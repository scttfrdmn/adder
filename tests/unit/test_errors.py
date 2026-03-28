"""Unit tests for adder/errors.py."""

import pytest

from adder.errors import (
    BurstCostLimitError,
    BurstError,
    BurstPartialError,
    BurstQuotaError,
    BurstSetupError,
    BurstTimeoutError,
)


def test_burst_partial_error_counts():
    results = [1, None, 3, None, 5]
    errors = [None, "err1", None, "err2", None]
    exc = BurstPartialError(results=results, errors=errors)
    assert exc.failed_count == 2
    assert exc.success_count == 3
    assert exc.results == results
    assert exc.errors == errors


def test_burst_partial_error_all_fail():
    results = [None, None]
    errors = ["e1", "e2"]
    exc = BurstPartialError(results=results, errors=errors)
    assert exc.failed_count == 2
    assert exc.success_count == 0


def test_burst_partial_error_all_succeed():
    results = [1, 2, 3]
    errors = [None, None, None]
    exc = BurstPartialError(results=results, errors=errors)
    assert exc.failed_count == 0
    assert exc.success_count == 3


def test_burst_partial_error_is_burst_error():
    exc = BurstPartialError(results=[], errors=[])
    assert isinstance(exc, BurstError)
    assert isinstance(exc, Exception)


def test_burst_quota_error_fields():
    exc = BurstQuotaError(requested=100, actual=50, quota_name="L-3032A538", quota_value=128.0)
    assert exc.requested_workers == 100
    assert exc.actual_workers == 50
    assert exc.quota_name == "L-3032A538"
    assert exc.quota_value == 128.0
    assert isinstance(exc, BurstError)


def test_burst_cost_limit_error_fields():
    exc = BurstCostLimitError(limit=10.0, estimated=15.5, partial_results=[1, 2])
    assert exc.limit == 10.0
    assert exc.estimated_cost == 15.5
    assert exc.partial_results == [1, 2]
    assert isinstance(exc, BurstError)


def test_burst_timeout_error_fields():
    exc = BurstTimeoutError(session_id="py-20260315-abc123", timeout_seconds=300, status=None)
    assert exc.session_id == "py-20260315-abc123"
    assert exc.timeout_seconds == 300
    assert exc.status is None
    assert isinstance(exc, BurstError)


def test_burst_setup_error_fields():
    exc = BurstSetupError(step="s3", cause="bucket exists", remediation="run setup")
    assert exc.step == "s3"
    assert exc.cause == "bucket exists"
    assert exc.remediation == "run setup"
    assert isinstance(exc, BurstError)


def test_error_str_representations():
    """All errors should have human-readable str()."""
    e1 = BurstPartialError([None], ["oops"])
    assert "1" in str(e1)

    e2 = BurstQuotaError(requested=50, actual=25, quota_name="test", quota_value=50.0)
    assert "50" in str(e2)

    e3 = BurstCostLimitError(limit=5.0, estimated=10.0, partial_results=[])
    assert "5.00" in str(e3)

    e4 = BurstTimeoutError(session_id="abc", timeout_seconds=60, status=None)
    assert "60" in str(e4)

    e5 = BurstSetupError(step="iam", cause="denied", remediation="check perms")
    assert "iam" in str(e5)
