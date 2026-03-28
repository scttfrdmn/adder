"""adder.map() — the primary user-facing API for cloud bursting."""

from __future__ import annotations

from typing import Callable, Iterable, Literal, TypeVar

from .executor import CloudExecutor

T = TypeVar("T")
U = TypeVar("U")


def map(
    items: Iterable[T],
    fn: Callable[[T], U],
    *,
    workers: int = 10,
    cpu: int = 2,
    memory: str = "4GB",
    backend: Literal["fargate", "ec2"] = "fargate",
    spot: bool = False,
    max_cost: float | None = None,
    cost_alert: float | None = None,
    timeout: int | None = None,
    region: str | None = None,
) -> list[U]:
    """Distribute items across AWS ECS workers and collect results.

    Synchronous — blocks until all tasks complete or an error occurs.
    Returns results in the same order as the input items.

    Args:
        items: Input items to process.
        fn: Function to apply to each item.
        workers: Number of parallel ECS workers.
        cpu: vCPUs per worker (0.25, 0.5, 1, 2, 4, 8, 16).
        memory: Memory per worker (e.g. "4GB", "512MB").
        backend: "fargate" (serverless) or "ec2".
        spot: Use Fargate Spot for ~70% cost savings (with interruption risk).
        max_cost: Cancel job if estimated cost exceeds this USD amount.
        cost_alert: Print warning if estimated cost exceeds this USD amount.
        timeout: Maximum seconds to wait for completion.
        region: AWS region (defaults to ~/.burst/config.json value).

    Returns:
        List of results in the same order as items.

    Raises:
        BurstPartialError: If some tasks fail.
        BurstCostLimitError: If max_cost is exceeded.
        BurstQuotaError: If workers cannot be provisioned at requested count.
        BurstTimeoutError: If timeout is exceeded.
        BurstSetupError: If AWS configuration is missing (run `adder setup`).
    """
    with CloudExecutor(
        workers=workers,
        cpu=cpu,
        memory=memory,
        backend=backend,
        spot=spot,
        max_cost=max_cost,
        cost_alert=cost_alert,
        region=region,
    ) as executor:
        return list(executor.map(fn, items, timeout=float(timeout) if timeout else None))
