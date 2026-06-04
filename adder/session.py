"""Session and DetachedSession — manages the full 7-step worker lifecycle."""

from __future__ import annotations

import concurrent.futures
import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

import boto3
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from . import cost as cost_mod
from .config import Config, load as load_config
from .errors import BurstCostLimitError, BurstPartialError, BurstTimeoutError
from .serialize import deserialize_result, serialize_task

T = TypeVar("T")
U = TypeVar("U")

_POLL_INTERVAL = 2.0  # seconds between S3 status polls


@dataclass
class SessionStatus:
    session_id: str
    status: str  # initializing|running|complete|failed|partial
    tasks_total: int
    tasks_complete: int
    tasks_failed: int
    workers_active: int
    elapsed_seconds: float
    cost_actual: float
    cost_estimate: float


def generate_session_id() -> str:
    """Generate a session ID in the format py-{yyyymmdd}-{random8hex}."""
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    rand_hex = secrets.token_hex(4)
    return f"py-{date_str}-{rand_hex}"


def _task_id(index: int) -> str:
    return f"task-{index:04d}"


def _task_key(session_id: str, task_index: int, ext: str) -> str:
    return f"sessions/{session_id}/tasks/{_task_id(task_index)}.{ext}"


def _manifest_key(session_id: str) -> str:
    return f"sessions/{session_id}/manifest.json"


def _chunk_items(items: list, n: int) -> list[list]:
    """Split items into n roughly equal chunks."""
    if not items:
        return []
    n = min(n, len(items))
    size, rem = divmod(len(items), n)
    chunks = []
    start = 0
    for i in range(n):
        end = start + size + (1 if i < rem else 0)
        chunks.append(items[start:end])
        start = end
    return chunks


def _boto3_client(service: str, region: str) -> Any:
    return boto3.client(service, region_name=region)


