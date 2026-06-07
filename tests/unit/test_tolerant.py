"""Unit tests for the tolerant map feature (Session._collect tolerant=True,
DetachedSession.collect tolerant=True, and adder.map_tolerant)."""

from __future__ import annotations

import json
from unittest.mock import patch

import boto3
import cloudpickle
import pytest
from moto import mock_aws

import adder
from adder.config import Config
from adder.errors import BurstPartialError
from adder.session import (
    DetachedSession,
    Session,
    _chunk_items,
    _task_key,
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


# ── Session._collect(tolerant=True) ──────────────────────────────────────────


@mock_aws
def test_collect_tolerant_all_success():
    """tolerant=True returns (results, errors) tuple with all-None errors on success."""
    cfg = _make_cfg()
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=cfg.s3_bucket)

    session_id = "py-20260315-tol00001"
    # Two chunks, both succeed
    for i, chunk_results in enumerate([[0, 2], [4, 6]]):
        s3.put_object(
            Bucket=cfg.s3_bucket,
            Key=_task_key(session_id, i, "result"),
            Body=cloudpickle.dumps(chunk_results),
        )
        s3.put_object(
            Bucket=cfg.s3_bucket,
            Key=_task_key(session_id, i, "status"),
            Body=b"done",
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
    import time
    result = sess._collect(s3, session_id, 2, time.monotonic(), tolerant=True)

    assert isinstance(result, tuple)
    results, errors = result
    assert results == [0, 2, 4, 6]
    assert all(e is None for e in errors)


@mock_aws
def test_collect_tolerant_partial_failure():
    """tolerant=True returns (results, errors) with None where chunks failed."""
    cfg = _make_cfg()
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=cfg.s3_bucket)

    session_id = "py-20260315-tol00002"
    # chunk 0 succeeds
    s3.put_object(
        Bucket=cfg.s3_bucket,
        Key=_task_key(session_id, 0, "result"),
        Body=cloudpickle.dumps([0, 2]),
    )
    s3.put_object(
        Bucket=cfg.s3_bucket,
        Key=_task_key(session_id, 0, "status"),
        Body=b"done",
    )
    # chunk 1 fails
    s3.put_object(
        Bucket=cfg.s3_bucket,
        Key=_task_key(session_id, 1, "error"),
        Body=b"RuntimeError: item failed",
    )
    s3.put_object(
        Bucket=cfg.s3_bucket,
        Key=_task_key(session_id, 1, "status"),
        Body=b"failed",
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
    import time
    result = sess._collect(s3, session_id, 2, time.monotonic(), tolerant=True)

    assert isinstance(result, tuple)
    results, errors = result
    # chunk 0: two successes
    assert results[0] == 0
    assert results[1] == 2
    assert errors[0] is None
    assert errors[1] is None
    # chunk 1 failed: one None result, one error string
    assert results[2] is None
    assert errors[2] is not None


@mock_aws
def test_collect_tolerant_does_not_raise_burst_partial_error():
    """tolerant=True must never raise BurstPartialError even with failures."""
    cfg = _make_cfg()
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=cfg.s3_bucket)

    session_id = "py-20260315-tol00003"
    # All chunks fail
    for i in range(3):
        s3.put_object(
            Bucket=cfg.s3_bucket,
            Key=_task_key(session_id, i, "error"),
            Body=b"Task failed completely",
        )
        s3.put_object(
            Bucket=cfg.s3_bucket,
            Key=_task_key(session_id, i, "status"),
            Body=b"failed",
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
    import time
    # Must not raise
    result = sess._collect(s3, session_id, 3, time.monotonic(), tolerant=True)
    results, errors = result
    assert all(r is None for r in results)
    assert all(e is not None for e in errors)


@mock_aws
def test_collect_non_tolerant_still_raises():
    """tolerant=False (default) preserves existing raise-on-failure behavior."""
    cfg = _make_cfg()
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=cfg.s3_bucket)

    session_id = "py-20260315-tol00004"
    s3.put_object(
        Bucket=cfg.s3_bucket,
        Key=_task_key(session_id, 0, "result"),
        Body=cloudpickle.dumps([10]),
    )
    s3.put_object(
        Bucket=cfg.s3_bucket,
        Key=_task_key(session_id, 0, "status"),
        Body=b"done",
    )
    s3.put_object(
        Bucket=cfg.s3_bucket,
        Key=_task_key(session_id, 1, "error"),
        Body=b"failure",
    )
    s3.put_object(
        Bucket=cfg.s3_bucket,
        Key=_task_key(session_id, 1, "status"),
        Body=b"failed",
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
    import time
    with pytest.raises(BurstPartialError):
        sess._collect(s3, session_id, 2, time.monotonic(), tolerant=False)


# ── DetachedSession.collect(tolerant=True) ────────────────────────────────────


@mock_aws
def test_detached_collect_tolerant_partial_failure():
    """DetachedSession.collect(tolerant=True) returns tuple without raising."""
    cfg = _make_cfg()
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=cfg.s3_bucket)

    session_id = "py-20260315-tol00005"
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
    # chunk 0 succeeds
    s3.put_object(
        Bucket=cfg.s3_bucket,
        Key=_task_key(session_id, 0, "result"),
        Body=cloudpickle.dumps([100, 200]),
    )
    s3.put_object(
        Bucket=cfg.s3_bucket,
        Key=_task_key(session_id, 0, "status"),
        Body=b"done",
    )
    # chunk 1 fails
    s3.put_object(
        Bucket=cfg.s3_bucket,
        Key=_task_key(session_id, 1, "error"),
        Body=b"Something went wrong",
    )
    s3.put_object(
        Bucket=cfg.s3_bucket,
        Key=_task_key(session_id, 1, "status"),
        Body=b"failed",
    )

    ds = DetachedSession(session_id=session_id, cfg=cfg)
    result = ds.collect(tolerant=True)

    assert isinstance(result, tuple)
    results, errors = result
    assert results[0] == 100
    assert results[1] == 200
    assert errors[0] is None
    assert errors[1] is None
    assert results[2] is None
    assert errors[2] is not None


