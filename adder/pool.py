"""Pool — reusable cluster that amortizes worker startup across multiple map calls."""

from __future__ import annotations

from typing import Callable, Iterable, Literal, TypeVar

T = TypeVar("T")
U = TypeVar("U")


class Pool:
    """A reusable cluster that provisions workers once and reuses them.

    Usage::

        pool = Pool(workers=20, cpu=4)
        results1 = pool.map(items1, fn1)
        results2 = pool.map(items2, fn2)
        pool.shutdown()
    """

    def __init__(
        self,
        workers: int = 10,
        cpu: int = 2,
        memory: str = "4GB",
        backend: Literal["fargate", "ec2"] = "fargate",
        spot: bool = False,
        region: str | None = None,
    ) -> None:
        self._workers = workers
        self._cpu = cpu
        self._memory = memory
        self._backend = backend
        self._spot = spot
        self._region = region
        self._image_uri: str | None = None
        self._cfg = None

    def _get_cfg_and_image(self):
        if self._cfg is None or self._image_uri is None:
            from .config import load as load_config
            from .env import ensure_image

            self._cfg = load_config()
            if self._region:
                self._cfg.region = self._region
            self._cfg.validate()
            self._image_uri = ensure_image(self._cfg)
        return self._cfg, self._image_uri

    def map(
        self,
        items: Iterable[T],
        fn: Callable[[T], U],
        *,
        timeout: int | None = None,
        max_cost: float | None = None,
        cost_alert: float | None = None,
    ) -> list[U]:
        """Map fn over items using the pool's workers.

        Returns results in the same order as items.
        """
        from .session import Session

        cfg, image_uri = self._get_cfg_and_image()

        from .executor import _parse_memory_gb

        memory_gb = _parse_memory_gb(self._memory)

        sess = Session(
            cfg=cfg,
            workers=self._workers,
            cpu=self._cpu,
            memory_gb=memory_gb,
            backend=self._backend,
            spot=self._spot,
            max_cost=max_cost,
            cost_alert=cost_alert,
            timeout=timeout,
        )
        return sess.run(list(items), fn, image_uri)

    def shutdown(self) -> None:
        """Release pool resources."""
        self._cfg = None
        self._image_uri = None
