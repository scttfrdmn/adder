"""Unit tests for adder/executor.py."""

import pytest

from adder.executor import CloudExecutor, _parse_memory_gb


# ── _parse_memory_gb ──────────────────────────────────────────────────────────


def test_parse_memory_gb_gb():
    assert _parse_memory_gb("4GB") == 4
    assert _parse_memory_gb("16GB") == 16


def test_parse_memory_gb_mb():
    assert _parse_memory_gb("1024MB") == 1
    assert _parse_memory_gb("512MB") == 1  # rounds up to 1


def test_parse_memory_gb_no_unit():
    assert _parse_memory_gb("8") == 8


def test_parse_memory_gb_case_insensitive():
    assert _parse_memory_gb("4gb") == 4
    assert _parse_memory_gb("4Gb") == 4


# ── CloudExecutor interface ───────────────────────────────────────────────────


def test_executor_context_manager():
    """CloudExecutor works as a context manager."""
    with CloudExecutor(workers=5) as exc:
        assert isinstance(exc, CloudExecutor)


def test_executor_shutdown():
    exc = CloudExecutor(workers=5)
    exc.shutdown()
    with pytest.raises(RuntimeError, match="shut down"):
        exc.submit(lambda: None)


def test_executor_shutdown_idempotent():
    exc = CloudExecutor(workers=5)
    exc.shutdown()
    exc.shutdown()  # Should not raise


def test_executor_defaults():
    exc = CloudExecutor()
    assert exc._workers == 10
    assert exc._cpu == 2
    assert exc._memory_gb == 4
    assert exc._backend == "fargate"
    assert exc._spot is False
    assert exc._max_cost is None
