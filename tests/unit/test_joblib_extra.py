"""Additional tests for joblib backend configure/apply_async paths."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from adder.joblib_backend import AdderBackend, _FutureWrapper


def test_future_wrapper_get():
    import concurrent.futures

    f = concurrent.futures.Future()
    f.set_result(99)
    wrapper = _FutureWrapper(f)
    assert wrapper.get() == 99


def test_configure_sets_executor():
    backend = AdderBackend(workers=5)
    with patch("adder.executor.CloudExecutor") as MockExc:
        MockExc.return_value = MagicMock()
        n = backend.configure(n_jobs=5)
    assert n == 5
    assert backend._executor is not None


def test_configure_n_jobs_minus_one():
    backend = AdderBackend(workers=10)
    with patch("adder.executor.CloudExecutor"):
        n = backend.configure(n_jobs=-1)
    assert n == 10


def test_apply_async_submits_to_executor():
    """apply_async calls executor.submit and returns a _FutureWrapper."""
    import concurrent.futures

    backend = AdderBackend(workers=5)

    mock_executor = MagicMock()
    future = concurrent.futures.Future()
    future.set_result("done")
    mock_executor.submit.return_value = future
    backend._executor = mock_executor

    func = MagicMock(return_value="done")
    wrapper = backend.apply_async(func)

    mock_executor.submit.assert_called_once_with(func)
    assert wrapper.get() == "done"


def test_apply_async_with_callback():
    """apply_async calls callback with result when future resolves."""
    import concurrent.futures

    backend = AdderBackend(workers=5)

    mock_executor = MagicMock()
    future = concurrent.futures.Future()
    future.set_result("result_value")
    mock_executor.submit.return_value = future
    backend._executor = mock_executor

    received = []
    backend.apply_async(lambda: "result_value", callback=received.append)

    # Callback may be async; wait a bit
    import time

    time.sleep(0.05)
    assert "result_value" in received


def test_abort_everything_shuts_down_executor():
    backend = AdderBackend(workers=5)
    mock_executor = MagicMock()
    backend._executor = mock_executor

    backend.abort_everything()

    mock_executor.shutdown.assert_called_once_with(wait=False)
    assert backend._executor is None
