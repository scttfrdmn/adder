"""Unit tests for adder/config.py."""

import json
import os
import stat
from pathlib import Path

import pytest

from adder.config import Config, load, save


def test_default_config():
    cfg = Config()
    assert cfg.region == "us-east-1"
    assert cfg.ecs_cluster == "burst-cluster"
    assert cfg.backend == "fargate"
    assert cfg.spot is False
    assert cfg.default_workers == 10


def test_save_and_load(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    monkeypatch.setenv("BURST_CONFIG_PATH", str(config_file))

    cfg = Config(
        region="us-west-2",
        s3_bucket="burst-us-west-2",
        ecs_cluster="burst-cluster",
        ecr_base_uri="123456789.dkr.ecr.us-west-2.amazonaws.com",
        execution_role_arn="arn:aws:iam::123456789:role/burst-execution-role",
        task_role_arn="arn:aws:iam::123456789:role/burst-task-role",
    )
    save(cfg)

    assert config_file.exists()

    loaded = load()
    assert loaded.region == "us-west-2"
    assert loaded.s3_bucket == "burst-us-west-2"
    assert loaded.ecr_base_uri == "123456789.dkr.ecr.us-west-2.amazonaws.com"


def test_save_permissions(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    monkeypatch.setenv("BURST_CONFIG_PATH", str(config_file))

    save(Config())
    mode = stat.S_IMODE(os.stat(config_file).st_mode)
    assert mode == 0o600


def test_load_missing_file(tmp_path, monkeypatch):
    """Load returns default Config when file doesn't exist."""
    monkeypatch.setenv("BURST_CONFIG_PATH", str(tmp_path / "nonexistent.json"))
    cfg = load()
    assert cfg.region == "us-east-1"


def test_load_ignores_unknown_keys(tmp_path, monkeypatch):
    """Load gracefully ignores keys not in Config."""
    config_file = tmp_path / "config.json"
    monkeypatch.setenv("BURST_CONFIG_PATH", str(config_file))

    data = {"region": "eu-west-1", "unknown_future_key": "some_value", "backend": "fargate"}
    config_file.write_text(json.dumps(data))

    cfg = load()
    assert cfg.region == "eu-west-1"


def test_validate_raises_when_fields_missing():
    from adder.errors import BurstSetupError
    cfg = Config()  # no s3_bucket, etc.
    with pytest.raises(BurstSetupError) as exc_info:
        cfg.validate()
    assert "s3_bucket" in str(exc_info.value)


def test_validate_passes_when_all_fields_set():
    cfg = Config(
        s3_bucket="burst-us-east-1",
        ecr_base_uri="123.dkr.ecr.us-east-1.amazonaws.com",
        execution_role_arn="arn:aws:iam::123:role/exec",
        task_role_arn="arn:aws:iam::123:role/task",
    )
    cfg.validate()  # Should not raise
