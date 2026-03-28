"""Unit tests for adder/cost.py."""

import pytest

from adder.cost import (
    FARGATE_GB_PER_HOUR,
    FARGATE_VCPU_PER_HOUR,
    estimate_cost,
    estimate_cost_per_hour,
)


def test_fargate_constants():
    assert FARGATE_VCPU_PER_HOUR == pytest.approx(0.04048)
    assert FARGATE_GB_PER_HOUR == pytest.approx(0.004445)


def test_estimate_cost_per_hour_single_worker():
    # 1 worker, 2 vCPU, 4 GB
    rate = estimate_cost_per_hour(cpu=2, memory_gb=4, workers=1)
    expected = 2 * FARGATE_VCPU_PER_HOUR + 4 * FARGATE_GB_PER_HOUR
    assert rate == pytest.approx(expected)


def test_estimate_cost_per_hour_scales_with_workers():
    rate1 = estimate_cost_per_hour(cpu=2, memory_gb=4, workers=1)
    rate10 = estimate_cost_per_hour(cpu=2, memory_gb=4, workers=10)
    assert rate10 == pytest.approx(rate1 * 10)


def test_estimate_cost_zero_hours():
    assert estimate_cost(cpu=2, memory_gb=4, workers=10, hours=0) == 0.0


def test_estimate_cost_one_hour():
    cost = estimate_cost(cpu=2, memory_gb=4, workers=10, hours=1.0)
    assert cost == pytest.approx(estimate_cost_per_hour(cpu=2, memory_gb=4, workers=10))


def test_estimate_cost_fractional_hours():
    cost_full = estimate_cost(cpu=2, memory_gb=4, workers=10, hours=1.0)
    cost_half = estimate_cost(cpu=2, memory_gb=4, workers=10, hours=0.5)
    assert cost_half == pytest.approx(cost_full / 2)


def test_cost_50_workers_reasonable_range():
    """50 workers, 4 vCPU, 8 GB should be in a plausible Fargate cost range."""
    rate = estimate_cost_per_hour(cpu=4, memory_gb=8, workers=50)
    # 50 × (4 × 0.04048 + 8 × 0.004445) ≈ $9.87/hr
    expected = 50 * (4 * FARGATE_VCPU_PER_HOUR + 8 * FARGATE_GB_PER_HOUR)
    assert rate == pytest.approx(expected)
    assert 8.0 <= rate <= 12.0, f"Unexpected cost: ${rate:.2f}/hr"
