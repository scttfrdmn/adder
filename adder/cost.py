"""Cost estimation and display for adder — matches ARCHITECTURE.md format exactly."""

from __future__ import annotations

from rich.console import Console

FARGATE_VCPU_PER_HOUR = 0.04048
FARGATE_GB_PER_HOUR = 0.004445

_console = Console(stderr=True)


def estimate_cost_per_hour(cpu: int, memory_gb: int, workers: int) -> float:
    """Estimate cost per hour for a given worker configuration."""
    return workers * (cpu * FARGATE_VCPU_PER_HOUR + memory_gb * FARGATE_GB_PER_HOUR)


def estimate_cost(cpu: int, memory_gb: int, workers: int, hours: float) -> float:
    """Estimate total cost for a given duration."""
    return estimate_cost_per_hour(cpu, memory_gb, workers) * hours


def print_start(workers: int) -> None:
    _console.print(f":rocket: Starting burst cluster with {workers} workers")


def print_cost_estimate(rate: float) -> None:
    _console.print(f":money_bag: Estimated cost: ~${rate:.2f}/hour")


def print_processing(total: int, workers: int) -> None:
    _console.print(f":bar_chart: Processing {total} items with {workers} workers")


def print_chunks(chunks: int, avg: int) -> None:
    _console.print(f":package: Created {chunks} chunks (avg {avg} items per chunk)")


def print_submitted(n: int) -> None:
    _console.print(f":rocket: Submitting tasks...")
    _console.print(f":white_check_mark: Submitted {n} tasks")


def print_progress(done: int, total: int, elapsed: str) -> None:
    _console.print(f":hourglass_flowing_sand: Progress: {done}/{total} tasks ({elapsed} elapsed)")


def print_completed(elapsed: str) -> None:
    _console.print(f":white_check_mark: Completed in {elapsed}")


def print_actual_cost(cost: float) -> None:
    _console.print(f":money_bag: Actual cost: ${cost:.2f}")


def print_quota_warning(
    req: int, req_vcpu: int, actual: int, actual_vcpu: int
) -> None:
    _console.print(
        f":warning: Requested {req} workers ({req_vcpu} vCPUs) but quota allows "
        f"{actual} workers ({actual_vcpu} vCPUs)"
    )
    _console.print(
        f":warning: Using {actual} workers instead. Request quota increase: "
        "https://console.aws.amazon.com/servicequotas/"
    )


def print_cost_alert(threshold: float) -> None:
    _console.print(
        f":warning: Estimated cost exceeds alert threshold of ${threshold:.2f}"
    )
