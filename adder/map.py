"""adder.map() — the primary user-facing API for cloud bursting."""

from __future__ import annotations

from typing import Callable, Iterable, Literal, TypeVar

from .executor import CloudExecutor

T = TypeVar("T")
U = TypeVar("U")


def _parse_memory_gb(memory: str) -> int:
    """Parse memory string like '4GB' or '512MB' into integer GB."""
    memory = memory.strip().upper()
    if memory.endswith("GB"):
        return int(memory[:-2])
    if memory.endswith("MB"):
        mb = int(memory[:-2])
        return max(1, mb // 1024)
    return int(memory)


def map(
    items: Iterable[T],
    fn: Callable[[T], U],
    *,
    workers: int = 10,
    cpu: int = 2,
    memory: str = "4GB",
    backend: Literal["fargate", "ec2"] = "fargate",
    spot: bool = False,
    max_cost: float | None = None,
    cost_alert: float | None = None,
    timeout: int | None = None,
    region: str | None = None,
    arch: str = "amd64",
) -> list[U]:
    """Distribute items across AWS ECS workers and collect results.

    Synchronous — blocks until all tasks complete or an error occurs.
    Returns results in the same order as the input items.

    Args:
        items: Input items to process.
        fn: Function to apply to each item.
        workers: Number of parallel ECS workers.
        cpu: vCPUs per worker (0.25, 0.5, 1, 2, 4, 8, 16).
        memory: Memory per worker (e.g. "4GB", "512MB").
        backend: "fargate" (serverless) or "ec2".
        spot: Use Fargate Spot for ~70% cost savings (with interruption risk).
        max_cost: Cancel job if estimated cost exceeds this USD amount.
        cost_alert: Print warning if estimated cost exceeds this USD amount.
        timeout: Maximum seconds to wait for completion.
        region: AWS region (defaults to ~/.burst/config.json value).
        arch: CPU architecture for ECS task ("amd64" or "arm64").

    Returns:
        List of results in the same order as items.

    Raises:
        BurstPartialError: If some tasks fail.
        BurstCostLimitError: If max_cost is exceeded.
        BurstQuotaError: If workers cannot be provisioned at requested count.
        BurstTimeoutError: If timeout is exceeded.
        BurstSetupError: If AWS configuration is missing (run `adder setup`).
    """
    with CloudExecutor(
        workers=workers,
        cpu=cpu,
        memory=memory,
        backend=backend,
        spot=spot,
        max_cost=max_cost,
        cost_alert=cost_alert,
        region=region,
        arch=arch,
    ) as executor:
        return list(executor.map(fn, items, timeout=float(timeout) if timeout else None))


def map_tolerant(
    items: Iterable[T],
    fn: Callable[[T], U],
    *,
    workers: int = 10,
    cpu: int = 2,
    memory: str = "4GB",
    backend: Literal["fargate", "ec2"] = "fargate",
    spot: bool = False,
    max_cost: float | None = None,
    cost_alert: float | None = None,
    timeout: int | None = None,
    region: str | None = None,
    arch: str = "amd64",
) -> tuple[list, list]:
    """Distribute items across AWS ECS workers, returning (results, errors).

    Like map() but never raises BurstPartialError. results[i] is None where
    item i failed; errors[i] is an error message string or None on success.

    Args:
        items: Input items to process.
        fn: Function to apply to each item.
        workers: Number of parallel ECS workers.
        cpu: vCPUs per worker (0.25, 0.5, 1, 2, 4, 8, 16).
        memory: Memory per worker (e.g. "4GB", "512MB").
        backend: "fargate" (serverless) or "ec2".
        spot: Use Fargate Spot for ~70% cost savings (with interruption risk).
        max_cost: Cancel job if estimated cost exceeds this USD amount.
        cost_alert: Print warning if estimated cost exceeds this USD amount.
        timeout: Maximum seconds to wait for completion.
        region: AWS region (defaults to ~/.burst/config.json value).
        arch: CPU architecture for ECS task ("amd64" or "arm64").

    Returns:
        Tuple of (results, errors). results[i] is the return value of fn(items[i])
        or None if the item failed. errors[i] is None on success or an error
        message string on failure.

    Raises:
        BurstCostLimitError: If max_cost is exceeded.
        BurstTimeoutError: If timeout is exceeded.
        BurstSetupError: If AWS configuration is missing (run `adder setup`).
    """
    items_list = list(items)
    if not items_list:
        return [], []

    from .config import load as load_config
    from .env import ensure_image
    from .session import Session

    cfg = load_config()
    if region:
        cfg.region = region

    cfg.validate()
    image_uri = ensure_image(cfg)

    sess = Session(
        cfg=cfg,
        workers=workers,
        cpu=cpu,
        memory_gb=_parse_memory_gb(memory),
        backend=backend,
        spot=spot,
        max_cost=max_cost,
        cost_alert=cost_alert,
        timeout=timeout,
        arch=arch,
    )

    # Run the session up to (but not including) _collect, then call _collect tolerant.
    # We reuse the Session.run() internals by calling _collect with tolerant=True.
    # To do this we inline the relevant parts of Session.run() here.
    import time
    from . import cost as cost_mod
    from .errors import BurstCostLimitError
    from .session import generate_session_id, _chunk_items, _task_key, _manifest_key, _boto3_client
    import json
    from datetime import datetime, timezone
    from .serialize import serialize_task

    rate = cost_mod.estimate_cost_per_hour(cpu, sess._memory_gb, workers)
    cost_mod.print_start(workers)
    cost_mod.print_cost_estimate(rate)

    if cost_alert and rate > cost_alert:
        cost_mod.print_cost_alert(cost_alert)

    if max_cost is not None and rate > max_cost:
        raise BurstCostLimitError(limit=max_cost, estimated=rate, partial_results=[])

    s3 = _boto3_client("s3", cfg.region)
    ecs = _boto3_client("ecs", cfg.region)

    session_id = generate_session_id()
    start_time = time.monotonic()

    actual_workers = workers
    if cfg.fargate_quota_vcpu > 0:
        max_workers = int(cfg.fargate_quota_vcpu // cpu)
        if max_workers < workers:
            cost_mod.print_quota_warning(workers, workers * cpu, max_workers, max_workers * cpu)
            actual_workers = max_workers

    chunks = _chunk_items(items_list, actual_workers)
    chunk_count = len(chunks)
    avg_chunk = len(items_list) // chunk_count if chunk_count else 0

    cost_mod.print_processing(len(items_list), actual_workers)
    cost_mod.print_chunks(chunk_count, avg_chunk)

    manifest = {
        "session_id": session_id,
        "language": "python",
        "library_version": "0.1.0",
        "status": "initializing",
        "workers_requested": workers,
        "workers_actual": actual_workers,
        "cpu": cpu,
        "memory_gb": sess._memory_gb,
        "backend": backend,
        "spot": spot,
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

    for i, chunk in enumerate(chunks):
        task_data = serialize_task(fn, chunk)
        s3.put_object(
            Bucket=cfg.s3_bucket,
            Key=_task_key(session_id, i, "task"),
            Body=task_data,
        )

    sess._launch_workers(ecs, s3, session_id, image_uri, chunk_count)
    cost_mod.print_submitted(chunk_count)

    results, errors = sess._collect(s3, session_id, chunk_count, start_time, tolerant=True)

    elapsed = time.monotonic() - start_time
    cost_mod.print_completed(f"{elapsed:.1f}s")
    actual_cost = cost_mod.estimate_cost(cpu, sess._memory_gb, actual_workers, elapsed / 3600)
    cost_mod.print_actual_cost(actual_cost)

    sess._cleanup_tasks(s3, session_id, chunk_count)

    return results, errors
