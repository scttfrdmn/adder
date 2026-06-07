"""Test fixtures for adder tests.

Unit tests use moto (no AWS, no subprocess).
Integration tests:
  - Substrate (default): BURST_INTEGRATION_TEST=1
  - Real AWS:            BURST_INTEGRATION_TEST=1 BURST_USE_REAL_AWS=1
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time

import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _using_real_aws() -> bool:
    return bool(os.environ.get("BURST_USE_REAL_AWS"))


@pytest.fixture(scope="session")
def substrate_server():
    """Start a substrate server, or yield None when running against real AWS.

    Requires BURST_INTEGRATION_TEST=1. Add BURST_USE_REAL_AWS=1 to use real AWS.
    """
    if not os.environ.get("BURST_INTEGRATION_TEST"):
        pytest.skip("Set BURST_INTEGRATION_TEST=1 to run integration tests")

    if _using_real_aws():
        yield None
        return

    port = _free_port()
    proc = subprocess.Popen(
        ["substrate", "server", "--address", f":{port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    import requests

    deadline = time.monotonic() + 60.0
    url = f"http://localhost:{port}"
    while time.monotonic() < deadline:
        try:
            requests.get(f"{url}/health", timeout=0.5)
            break
        except Exception:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError(f"substrate server did not start within 60s on port {port}")

    yield url

    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def reset_substrate(substrate_server, monkeypatch):
    """Point boto3 at substrate (or leave real AWS env intact) and reset state."""
    import requests

    if substrate_server is not None:
        monkeypatch.setenv("AWS_ENDPOINT_URL", substrate_server)
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    yield

    if substrate_server is not None:
        try:
            requests.post(f"{substrate_server}/v1/state/reset", timeout=5)
        except Exception:
            pass


@pytest.fixture
def substrate_config(tmp_path, monkeypatch, reset_substrate):
    """Write a config.json for the current target (substrate or real AWS)."""
    if _using_real_aws():
        from adder.config import load
        cfg = load()
        return {
            "region": cfg.region,
            "s3_bucket": cfg.s3_bucket,
            "ecs_cluster": cfg.ecs_cluster,
            "ecr_base_uri": cfg.ecr_base_uri,
            "execution_role_arn": cfg.execution_role_arn,
            "task_role_arn": cfg.task_role_arn,
            "default_workers": cfg.default_workers,
            "default_cpu": cfg.default_cpu,
            "default_memory_gb": cfg.default_memory_gb,
        }

    cfg_data = {
        "region": "us-east-1",
        "s3_bucket": "burst-us-east-1",
        "ecs_cluster": "burst-cluster",
        "ecr_base_uri": "123456789012.dkr.ecr.us-east-1.amazonaws.com",
        "execution_role_arn": "arn:aws:iam::123456789012:role/burst-execution-role",
        "task_role_arn": "arn:aws:iam::123456789012:role/burst-task-role",
        "default_workers": 3,
        "default_cpu": 1,
        "default_memory_gb": 2,
    }
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(cfg_data))
    monkeypatch.setenv("BURST_CONFIG_PATH", str(config_file))
    return cfg_data