class Session:
    """Manages the full 7-step worker lifecycle synchronously."""

    def __init__(
        self,
        cfg: Config,
        workers: int,
        cpu: int,
        memory_gb: int,
        backend: str,
        spot: bool,
        max_cost: float | None,
        cost_alert: float | None,
        timeout: int | None,
    ) -> None:
        self._cfg = cfg
        self._workers = workers
        self._cpu = cpu
        self._memory_gb = memory_gb
        self._backend = backend
        self._spot = spot
        self._max_cost = max_cost
        self._cost_alert = cost_alert
        self._timeout = timeout

    def run(self, items: list, fn: Callable, image_uri: str) -> list:
        """Execute the full 7-step lifecycle. Returns results in original order."""
        cfg = self._cfg
        items = list(items)
        if not items:
            return []

        # Step 1: Already done (image_uri passed in)

        # Step 2: Session initialization — cost/quota checks before any AWS calls
        rate = cost_mod.estimate_cost_per_hour(self._cpu, self._memory_gb, self._workers)

        cost_mod.print_start(self._workers)
        cost_mod.print_cost_estimate(rate)

        if self._cost_alert and rate > self._cost_alert:
            cost_mod.print_cost_alert(self._cost_alert)

        if self._max_cost is not None and rate > self._max_cost:
            raise BurstCostLimitError(
                limit=self._max_cost,
                estimated=rate,
                partial_results=[],
            )

        s3 = _boto3_client("s3", cfg.region)
        ecs = _boto3_client("ecs", cfg.region)

        session_id = generate_session_id()
        start_time = time.monotonic()

        # Check / adjust worker count against quota
        actual_workers = self._workers
        if cfg.fargate_quota_vcpu > 0:
            max_workers = int(cfg.fargate_quota_vcpu // self._cpu)
            if max_workers < self._workers:
                cost_mod.print_quota_warning(
                    self._workers,
                    self._workers * self._cpu,
                    max_workers,
                    max_workers * self._cpu,
                )
                actual_workers = max_workers

        chunks = _chunk_items(items, actual_workers)
        chunk_count = len(chunks)
        avg_chunk = len(items) // chunk_count if chunk_count else 0

        cost_mod.print_processing(len(items), actual_workers)
        cost_mod.print_chunks(chunk_count, avg_chunk)

        # Write manifest
        manifest = {
            "session_id": session_id,
            "language": "python",
            "library_version": "0.1.0",
            "status": "initializing",
            "workers_requested": self._workers,
            "workers_actual": actual_workers,
            "cpu": self._cpu,
            "memory_gb": self._memory_gb,
            "backend": self._backend,
            "spot": self._spot,
            "region": cfg.region,
            "cost_estimate_per_hour": rate,
            "task_count": chunk_count,
            "chunk_count": chunk_count,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "tasks_total": chunk_count,
            "tasks_complete": 0,
            "tasks_failed": 0,
            "workers_active": 0,
            "cost_actual": 0.0,
        }
        s3.put_object(
            Bucket=cfg.s3_bucket,
            Key=_manifest_key(session_id),
            Body=json.dumps(manifest).encode(),
        )

        # Step 3: Upload task files
        for i, chunk in enumerate(chunks):
            task_data = serialize_task(fn, chunk)
            s3.put_object(
                Bucket=cfg.s3_bucket,
                Key=_task_key(session_id, i, "task"),
                Body=task_data,
            )

        # Step 4: Launch ECS workers
        self._launch_workers(ecs, s3, session_id, image_uri, chunk_count)
        cost_mod.print_submitted(chunk_count)

        # Step 5: Poll and collect
        results = self._collect(s3, session_id, chunk_count, start_time)

        elapsed = time.monotonic() - start_time
        cost_mod.print_completed(f"{elapsed:.1f}s")
        actual_cost = cost_mod.estimate_cost(
            self._cpu, self._memory_gb, actual_workers, elapsed / 3600
        )
        cost_mod.print_actual_cost(actual_cost)

        # Cleanup task files
        self._cleanup_tasks(s3, session_id, chunk_count)

        return results

    def _launch_workers(
        self,
        ecs: Any,
        s3: Any,
        session_id: str,
        image_uri: str,
        chunk_count: int,
    ) -> None:
        cfg = self._cfg

        # Describe VPC subnets/security groups
        ec2 = _boto3_client("ec2", cfg.region)
        vpc_resp = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])
        vpc_id = vpc_resp["Vpcs"][0]["VpcId"]
        subnets_resp = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
        subnet_ids = [s["SubnetId"] for s in subnets_resp["Subnets"]]
        sg_resp = ec2.describe_security_groups(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": "group-name", "Values": ["default"]},
            ]
        )
        sg_ids = [g["GroupId"] for g in sg_resp["SecurityGroups"]]

        # Register task definition
        task_def = {
            "family": f"burst-{session_id}",
            "taskRoleArn": cfg.task_role_arn,
            "executionRoleArn": cfg.execution_role_arn,
            "networkMode": "awsvpc",
            "requiresCompatibilities": ["FARGATE"],
            "cpu": str(self._cpu * 1024),
            "memory": str(self._memory_gb * 1024),
            "containerDefinitions": [
                {
                    "name": "burst-worker",
                    "image": image_uri,
                    "essential": True,
                    "environment": [
                        {"name": "BURST_SESSION_ID", "value": session_id},
                        {"name": "BURST_S3_BUCKET", "value": cfg.s3_bucket},
                        {"name": "BURST_REGION", "value": cfg.region},
                        {"name": "BURST_LANG", "value": "python"},
                    ],
                    "logConfiguration": {
                        "logDriver": "awslogs",
                        "options": {
                            "awslogs-group": "/ecs/burst",
                            "awslogs-region": cfg.region,
                            "awslogs-stream-prefix": "burst",
                        },
                    },
                }
            ],
        }
        reg_resp = ecs.register_task_definition(**task_def)
        task_def_arn = reg_resp["taskDefinition"]["taskDefinitionArn"]

        launch_type = "FARGATE_SPOT" if self._spot else "FARGATE"

        # Wave-based launch if quota limits workers
        wave_size = chunk_count
        if self._cfg.fargate_quota_vcpu > 0:
            max_at_once = int(self._cfg.fargate_quota_vcpu // self._cpu)
            if max_at_once < chunk_count:
                wave_size = max_at_once

        launched = 0
        while launched < chunk_count:
            wave_end = min(launched + wave_size, chunk_count)
            for i in range(launched, wave_end):
                task_id = _task_id(i)
                ecs.run_task(
                    cluster=cfg.ecs_cluster,
                    taskDefinition=task_def_arn,
                    launchType=launch_type,
                    networkConfiguration={
                        "awsvpcConfiguration": {
                            "subnets": subnet_ids,
                            "securityGroups": sg_ids,
                            "assignPublicIp": "ENABLED",
                        }
                    },
                    overrides={
                        "containerOverrides": [
                            {
                                "name": "burst-worker",
                                "environment": [
                                    {"name": "BURST_TASK_ID", "value": task_id},
                                ],
                            }
                        ]
                    },
                    tags=[{"key": "burst-session-id", "value": session_id}],
                )
            launched = wave_end
            # If more waves, wait for this wave to finish before launching next
            if launched < chunk_count:
                self._wait_wave(s3, session_id, launched - wave_size, launched)

    def _wait_wave(self, s3: Any, session_id: str, start: int, end: int) -> None:
        """Poll until all tasks in [start, end) are in a terminal state."""
        cfg = self._cfg
        while True:
            done = True
            for i in range(start, end):
                key = _task_key(session_id, i, "status")
                try:
                    resp = s3.get_object(Bucket=cfg.s3_bucket, Key=key)
                    status = resp["Body"].read().decode()
                    if status not in ("done", "failed"):
                        done = False
                        break
                except Exception:
                    done = False
                    break
            if done:
                return
            time.sleep(_POLL_INTERVAL)

    def _collect(
        self,
        s3: Any,
        session_id: str,
        chunk_count: int,
        start_time: float,
    ) -> list:
        """Poll until all tasks complete, then download and assemble results."""
        cfg = self._cfg
        deadline = start_time + self._timeout if self._timeout is not None else None

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
        ) as progress:
            task = progress.add_task("Collecting results", total=chunk_count)

            while True:
                if deadline and time.monotonic() > deadline:
                    status = self._get_status(s3, session_id, chunk_count, start_time)
                    raise BurstTimeoutError(
                        session_id=session_id,
                        timeout_seconds=self._timeout,  # type: ignore[arg-type]
                        status=status,
                    )

                done_count, failed_count = self._count_statuses(s3, session_id, chunk_count)
                progress.update(task, completed=done_count + failed_count)

                if done_count + failed_count >= chunk_count:
                    break

                time.sleep(_POLL_INTERVAL)

        # Download results concurrently
        results_by_chunk: dict[int, list] = {}
        errors_by_chunk: dict[int, str] = {}

        def download_chunk(i: int) -> None:
            key = _task_key(session_id, i, "status")
            try:
                resp = s3.get_object(Bucket=cfg.s3_bucket, Key=key)
                status = resp["Body"].read().decode()
            except Exception:
                status = "failed"

            if status == "done":
                result_key = _task_key(session_id, i, "result")
                data = s3.get_object(Bucket=cfg.s3_bucket, Key=result_key)["Body"].read()
                results_by_chunk[i] = deserialize_result(data)
            else:
                error_key = _task_key(session_id, i, "error")
                try:
                    err_data = s3.get_object(Bucket=cfg.s3_bucket, Key=error_key)["Body"].read()
                    errors_by_chunk[i] = err_data.decode()
                except Exception:
                    errors_by_chunk[i] = f"Task {_task_id(i)} failed with unknown error"

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            list(pool.map(download_chunk, range(chunk_count)))

        # Assemble in order
        all_results = []
        all_errors = []
        any_failed = bool(errors_by_chunk)

        for i in range(chunk_count):
            if i in results_by_chunk:
                chunk_results = results_by_chunk[i]
                all_results.extend(chunk_results)
                all_errors.extend([None] * len(chunk_results))
            else:
                # Estimate chunk size from errors
                all_results.append(None)
                all_errors.append(errors_by_chunk.get(i, "unknown error"))

        if any_failed:
            raise BurstPartialError(results=all_results, errors=all_errors)

        return all_results

    def _count_statuses(self, s3: Any, session_id: str, chunk_count: int) -> tuple[int, int]:
        """Return (done_count, failed_count) across all tasks."""
        cfg = self._cfg
        done = 0
        failed = 0
        for i in range(chunk_count):
            key = _task_key(session_id, i, "status")
            try:
                resp = s3.get_object(Bucket=cfg.s3_bucket, Key=key)
                status = resp["Body"].read().decode()
                if status == "done":
                    done += 1
                elif status == "failed":
                    failed += 1
            except Exception:
                pass
        return done, failed

    def _get_status(
        self, s3: Any, session_id: str, chunk_count: int, start_time: float
    ) -> SessionStatus:
        done, failed = self._count_statuses(s3, session_id, chunk_count)
        elapsed = time.monotonic() - start_time
        return SessionStatus(
            session_id=session_id,
            status="running",
            tasks_total=chunk_count,
            tasks_complete=done,
            tasks_failed=failed,
            workers_active=chunk_count - done - failed,
            elapsed_seconds=elapsed,
            cost_actual=0.0,
            cost_estimate=cost_mod.estimate_cost_per_hour(
                self._cpu, self._memory_gb, self._workers
            ),
        )

    def _cleanup_tasks(self, s3: Any, session_id: str, chunk_count: int) -> None:
        """Delete task/result/status/error files (keep manifest)."""
        cfg = self._cfg
        for i in range(chunk_count):
            for ext in ("task", "result", "status", "error"):
                try:
                    s3.delete_object(Bucket=cfg.s3_bucket, Key=_task_key(session_id, i, ext))
                except Exception:
                    pass


