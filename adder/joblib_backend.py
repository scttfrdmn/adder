"""joblib parallel backend for adder — enables transparent cloud bursting for scikit-learn."""

from __future__ import annotations

import concurrent.futures
from typing import Any, Callable

from joblib.parallel import ParallelBackendBase


class AdderBackend(ParallelBackendBase):
    """joblib parallel backend that runs jobs on AWS ECS workers via adder.

    Registration (done automatically on ``import adder``)::

        import joblib
        from adder.joblib_backend import AdderBackend
        joblib.register_parallel_backend('adder', AdderBackend)

    Usage::

        from joblib import parallel_backend
        import adder  # registers backend

        with parallel_backend('adder', workers=50, cpu=4):
            grid_search = GridSearchCV(model, param_grid, n_jobs=-1)
            grid_search.fit(X, y)
    """

    def __init__(
        self,
        nesting_level: int | None = None,
        inner_max_num_threads: int | None = None,
        workers: int = 10,
        cpu: int = 2,
        memory: str = "4GB",
        backend: str = "fargate",
        spot: bool = False,
        max_cost: float | None = None,
        region: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(nesting_level=nesting_level, inner_max_num_threads=inner_max_num_threads)
        self._workers = workers
        self._cpu = cpu
        self._memory = memory
        self._backend_type = backend
        self._spot = spot
        self._max_cost = max_cost
        self._region = region
        self._executor: Any = None

    def configure(
        self, n_jobs: int = 1, parallel: Any = None, **backend_args: Any
    ) -> tuple[int, Any]:
        """Configure the backend. Called by joblib before dispatching work."""
        n = self.effective_n_jobs(n_jobs)
        self._executor = self._make_executor()
        return n, self

    def effective_n_jobs(self, n_jobs: int = 1) -> int:
        """Return the effective number of jobs."""
        if n_jobs == -1:
            return self._workers
        if n_jobs < 0:
            return max(1, self._workers + 1 + n_jobs)
        return max(1, n_jobs)

    def apply_async(self, func: Callable, callback: Callable | None = None) -> Any:
        """Submit a batch of calls as a cloud task.

        ``func`` is typically a ``BatchedCalls`` instance from joblib.
        """
        executor = self._get_executor()

        future = executor.submit(func)

        if callback is not None:
            future.add_done_callback(lambda f: callback(f.result()) if not f.exception() else None)

        return _FutureWrapper(future)

    def abort_everything(self, ensure_ready: bool = True) -> None:
        """Abort all pending tasks."""
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None

    def _make_executor(self) -> Any:
        from .executor import CloudExecutor

        return CloudExecutor(
            workers=self._workers,
            cpu=self._cpu,
            memory=self._memory,
            backend=self._backend_type,
            spot=self._spot,
            max_cost=self._max_cost,
            region=self._region,
        )

    def _get_executor(self) -> Any:
        if self._executor is None:
            self._executor = self._make_executor()
        return self._executor


class _FutureWrapper:
    """Wraps a concurrent.futures.Future to match joblib's expected interface."""

    def __init__(self, future: concurrent.futures.Future) -> None:
        self._future = future

    def get(self) -> Any:
        return self._future.result()
