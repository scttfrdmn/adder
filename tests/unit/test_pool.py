"""Unit tests for adder/pool.py."""

from unittest.mock import MagicMock, patch


from adder.pool import Pool


def test_pool_defaults():
    pool = Pool()
    assert pool._workers == 10
    assert pool._cpu == 2
    assert pool._memory == "4GB"
    assert pool._backend == "fargate"
    assert pool._spot is False


def test_pool_custom_options():
    pool = Pool(workers=50, cpu=4, memory="8GB", spot=True, region="us-west-2")
    assert pool._workers == 50
    assert pool._cpu == 4
    assert pool._memory == "8GB"
    assert pool._spot is True
    assert pool._region == "us-west-2"


def test_pool_shutdown_clears_state():
    pool = Pool(workers=10)
    pool._cfg = MagicMock()
    pool._image_uri = "some-uri"
    pool.shutdown()
    assert pool._cfg is None
    assert pool._image_uri is None


def test_pool_shutdown_idempotent():
    pool = Pool()
    pool.shutdown()
    pool.shutdown()  # Should not raise


def test_pool_map_calls_session(monkeypatch, tmp_path):
    """Pool.map delegates to Session.run."""
    import json
    from adder.config import Config
    import dataclasses

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

    pool = Pool(workers=3, cpu=1, memory="2GB")

    with (
        patch("adder.env.ensure_image", return_value="fake-uri"),
        patch("adder.session.Session") as MockSession,
    ):
        mock_sess = MagicMock()
        mock_sess.run.return_value = [2, 4, 6]
        MockSession.return_value = mock_sess

        results = pool.map([1, 2, 3], lambda x: x * 2)

    assert results == [2, 4, 6]
    mock_sess.run.assert_called_once()