# ── adder.map_tolerant (unit: mock Session._collect) ─────────────────────────


@mock_aws
def test_session_run_tolerant_via_collect():
    """Session._collect(tolerant=True) returns tuple when partial failure occurs."""
    cfg = _make_cfg()
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=cfg.s3_bucket)

    items = [0, 1, 2, 3]

    session = Session(
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

    def fake_launch(ecs, s3_client, session_id, image_uri, chunk_count):
        # chunk 0 = [0, 1] — succeeds with doubled values
        s3_client.put_object(
            Bucket=cfg.s3_bucket,
            Key=f"sessions/{session_id}/tasks/task-0000.result",
            Body=cloudpickle.dumps([0, 2]),
        )
        s3_client.put_object(
            Bucket=cfg.s3_bucket,
            Key=f"sessions/{session_id}/tasks/task-0000.status",
            Body=b"done",
        )
        # chunk 1 = [2, 3] — fails
        s3_client.put_object(
            Bucket=cfg.s3_bucket,
            Key=f"sessions/{session_id}/tasks/task-0001.error",
            Body=b"Worker error on odd numbers",
        )
        s3_client.put_object(
            Bucket=cfg.s3_bucket,
            Key=f"sessions/{session_id}/tasks/task-0001.status",
            Body=b"failed",
        )

    # Use _collect directly with tolerant=True after a fake launch
    with patch.object(session, "_launch_workers", side_effect=fake_launch):
        # We can't call session.run() here (it doesn't expose tolerant),
        # but we validate the _collect path in isolation via fake S3 state.
        import time
        session_id = "py-20260315-tolrun01"
        fake_launch(None, s3, session_id, None, 2)
        start = time.monotonic()
        result = session._collect(s3, session_id, 2, start, tolerant=True)

    results, errors = result
    # chunk 0: two successes
    assert results[0] == 0
    assert results[1] == 2
    assert errors[0] is None
    assert errors[1] is None
    # chunk 1: one failure slot
    assert results[2] is None
    assert errors[2] is not None


def test_map_tolerant_empty_items(tmp_path, monkeypatch):
    """map_tolerant with empty items returns ([], []) without AWS calls."""
    import dataclasses
    cfg = _make_cfg()
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(dataclasses.asdict(cfg)))
    monkeypatch.setenv("BURST_CONFIG_PATH", str(config_file))

    results, errors = adder.map_tolerant([], lambda x: x)
    assert results == []
    assert errors == []
