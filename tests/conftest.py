"""Test fixtures for adder tests.

Unit tests use moto (no AWS, no subprocess).
Integration tests use substrate — set BURST_INTEGRATION_TEST=1 to enable.
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


@pytest.fixture(scope="session")
def substrate_server():
    """Start a substrate server for the test session.

    Requires BURST_INTEGRATION_TEST=1 to activate.
    """
    if not os.environ.get("BURST_INTEGRATION_TEST"):
        pytest.skip("Set BURST_INTEGRATION_TEST=1 to run integration tests")

    port = _free_port()
    proc = subprocess.Popen(
        ["substrate", "server", "--address", f":{port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for server to be ready (60s for CI — substrate may need to compile)
    deadline = time.monotonic() + 60.0
    url = f"http://localhost:{port}"
    import requests

    while time.monotonic() < deadline:
        try:
            requests.get(f"{url}/health", timeout=0.5)
            break
        except Exception:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError(f"substrate server did not start within 10s on port {port}")

    yield url

    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def reset_substrate(substrate_server, monkeypatch):
    """Reset substrate state between tests and point boto3 at substrate.

    Use this fixture explicitly in integration tests.
    """
    import requests

    # Point all boto3 calls at substrate via standard env var
    monkeypatch.setenv("AWS_ENDPOINT_URL", substrate_server)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    yield

    # Reset substrate state after each test
    try:
        requests.post(f"{substrate_server}/v1/state/reset", timeout=5)
    except Exception:
        pass


@pytest.fixture
def substrate_config(tmp_path, monkeypatch, reset_substrate):
    """Write a config.json pointing at substrate and return it."""
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
