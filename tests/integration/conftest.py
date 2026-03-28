"""Integration test configuration — applies substrate fixtures to all integration tests."""

import pytest


@pytest.fixture(autouse=True)
def _substrate_env(reset_substrate):
    """Auto-apply substrate env setup for all integration tests."""
    yield