class DetachedSession:
    """A session that runs asynchronously — process can exit after submit()."""

    def __init__(self, session_id: str, cfg: Config) -> None:
        self._session_id = session_id
        self._cfg = cfg

    @property
    def session_id(self) -> str:
        return self._session_id

    def status(self) -> SessionStatus:
        """Read current status from S3 manifest."""
        s3 = _boto3_client("s3", self._cfg.region)
        resp = s3.get_object(Bucket=self._cfg.s3_bucket, Key=_manifest_key(self._session_id))
        data = json.loads(resp["Body"].read())
        return SessionStatus(
            session_id=data["session_id"],
            status=data["status"],
            tasks_total=data.get("tasks_total", 0),
            tasks_complete=data.get("tasks_complete", 0),
            tasks_failed=data.get("tasks_failed", 0),
            workers_active=data.get("workers_active", 0),
            elapsed_seconds=data.get("elapsed_seconds", 0.0),
            cost_actual=data.get("cost_actual", 0.0),
            cost_estimate=data.get("cost_estimate_per_hour", 0.0),
        )

    def collect(self, timeout: int | None = None) -> list:
        """Block until all tasks complete, then return results in order."""
        cfg = self._cfg
        s3 = _boto3_client("s3", cfg.region)

        # Read manifest to get chunk count and config
        resp = s3.get_object(Bucket=cfg.s3_bucket, Key=_manifest_key(self._session_id))
        manifest = json.loads(resp["Body"].read())
        chunk_count = manifest["chunk_count"]
        manifest["cpu"]
        manifest["memory_gb"]
        manifest["workers_actual"]

        deadline = time.monotonic() + timeout if timeout is not None else None

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
        ) as progress:
            ptask = progress.add_task("Collecting results", total=chunk_count)

            while True:
                if deadline and time.monotonic() > deadline:
                    st = self.status()
                    raise BurstTimeoutError(
                        session_id=self._session_id,
                        timeout_seconds=timeout,  # type: ignore[arg-type]
                        status=st,
                    )

                done = failed = 0
                for i in range(chunk_count):
                    key = _task_key(self._session_id, i, "status")
                    try:
                        r = s3.get_object(Bucket=cfg.s3_bucket, Key=key)
                        st = r["Body"].read().decode()
                        if st == "done":
                            done += 1
                        elif st == "failed":
                            failed += 1
                    except Exception:
                        pass
                progress.update(ptask, completed=done + failed)
                if done + failed >= chunk_count:
                    break
                time.sleep(_POLL_INTERVAL)

        # Download and assemble
        results_by_chunk: dict[int, list] = {}
        errors_by_chunk: dict[int, str] = {}

        def download(i: int) -> None:
            key = _task_key(self._session_id, i, "status")
            try:
                r = s3.get_object(Bucket=cfg.s3_bucket, Key=key)
                status = r["Body"].read().decode()
            except Exception:
                status = "failed"

            if status == "done":
                rkey = _task_key(self._session_id, i, "result")
                data = s3.get_object(Bucket=cfg.s3_bucket, Key=rkey)["Body"].read()
                results_by_chunk[i] = deserialize_result(data)
            else:
                ekey = _task_key(self._session_id, i, "error")
                try:
                    err = s3.get_object(Bucket=cfg.s3_bucket, Key=ekey)["Body"].read()
                    errors_by_chunk[i] = err.decode()
                except Exception:
                    errors_by_chunk[i] = f"Task {_task_id(i)} failed"

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            list(pool.map(download, range(chunk_count)))

        all_results: list = []
        all_errors: list = []
        any_failed = bool(errors_by_chunk)

        for i in range(chunk_count):
            if i in results_by_chunk:
                chunk_results = results_by_chunk[i]
                all_results.extend(chunk_results)
                all_errors.extend([None] * len(chunk_results))
            else:
                all_results.append(None)
                all_errors.append(errors_by_chunk.get(i, "unknown error"))

        if any_failed:
            raise BurstPartialError(results=all_results, errors=all_errors)

        return all_results

    def cleanup(self) -> None:
        """Delete all S3 objects for this session."""
        cfg = self._cfg
        s3 = _boto3_client("s3", cfg.region)
        prefix = f"sessions/{self._session_id}/"
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=cfg.s3_bucket, Prefix=prefix):
            objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if objects:
                s3.delete_objects(Bucket=cfg.s3_bucket, Delete={"Objects": objects})


