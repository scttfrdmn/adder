"""Unit tests for adder/session.py — uses moto for S3/ECS mocks."""

from __future__ import annotations

import json
import re
import time
from unittest.mock import MagicMock, patch

import boto3
import cloudpickle
import pytest
from moto import mock_aws

from adder.config import Config
from adder.errors import BurstPartialError, BurstTimeoutError
from adder.session import (
    Session,
    SessionStatus,
    _chunk_items,
    _task_id,
    generate_session_id,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_cfg() -> Config:
    return Config(
        region="us-east-1",
        s3_bucket="burst-us-east-1",
        ecs_cluster="burst-cluster",
        ecr_base_uri="123456789012.dkr.ecr.us-east-1.amazonaws.com",
        execution_role_arn="arn:aws:iam::123456789012:role/burst-execution-role",
        task_role_arn="arn:aws:iam::123456789012:role/burst-task-role",
    )


# ── generate_session_id ───────────────────────────────────────────────────────

def test_session_id_format():
    sid = generate_session_id()
    assert re.match(r"^py-\d{8}-[0-9a-f]{8}$", sid), f"Bad session ID: {sid}"


def test_session_id_unique():
    ids = {generate_session_id() for _ in range(100)}
    assert len(ids) == 100


# ── _task_id ──────────────────────────────────────────────────────────────────

def test_task_id_format():
    assert _task_id(0) == "task-0000"
    assert _task_id(42) == "task-0042"
    assert _task_id(9999) == "task-9999"


# ── _chunk_items ──────────────────────────────────────────────────────────────

def test_chunk_items_even():
    chunks = _chunk_items(list(range(10)), 5)
    assert len(chunks) == 5
    assert all(len(c) == 2 for c in chunks)


def test_chunk_items_remainder():
    chunks = _chunk_items(list(range(11)), 5)
    assert len(chunks) == 5
    total = sum(len(c) for c in chunks)
    assert total == 11


def test_chunk_items_fewer_than_workers():
    """When items < workers, create one chunk per item."""
    chunks = _chunk_items([1, 2, 3], 10)
    assert len(chunks) == 3
    assert sum(len(c) for c in chunks) == 3


def test_chunk_items_empty():
    assert _chunk_items([], 10) == []


def test_chunk_items_preserves_order():
    items = list(range(100))
    chunks = _chunk_items(items, 7)
    reconstructed = [x for chunk in chunks for x in chunk]
    assert reconstructed == items


# ── Session.run with moto ─────────────────────────────────────────────────────

@mock_aws
def test_session_run_basic():
    """Session.run returns correct results using moto S3."""
    cfg = _make_cfg()

    # Create S3 bucket
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=cfg.s3_bucket)

    # Patch ECS and EC2 to avoid real calls
    session = Session(cfg, workers=3, cpu=1, memory_gb=1, backend="fargate",
                      spot=False, max_cost=None, cost_alert=None, timeout=None)

    items = [1, 2, 3, 4, 5]
    fn = lambda x: x * 2

    # Patch _launch_workers to simulate worker completion by writing status files
    def fake_launch(ecs, s3_client, session_id, image_uri, chunk_count):
        # Simulate workers completing: write result/status files
        import cloudpickle
        chunks = _chunk_items(items, min(3, len(items)))
        for i, chunk in enumerate(chunks):
            results = [x * 2 for x in chunk]
            result_data = cloudpickle.dumps(results)
            s3_client.put_object(
                Bucket=cfg.s3_bucket,
                Key=f"sessions/{session_id}/tasks/task-{i:04d}.result",
                Body=result_data,
            )
            s3_client.put_object(
                Bucket=cfg.s3_bucket,
                Key=f"sessions/{session_id}/tasks/task-{i:04d}.status",
                Body=b"done",
            )

    with patch.object(session, "_launch_workers", side_effect=fake_launch):
        results = session.run(items, fn, "fake-image-uri")

    assert results == [2, 4, 6, 8, 10]


@mock_aws
def test_session_run_out_of_order_results():
    """Results must be assembled in original order even if chunks complete out of order."""
    cfg = _make_cfg()
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=cfg.s3_bucket)

    items = list(range(6))
    fn = lambda x: x * 10

    session = Session(cfg, workers=3, cpu=1, memory_gb=1, backend="fargate",
                      spot=False, max_cost=None, cost_alert=None, timeout=None)

    def fake_launch(ecs, s3_client, session_id, image_uri, chunk_count):
        import cloudpickle
        chunks = _chunk_items(items, 3)
        # Write results in reverse order (simulating out-of-order completion)
        for i in reversed(range(len(chunks))):
            results = [x * 10 for x in chunks[i]]
            s3_client.put_object(
                Bucket=cfg.s3_bucket,
                Key=f"sessions/{session_id}/tasks/task-{i:04d}.result",
                Body=cloudpickle.dumps(results),
            )
            s3_client.put_object(
                Bucket=cfg.s3_bucket,
                Key=f"sessions/{session_id}/tasks/task-{i:04d}.status",
                Body=b"done",
            )

    with patch.object(session, "_launch_workers", side_effect=fake_launch):
        results = session.run(items, fn, "fake-image-uri")

    assert results == [0, 10, 20, 30, 40, 50]


@mock_aws
def test_session_run_partial_failure():
    """BurstPartialError raised when some chunks fail."""
    cfg = _make_cfg()
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=cfg.s3_bucket)

    items = [1, 2, 3, 4]
    fn = lambda x: x

    session = Session(cfg, workers=2, cpu=1, memory_gb=1, backend="fargate",
                      spot=False, max_cost=None, cost_alert=None, timeout=None)

    def fake_launch(ecs, s3_client, session_id, image_uri, chunk_count):
        import cloudpickle
        chunks = _chunk_items(items, 2)
        # First chunk succeeds
        s3_client.put_object(
            Bucket=cfg.s3_bucket,
            Key=f"sessions/{session_id}/tasks/task-0000.result",
            Body=cloudpickle.dumps([1, 2]),
        )
        s3_client.put_object(
            Bucket=cfg.s3_bucket,
            Key=f"sessions/{session_id}/tasks/task-0000.status",
            Body=b"done",
        )
        # Second chunk fails
        s3_client.put_object(
            Bucket=cfg.s3_bucket,
            Key=f"sessions/{session_id}/tasks/task-0001.error",
            Body=b"RuntimeError: something went wrong",
        )
        s3_client.put_object(
            Bucket=cfg.s3_bucket,
            Key=f"sessions/{session_id}/tasks/task-0001.status",
            Body=b"failed",
        )

    with patch.object(session, "_launch_workers", side_effect=fake_launch):
        with pytest.raises(BurstPartialError) as exc_info:
            session.run(items, fn, "fake-image-uri")

    err = exc_info.value
    assert err.failed_count == 1
    assert err.success_count >= 1
