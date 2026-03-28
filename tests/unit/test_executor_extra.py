"""Additional tests for executor submit/map paths."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from adder.executor import CloudExecutor


def _setup_cfg(tmp_path, monkeypatch):
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
    return cfg


def test_executor_map_delegates_to_session(tmp_path, monkeypatch):
    """CloudExecutor.map runs items through Session."""
    _setup_cfg(tmp_path, monkeypatch)

    exc = CloudExecutor(workers=2, cpu=1, memory="2GB")

    with patch("adder.env.ensure_image", return_value="fake-uri"), \
         patch("adder.session.Session") as MockSession:
        mock_sess = MagicMock()
        mock_sess.run.return_value = [2, 4, 6]
        MockSession.return_value = mock_sess

        results = list(exc.map(lambda x: x * 2, [1, 2, 3]))

    assert results == [2, 4, 6]


def test_executor_map_multiple_iterables(tmp_path, monkeypatch):
    """CloudExecutor.map with multiple iterables zips them."""
    _setup_cfg(tmp_path, monkeypatch)

    exc = CloudExecutor(workers=2, cpu=1, memory="2GB")

    with patch("adder.env.ensure_image", return_value="fake-uri"), \
         patch("adder.session.Session") as MockSession:
        mock_sess = MagicMock()
        mock_sess.run.return_value = [3, 7]
        MockSession.return_value = mock_sess

        results = list(exc.map(lambda a, b: a + b, [1, 3], [2, 4]))

    assert results == [3, 7]


def test_executor_submit_returns_future(tmp_path, monkeypatch):
    """CloudExecutor.submit returns a Future that resolves correctly."""
    import concurrent.futures
    _setup_cfg(tmp_path, monkeypatch)

    exc = CloudExecutor(workers=1, cpu=1, memory="2GB")

    with patch("adder.env.ensure_image", return_value="fake-uri"), \
         patch("adder.session.Session") as MockSession:
        mock_sess = MagicMock()
        mock_sess.run.return_value = [42]
        MockSession.return_value = mock_sess

        future = exc.submit(lambda x: x * 2, 21)
        result = future.result(timeout=5)

    assert result == 42


def test_executor_region_override(tmp_path, monkeypatch):
    """CloudExecutor uses provided region."""
    _setup_cfg(tmp_path, monkeypatch)
    exc = CloudExecutor(workers=5, region="ap-southeast-1")
    cfg = exc._get_cfg()
    assert cfg.region == "ap-southeast-1"


def test_executor_map_raises_when_shutdown(tmp_path, monkeypatch):
    exc = CloudExecutor(workers=5)
    exc.shutdown()
    with pytest.raises(RuntimeError, match="shut down"):
        list(exc.map(lambda x: x, [1, 2, 3]))
