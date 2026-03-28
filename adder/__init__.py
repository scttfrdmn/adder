"""adder — Cloud bursting for Python.

Drop-in replacement for ProcessPoolExecutor with transparent AWS ECS bursting.

Quick start::

    import adder

    results = adder.map(items, my_function, workers=50)

Or use the concurrent.futures interface::

    with adder.CloudExecutor(workers=50) as executor:
        results = list(executor.map(my_function, items))

Or as a joblib backend for scikit-learn::

    from joblib import parallel_backend
    import adder  # registers 'adder' backend

    with parallel_backend('adder', workers=50):
        grid_search.fit(X, y)
"""

from __future__ import annotations

__version__ = "0.1.0"

from .map import map
from .executor import CloudExecutor
from .pool import Pool
from .errors import (
    BurstError,
    BurstPartialError,
    BurstQuotaError,
    BurstCostLimitError,
    BurstTimeoutError,
    BurstSetupError,
)
from .session import DetachedSession, attach as _attach_impl

import joblib
from .joblib_backend import AdderBackend

joblib.register_parallel_backend("adder", AdderBackend)


def session(
    workers: int = 10,
    cpu: int = 2,
    memory: str = "4GB",
    backend: str = "fargate",
    spot: bool = False,
    region: str | None = None,
    detached: bool = False,
) -> DetachedSession:
    """Create a DetachedSession.

    Returns a DetachedSession that can outlive the calling process.

    Usage::

        session = adder.session(workers=50, detached=True)
        session_id = session.submit(items, fn)
        # Process can exit — job continues in AWS

        # Later, reattach:
        session = adder.attach(session_id)
        results = session.collect()
    """
    from .config import load as load_config

    cfg = load_config()
    if region:
        cfg.region = region
    return DetachedSession(session_id="", cfg=cfg)


def attach(session_id: str) -> DetachedSession:
    """Reattach to an existing detached session.

    Args:
        session_id: The session ID returned by DetachedSession.submit().

    Returns:
        A DetachedSession connected to the existing session.
    """
    return _attach_impl(session_id)


__all__ = [
    "map",
    "CloudExecutor",
    "Pool",
    "session",
    "attach",
    "DetachedSession",
    "BurstError",
    "BurstPartialError",
    "BurstQuotaError",
    "BurstCostLimitError",
    "BurstTimeoutError",
    "BurstSetupError",
    "__version__",
]
