"""Unit tests for adder/cli.py using click's CliRunner."""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from adder.cli import main
from adder.config import Config


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    cfg = Config(
        region="us-east-1",
        s3_bucket="burst-us-east-1",
        ecs_cluster="burst-cluster",
        ecr_base_uri="123.dkr.ecr.us-east-1.amazonaws.com",
        execution_role_arn="arn:aws:iam::123:role/exec",
        task_role_arn="arn:aws:iam::123:role/task",
    )
    config_file = tmp_path / "config.json"
    import dataclasses

    config_file.write_text(json.dumps(dataclasses.asdict(cfg)))
    monkeypatch.setenv("BURST_CONFIG_PATH", str(config_file))
    return cfg, config_file


# ── version ───────────────────────────────────────────────────────────────────


def test_version_shows_adder_version(runner):
    with (
        patch("shutil.which", return_value=None),
        patch("subprocess.run", side_effect=FileNotFoundError()),
    ):
        result = runner.invoke(main, ["version"])
    assert "0.1.0" in result.output
    assert result.exit_code == 0


def test_version_with_burst_core(runner):
    with (
        patch("shutil.which", return_value="/usr/local/bin/burst-core"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="0.4.0\n")
        result = runner.invoke(main, ["version"])
    assert "0.1.0" in result.output
    assert result.exit_code == 0


# ── config show ───────────────────────────────────────────────────────────────


def test_config_show(runner, mock_config):
    result = runner.invoke(main, ["config", "show"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["region"] == "us-east-1"
    assert data["s3_bucket"] == "burst-us-east-1"


# ── config set ────────────────────────────────────────────────────────────────


def test_config_set_string(runner, mock_config):
    cfg, config_file = mock_config
    result = runner.invoke(main, ["config", "set", "region", "eu-west-1"])
    assert result.exit_code == 0
    data = json.loads(config_file.read_text())
    assert data["region"] == "eu-west-1"


def test_config_set_int(runner, mock_config):
    cfg, config_file = mock_config
    result = runner.invoke(main, ["config", "set", "default_workers", "25"])
    assert result.exit_code == 0
    data = json.loads(config_file.read_text())
    assert data["default_workers"] == 25


def test_config_set_bool(runner, mock_config):
    cfg, config_file = mock_config
    result = runner.invoke(main, ["config", "set", "spot", "true"])
    assert result.exit_code == 0
    data = json.loads(config_file.read_text())
    assert data["spot"] is True


def test_config_set_unknown_key(runner, mock_config):
    result = runner.invoke(main, ["config", "set", "nonexistent_key", "value"])
    assert result.exit_code != 0


# ── setup / status ────────────────────────────────────────────────────────────


def test_setup_delegates_to_burst_core(runner):
    with (
        patch("shutil.which", return_value="/usr/bin/burst-core"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        runner.invoke(main, ["setup"])
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "burst-core" in cmd[0]
    assert "setup" in cmd


def test_setup_fails_without_burst_core(runner):
    with patch("shutil.which", return_value=None):
        home_path_mock = MagicMock()
        home_path_mock.exists.return_value = False
        with patch("adder.cli._burst_core_home_path", return_value=home_path_mock):
            result = runner.invoke(main, ["setup"])
    assert result.exit_code != 0
    assert "burst-core" in result.output


def test_status_delegates_to_burst_core(runner):
    with (
        patch("shutil.which", return_value="/usr/bin/burst-core"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        runner.invoke(main, ["status"])
    cmd = mock_run.call_args[0][0]
    assert "status" in cmd


# ── session commands ──────────────────────────────────────────────────────────


def test_session_list(runner):
    with (
        patch("shutil.which", return_value="/usr/bin/burst-core"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        runner.invoke(main, ["session", "list"])
    cmd = mock_run.call_args[0][0]
    assert "session" in cmd
    assert "list" in cmd


def test_session_status(runner):
    with (
        patch("shutil.which", return_value="/usr/bin/burst-core"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        runner.invoke(main, ["session", "status", "py-20260315-abc123"])
    cmd = mock_run.call_args[0][0]
    assert "py-20260315-abc123" in cmd


def test_session_cleanup(runner):
    with (
        patch("shutil.which", return_value="/usr/bin/burst-core"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        runner.invoke(main, ["session", "cleanup", "py-20260315-abc123"])
    cmd = mock_run.call_args[0][0]
    assert "cleanup" in cmd


def test_help(runner):
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "adder" in result.output.lower()
