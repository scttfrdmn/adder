"""Unit tests for adder/env.py."""

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from adder.env import EXCLUDE_PACKAGES, capture_environment


def test_capture_environment_returns_tuple():
    requirements, env_hash = capture_environment()
    assert isinstance(requirements, str)
    assert isinstance(env_hash, str)
    assert len(env_hash) == 64  # SHA256 hex digest


def test_capture_environment_hash_is_sha256():
    requirements, env_hash = capture_environment()
    expected = hashlib.sha256(requirements.encode()).hexdigest()
    assert env_hash == expected


def test_capture_environment_sorted():
    requirements, _ = capture_environment()
    if not requirements:
        pytest.skip("No packages installed")
    lines = requirements.split("\n")
    assert lines == sorted(lines)


def test_capture_environment_format():
    """Each line should be 'package==version'."""
    requirements, _ = capture_environment()
    if not requirements:
        pytest.skip("No packages installed")
    for line in requirements.split("\n"):
        assert "==" in line, f"Expected 'pkg==ver' format, got: {line!r}"


def test_capture_environment_excludes_pip():
    requirements, _ = capture_environment()
    lines = [line.split("==")[0].lower() for line in requirements.split("\n") if line]
    for excluded in ("pip", "setuptools", "wheel"):
        assert excluded not in lines, f"{excluded!r} should be excluded"


def test_capture_environment_stable():
    """Same environment produces same hash on repeated calls."""
    _, hash1 = capture_environment()
    _, hash2 = capture_environment()
    assert hash1 == hash2


def test_build_image_calls_burst_core():
    """build_image shells out to burst-core with correct arguments."""
    from adder.env import build_image

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="123.dkr.ecr.us-east-1.amazonaws.com/burst-workers-python:abc123\n")
        uri = build_image("abc123", "/tmp/Dockerfile")

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "burst-core" in cmd
    assert "image" in cmd
    assert "build" in cmd
    assert "--env-hash" in cmd
    assert "abc123" in cmd
    assert uri == "123.dkr.ecr.us-east-1.amazonaws.com/burst-workers-python:abc123"
