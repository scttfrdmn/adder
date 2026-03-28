"""cloudpickle serialization helpers for adder tasks and results."""

from __future__ import annotations

import sys
from typing import Any, Callable

import cloudpickle


def serialize_task(fn: Callable, items: list) -> bytes:
    """Serialize a function and its input data to bytes.

    Uses cloudpickle to handle lambdas, closures, and interactively-defined functions.
    """
    payload = {
        "fn": fn,
        "items": items,
        "python_version": sys.version_info[:3],
    }
    return cloudpickle.dumps(payload)


def deserialize_task(data: bytes) -> tuple[Callable, list]:
    """Deserialize a task payload into (fn, items)."""
    payload = cloudpickle.loads(data)
    return payload["fn"], payload["items"]


def serialize_result(result: Any) -> bytes:
    """Serialize a result list to bytes."""
    return cloudpickle.dumps(result)


def deserialize_result(data: bytes) -> Any:
    """Deserialize a result payload."""
    return cloudpickle.loads(data)
