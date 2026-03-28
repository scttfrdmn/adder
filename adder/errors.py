"""Exception hierarchy for adder."""

from __future__ import annotations


class BurstError(Exception):
    """Base class for all adder errors."""


class BurstPartialError(BurstError):
    """Raised when some tasks fail and some succeed."""

    def __init__(self, results: list, errors: list) -> None:
        self.results = results
        self.errors = errors
        self.failed_count = sum(1 for e in errors if e is not None)
        self.success_count = sum(1 for r in results if r is not None)
        super().__init__(
            f"{self.failed_count} of {self.failed_count + self.success_count} tasks failed"
        )


class BurstQuotaError(BurstError):
    """Raised when AWS quota prevents launching the requested number of workers."""

    def __init__(self, requested: int, actual: int, quota_name: str, quota_value: float) -> None:
        self.requested_workers = requested
        self.actual_workers = actual
        self.quota_name = quota_name
        self.quota_value = quota_value
        super().__init__(
            f"Requested {requested} workers but quota {quota_name!r} allows {actual} "
            f"(quota value: {quota_value})"
        )


class BurstCostLimitError(BurstError):
    """Raised when the job hits the configured cost ceiling."""

    def __init__(self, limit: float, estimated: float, partial_results: list) -> None:
        self.limit = limit
        self.estimated_cost = estimated
        self.partial_results = partial_results
        super().__init__(
            f"Cost limit ${limit:.2f} exceeded (estimated ${estimated:.2f})"
        )


class BurstTimeoutError(BurstError):
    """Raised when the job exceeds the configured timeout."""

    def __init__(self, session_id: str, timeout_seconds: int, status: object) -> None:
        self.session_id = session_id
        self.timeout_seconds = timeout_seconds
        self.status = status
        super().__init__(
            f"Session {session_id} timed out after {timeout_seconds}s"
        )


class BurstSetupError(BurstError):
    """Raised when AWS resource provisioning fails."""

    def __init__(self, step: str, cause: str, remediation: str) -> None:
        self.step = step
        self.cause = cause
        self.remediation = remediation
        super().__init__(
            f"Setup failed at step {step!r}: {cause}. Remediation: {remediation}"
        )