def submit_detached(items: list, fn: Callable, cfg: Config, **kwargs: Any) -> str:
    """Start a detached session. Returns the session_id.

    The calling process can exit after this returns.
    """
    from .env import ensure_image

    workers = kwargs.get("workers", cfg.default_workers)
    cpu = kwargs.get("cpu", cfg.default_cpu)
    memory_gb = kwargs.get("memory_gb", cfg.default_memory_gb)
    backend = kwargs.get("backend", cfg.backend)
    spot = kwargs.get("spot", cfg.spot)

    image_uri = ensure_image(cfg)
    items = list(items)
    chunks = _chunk_items(items, workers)
    session_id = generate_session_id()

    s3 = _boto3_client("s3", cfg.region)
    ecs = _boto3_client("ecs", cfg.region)

    manifest = {
        "session_id": session_id,
        "language": "python",
        "library_version": "0.1.0",
        "status": "initializing",
        "workers_requested": workers,
        "workers_actual": len(chunks),
        "cpu": cpu,
        "memory_gb": memory_gb,
        "backend": backend,
        "spot": spot,
        "region": cfg.region,
        "cost_estimate_per_hour": cost_mod.estimate_cost_per_hour(cpu, memory_gb, workers),
        "task_count": len(chunks),
        "chunk_count": len(chunks),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "tasks_total": len(chunks),
        "tasks_complete": 0,
        "tasks_failed": 0,
        "workers_active": 0,
        "cost_actual": 0.0,
    }
    s3.put_object(
        Bucket=cfg.s3_bucket,
        Key=_manifest_key(session_id),
        Body=json.dumps(manifest).encode(),
    )

    for i, chunk in enumerate(chunks):
        s3.put_object(
            Bucket=cfg.s3_bucket,
            Key=_task_key(session_id, i, "task"),
            Body=serialize_task(fn, chunk),
        )

    # Launch workers (reuse Session helper)
    sess = Session(cfg, workers, cpu, memory_gb, backend, spot, None, None, None)
    sess._launch_workers(ecs, s3, session_id, image_uri, len(chunks))

    return session_id


def attach(session_id: str, cfg: Config | None = None) -> DetachedSession:
    """Reattach to an existing detached session."""
    if cfg is None:
        cfg = load_config()
    return DetachedSession(session_id=session_id, cfg=cfg)
