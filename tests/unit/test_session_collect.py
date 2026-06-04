"""Additional unit tests for Session collection, cleanup, and DetachedSession paths."""

from __future__ import annotations

import json
from unittest.mock import patch

import boto3
import cloudpickle
import pytest
from moto import mock_aws

from adder.config import Config
from adder.errors import BurstTimeoutError
from adder.session import (
    DetachedSession,
    Session,
    _task_key,
    attach,
)


def _make_cfg() -> Config:
    return Config(
        region="us-east-1",
        s3_bucket="burst-us-east-1",
        ecs_cluster="burst-cluster",
        ecr_base_uri="123456789012.dkr.ecr.us-east-1.amazonaws.com",
        execution_role_arn="arn:aws:iam::123456789012:role/burst-execution-role",
        task_role_arn="arn:aws:iam::123456789012:role/burst-task-role",
    )


# ── Session._count_statuses ───────────────────────────────────────────────────


@mock_aws
def test_count_statuses_all_done():
    cfg = _make_cfg()
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=cfg.s3_bucket)

    session_id = "py-20260315-aabbccdd"
    for i in range(3):
        s3.put_object(
            Bucket=cfg.s3_bucket,
            Key=_task_key(session_id, i, "status"),
            Body=b"done",
        )

    sess = Session(
        cfg,
        workers=3,
        cpu=1,
        memory_gb=1,
        backend="fargate",
        spot=False,
        max_cost=None,
        cost_alert=None,
        timeout=None,
    )
    done, failed = sess._count_statuses(s3, session_id, 3)
    assert done == 3
    assert failed == 0


@mock_aws
def test_count_statuses_mixed():
    cfg = _make_cfg()
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=cfg.s3_bucket)

    session_id = "py-20260315-aabbccdd"
    s3.put_object(Bucket=cfg.s3_bucket, Key=_task_key(session_id, 0, "status"), Body=b"done")
    s3.put_object(Bucket=cfg.s3_bucket, Key=_task_key(session_id, 1, "status"), Body=b"failed")
    # task 2 has no status yet

    sess = Session(
        cfg,
        workers=3,
        cpu=1,
        memory_gb=1,
        backend="fargate",
        spot=False,
        max_cost=None,
        cost_alert=None,
        timeout=None,
    )
    done, failed = sess._count_statuses(s3, session_id, 3)
    assert done == 1
    assert failed == 1


# ── Session._cleanup_tasks ────────────────────────────────────────────────────


@mock_aws
def test_cleanup_tasks_removes_all():
    cfg = _make_cfg()
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=cfg.s3_bucket)

    session_id = "py-20260315-cleanup01"
    for i in range(2):
        for ext in ("task", "result", "status"):
            s3.put_object(
                Bucket=cfg.s3_bucket,
                Key=_task_key(session_id, i, ext),
                Body=b"data",
            )

    sess = Session(
        cfg,
        workers=2,
        cpu=1,
        memory_gb=1,
        backend="fargate",
        spot=False,
        max_cost=None,
        cost_alert=None,
        timeout=None,
    )
    sess._cleanup_tasks(s3, session_id, 2)

    # All task files should be gone
    for i in range(2):
        for ext in ("task", "result", "status"):
            with pytest.raises(Exception):
                s3.get_object(Bucket=cfg.s3_bucket, Key=_task_key(session_id, i, ext))


# ── DetachedSession ───────────────────────────────────────────────────────────


@mock_aws
def test_detached_session_status():
    cfg = _make_cfg()
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=cfg.s3_bucket)

    session_id = "py-20260315-detach01"
    manifest = {
        "session_id": session_id,
        "status": "running",
        "tasks_total": 5,
        "tasks_complete": 3,
        "tasks_failed": 0,
        "workers_active": 2,
        "elapsed_seconds": 15.3,
        "cost_actual": 0.0,
        "cost_estimate_per_hour": 2.5,
    }
    s3.put_object(
        Bucket=cfg.s3_bucket,
        Key=f"sessions/{session_id}/manifest.json",
        Body=json.dumps(manifest).encode(),
    )

    ds = DetachedSession(session_id=session_id, cfg=cfg)
    status = ds.status()

    assert status.session_id == session_id
    assert status.status == "running"
    assert status.tasks_total == 5
    assert status.tasks_complete == 3


