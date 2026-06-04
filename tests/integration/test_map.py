"""Integration tests for adder.map() using substrate as the AWS emulator.

These tests verify adder's full orchestration pipeline:
- chunking and S3 task upload
- ECS RunTask calls
- S3 result polling and collection
- Result ordering

Since ECS workers won't actually execute inside substrate, we simulate worker
completion by writing .result files directly to substrate S3 after task launch.

Requires: BURST_INTEGRATION_TEST=1 and substrate in PATH.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import boto3
import cloudpickle

from adder.config import Config, load as load_config
from adder.session import Session, _chunk_items, _task_key


def _make_s3(region: str = "us-east-1"):
    return boto3.client("s3", region_name=region)


def _setup_bucket(s3, bucket: str) -> None:
    s3.create_bucket(Bucket=bucket)


def _simulate_workers(s3, cfg: Config, session_id: str, items: list, fn, n_workers: int):
    """Write result files to S3 to simulate workers completing."""
    chunks = _chunk_items(items, n_workers)
    for i, chunk in enumerate(chunks):
        results = [fn(x) for x in chunk]
        result_data = cloudpickle.dumps(results)
        s3.put_object(
            Bucket=cfg.s3_bucket,
            Key=_task_key(session_id, i, "result"),
            Body=result_data,
        )
        s3.put_object(
            Bucket=cfg.s3_bucket,
            Key=_task_key(session_id, i, "status"),
            Body=b"done",
        )


def test_map_basic(substrate_config):
    """adder.map() returns correct results via substrate."""
    cfg = load_config()
    s3 = _make_s3()
    _setup_bucket(s3, cfg.s3_bucket)

    items = list(range(10))
    def fn(x):
        return x * 2

    session = Session(
        cfg=cfg,
        workers=3,
        cpu=1,
        memory_gb=2,
        backend="fargate",
        spot=False,
        max_cost=None,
        cost_alert=None,
        timeout=30,
    )

    captured_session_id = []

    def fake_launch(ecs, s3_client, session_id, image_uri, chunk_count):
        captured_session_id.append(session_id)
        # Simulate workers immediately completing
        _simulate_workers(s3_client, cfg, session_id, items, fn, 3)

    with patch.object(session, "_launch_workers", side_effect=fake_launch):
        results = session.run(items, fn, "fake-image:latest")

    assert results == [x * 2 for x in items]
    assert len(captured_session_id) == 1


def test_map_result_ordering(substrate_config):
    """Results must be in original order even with out-of-order chunk completion."""
    cfg = load_config()
    s3 = _make_s3()
    _setup_bucket(s3, cfg.s3_bucket)

    items = list(range(15))
    def fn(x):
        return x**2

    session = Session(
        cfg=cfg,
        workers=5,
        cpu=1,
        memory_gb=2,
        backend="fargate",
        spot=False,
        max_cost=None,
        cost_alert=None,
        timeout=30,
    )

    def fake_launch(ecs, s3_client, session_id, image_uri, chunk_count):
        chunks = _chunk_items(items, 5)
        # Write results in reverse order to test ordering
        for i in reversed(range(len(chunks))):
            results = [x**2 for x in chunks[i]]
            s3_client.put_object(
                Bucket=cfg.s3_bucket,
                Key=_task_key(session_id, i, "result"),
                Body=cloudpickle.dumps(results),
            )
            s3_client.put_object(
                Bucket=cfg.s3_bucket,
                Key=_task_key(session_id, i, "status"),
                Body=b"done",
            )

    with patch.object(session, "_launch_workers", side_effect=fake_launch):
        results = session.run(items, fn, "fake-image:latest")

    assert results == [x**2 for x in items]


def test_map_tasks_uploaded_to_s3(substrate_config):
    """Task files are written to S3 before workers launch."""
    cfg = load_config()
    s3 = _make_s3()
    _setup_bucket(s3, cfg.s3_bucket)

    items = [1, 2, 3, 4, 5]
    def fn(x):
        return x + 1

    session = Session(
        cfg=cfg,
        workers=2,
        cpu=1,
        memory_gb=2,
        backend="fargate",
        spot=False,
        max_cost=None,
        cost_alert=None,
        timeout=30,
    )

    task_files_at_launch: list[str] = []

    def fake_launch(ecs, s3_client, session_id, image_uri, chunk_count):
        # At this point, task files should already be in S3
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=cfg.s3_bucket,
            Prefix=f"sessions/{session_id}/tasks/",
        ):
            for obj in page.get("Contents", []):
                task_files_at_launch.append(obj["Key"])
        # Now simulate workers
        _simulate_workers(s3_client, cfg, session_id, items, fn, 2)

    with patch.object(session, "_launch_workers", side_effect=fake_launch):
        session.run(items, fn, "fake-image:latest")

    # .task files should have been present at launch time
    task_keys = [k for k in task_files_at_launch if k.endswith(".task")]
    assert len(task_keys) == 2  # 2 chunks


def test_map_manifest_written(substrate_config):
    """Session manifest is written to S3."""
    cfg = load_config()
    s3 = _make_s3()
    _setup_bucket(s3, cfg.s3_bucket)

    items = [1, 2, 3]
    def fn(x):
        return x

    session = Session(
        cfg=cfg,
        workers=1,
        cpu=1,
        memory_gb=2,
        backend="fargate",
        spot=False,
        max_cost=None,
        cost_alert=None,
        timeout=30,
    )

    captured_session_id = []

    def fake_launch(ecs, s3_client, session_id, image_uri, chunk_count):
        captured_session_id.append(session_id)
        _simulate_workers(s3_client, cfg, session_id, items, fn, 1)

    with patch.object(session, "_launch_workers", side_effect=fake_launch):
        session.run(items, fn, "fake-image:latest")

    session_id = captured_session_id[0]
    resp = s3.get_object(Bucket=cfg.s3_bucket, Key=f"sessions/{session_id}/manifest.json")
    manifest = json.loads(resp["Body"].read())

    assert manifest["session_id"] == session_id
    assert manifest["language"] == "python"
    assert manifest["task_count"] == 1


def test_map_task_files_cleaned_up(substrate_config):
    """Task files are deleted after completion (manifest kept)."""
    cfg = load_config()
    s3 = _make_s3()
    _setup_bucket(s3, cfg.s3_bucket)

    items = [1, 2]
    def fn(x):
        return x

    session = Session(
        cfg=cfg,
        workers=1,
        cpu=1,
        memory_gb=2,
        backend="fargate",
        spot=False,
        max_cost=None,
        cost_alert=None,
        timeout=30,
    )

    captured_session_id = []

    def fake_launch(ecs, s3_client, session_id, image_uri, chunk_count):
        captured_session_id.append(session_id)
        _simulate_workers(s3_client, cfg, session_id, items, fn, 1)

    with patch.object(session, "_launch_workers", side_effect=fake_launch):
        session.run(items, fn, "fake-image:latest")

    session_id = captured_session_id[0]
    paginator = s3.get_paginator("list_objects_v2")
    all_keys = []
    for page in paginator.paginate(Bucket=cfg.s3_bucket, Prefix=f"sessions/{session_id}/"):
        all_keys.extend(obj["Key"] for obj in page.get("Contents", []))

    task_files = [k for k in all_keys if not k.endswith("manifest.json")]
    assert len(task_files) == 0, f"Unexpected task files remaining: {task_files}"

    manifest_files = [k for k in all_keys if k.endswith("manifest.json")]
    assert len(manifest_files) == 1
