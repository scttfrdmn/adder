"""CloudExecutor — concurrent.futures.Executor interface for cloud bursting."""

from __future__ import annotations

import concurrent.futures
import threading
from typing import Any, Callable, Iterable, Iterator, TypeVar

from .config import Config, load as load_config

T = TypeVar("T")
U = TypeVar("U")


class CloudExecutor(concurrent.futures.Executor):
    """A concurrent.futures.Executor that runs tasks on AWS ECS workers.

    Drop-in replacement for ProcessPoolExecutor.

    Usage::

        with CloudExecutor(workers=50) as executor:
            results = list(executor.map(fn, items))
    """

    def __init__(
        self,
        workers: int = 10,
        cpu: int = 2,
        memory: str = "4GB",
        backend: str = "fargate",
        spot: bool = False,
        max_cost: float | None = None,
        cost_alert: float | None = None,
        region: str | None = None,
        arch: str = "amd64",
    ) -> None:
        self._workers = workers
        self._cpu = cpu
        self._memory_gb = _parse_memory_gb(memory)
        self._backend = backend
        self._spot = spot
        self._max_cost = max_cost
        self._cost_alert = cost_alert
        self._region = region
        self._arch = arch
        self._cfg: Config | None = None
        self._shutdown = False
        self._lock = threading.Lock()

    def _get_cfg(self) -> Config:
        if self._cfg is None:
            self._cfg = load_config()
            if self._region:
                self._cfg.region = self._region
        return self._cfg

    def submit(
        self,
        fn: Callable[..., T],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> concurrent.futures.Future[T]:
        """Submit a single function call as a cloud task.

        The call is dispatched as a single-item batch job.
        Returns a Future that resolves when the task completes.
        """
        if self._shutdown:
            raise RuntimeError("CloudExecutor has been shut down")

        future: concurrent.futures.Future[T] = concurrent.futures.Future()

        def _run() -> None:
            try:
                results = self._run_batch([args], lambda a: fn(*a, **kwargs))
                future.set_result(results[0])
            except Exception as e:
                future.set_exception(e)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return future

    def map(
        self,
        fn: Callable[[T], U],
        *iterables: Iterable[T],
        timeout: float | None = None,
        chunksize: int = 1,
    ) -> Iterator[U]:
        """Map fn over items using cloud workers.

        Returns results in the same order as input items.
        """
        if self._shutdown:
            raise RuntimeError("CloudExecutor has been shut down")

        # Zip multiple iterables into tuples if needed
        if len(iterables) == 1:
            items = list(iterables[0])
            actual_fn = fn
        else:
            items = list(zip(*iterables))
            def actual_fn(args):
                return fn(*args)  # type: ignore[assignment]

        results = self._run_batch(items, actual_fn, timeout=timeout)
        return iter(results)

    def _run_batch(
        self,
        items: list,
        fn: Callable,
        timeout: float | None = None,
    ) -> list:
        """Run a batch of items through the cloud workers."""
        from .env import ensure_image
        from .session import Session

        cfg = self._get_cfg()
        cfg.validate()

        image_uri = ensure_image(cfg)

        sess = Session(
            cfg=cfg,
            workers=self._workers,
            cpu=self._cpu,
            memory_gb=self._memory_gb,
            backend=self._backend,
            spot=self._spot,
            max_cost=self._max_cost,
            cost_alert=self._cost_alert,
            timeout=int(timeout) if timeout else None,
            arch=self._arch,
        )
        return sess.run(items, fn, image_uri)

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        """Shut down the executor."""
        with self._lock:
            self._shutdown = True


def _parse_memory_gb(memory: str) -> int:
    """Parse memory string like '4GB' or '512MB' into GB (int)."""
    memory = memory.strip().upper()
    if memory.endswith("GB"):
        return int(memory[:-2])
    if memory.endswith("MB"):
        mb = int(memory[:-2])
        return max(1, mb // 1024)
    # Assume GB if no unit
    return int(memory)