@mock_aws
def test_detached_session_collect():
    cfg = _make_cfg()
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=cfg.s3_bucket)

    session_id = "py-20260315-detach02"
    manifest = {
        "session_id": session_id,
        "status": "running",
        "tasks_total": 2,
        "tasks_complete": 0,
        "tasks_failed": 0,
        "workers_active": 2,
        "elapsed_seconds": 0.0,
        "cost_actual": 0.0,
        "cost_estimate_per_hour": 1.0,
        "chunk_count": 2,
        "cpu": 1,
        "memory_gb": 1,
        "workers_actual": 2,
    }
    s3.put_object(
        Bucket=cfg.s3_bucket,
        Key=f"sessions/{session_id}/manifest.json",
        Body=json.dumps(manifest).encode(),
    )

    # Write results to S3
    for i in range(2):
        results = [i * 10 + j for j in range(3)]
        s3.put_object(
            Bucket=cfg.s3_bucket,
            Key=_task_key(session_id, i, "result"),
            Body=cloudpickle.dumps(results),
        )
        s3.put_object(
            Bucket=cfg.s3_bucket,
            Key=_task_key(session_id, i, "status"),
            Body=b"done",
        )

    ds = DetachedSession(session_id=session_id, cfg=cfg)
    results = ds.collect()
    assert results == [0, 1, 2, 10, 11, 12]


@mock_aws
def test_detached_session_cleanup():
    cfg = _make_cfg()
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=cfg.s3_bucket)

    session_id = "py-20260315-cleanup02"
    for key in [
        f"sessions/{session_id}/manifest.json",
        f"sessions/{session_id}/tasks/task-0000.task",
        f"sessions/{session_id}/tasks/task-0000.result",
    ]:
        s3.put_object(Bucket=cfg.s3_bucket, Key=key, Body=b"data")

    ds = DetachedSession(session_id=session_id, cfg=cfg)
    ds.cleanup()

    # All objects should be gone
    resp = s3.list_objects_v2(Bucket=cfg.s3_bucket, Prefix=f"sessions/{session_id}/")
    assert resp.get("KeyCount", 0) == 0


def test_attach_returns_detached_session(tmp_path, monkeypatch):
    import json
    import dataclasses
    from adder.config import Config

    cfg = Config(
        region="us-east-1",
        s3_bucket="burst-us-east-1",
        ecr_base_uri="123.dkr.ecr.us-east-1.amazonaws.com",
        execution_role_arn="arn:aws:iam::123:role/exec",
        task_role_arn="arn:aws:iam::123:role/task",
    )
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(dataclasses.asdict(cfg)))
    monkeypatch.setenv("BURST_CONFIG_PATH", str(config_file))

    session_id = "py-20260315-attach01"
    ds = attach(session_id)
    assert isinstance(ds, DetachedSession)
    assert ds.session_id == session_id


# ── Session timeout ───────────────────────────────────────────────────────────


@mock_aws
def test_session_run_timeout():
    """BurstTimeoutError when timeout expires before tasks complete."""
    cfg = _make_cfg()
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=cfg.s3_bucket)

    items = [1, 2, 3]
    def fn(x):
        return x

    session = Session(
        cfg,
        workers=3,
        cpu=1,
        memory_gb=1,
        backend="fargate",
        spot=False,
        max_cost=None,
        cost_alert=None,
        timeout=0,
    )  # 0 seconds = immediate

    def fake_launch(ecs, s3_client, session_id, image_uri, chunk_count):
        # Don't write any results — tasks never complete
        pass

    with patch.object(session, "_launch_workers", side_effect=fake_launch):
        with pytest.raises(BurstTimeoutError) as exc_info:
            session.run(items, fn, "fake-image")

    err = exc_info.value
    assert err.timeout_seconds == 0
    assert err.session_id != ""


# ── Session cost limit ────────────────────────────────────────────────────────


def test_session_run_cost_limit_exceeded(tmp_path, monkeypatch):
    """BurstCostLimitError when estimated cost exceeds max_cost."""
    from adder.errors import BurstCostLimitError

    cfg = _make_cfg()
    session = Session(
        cfg=cfg,
        workers=1000,
        cpu=16,
        memory_gb=32,
        backend="fargate",
        spot=False,
        max_cost=0.01,  # very low limit
        cost_alert=None,
        timeout=None,
    )

    with pytest.raises(BurstCostLimitError) as exc_info:
        session.run([1, 2, 3], lambda x: x, "fake-image")

    err = exc_info.value
    assert err.limit == 0.01
    assert err.estimated_cost > 0.01
