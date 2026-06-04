"""Unit tests for adder/joblib_backend.py."""

from adder.joblib_backend import AdderBackend


def test_effective_n_jobs_explicit():
    backend = AdderBackend(workers=20)
    assert backend.effective_n_jobs(5) == 5
    assert backend.effective_n_jobs(1) == 1


def test_effective_n_jobs_minus_one():
    backend = AdderBackend(workers=20)
    assert backend.effective_n_jobs(-1) == 20


def test_effective_n_jobs_negative():
    """n_jobs=-2 means workers - 1."""
    backend = AdderBackend(workers=10)
    assert backend.effective_n_jobs(-2) == 9


def test_effective_n_jobs_clamps_to_one():
    backend = AdderBackend(workers=1)
    assert backend.effective_n_jobs(-10) == 1


def test_backend_registration():
    """AdderBackend should be registered as 'adder' in joblib."""
    import adder  # noqa: F401 — importing adder registers the backend
    import joblib

    with joblib.parallel_backend("adder"):
        pass  # Should not raise


def test_abort_everything():
    backend = AdderBackend(workers=5)
    # Should not raise even with no active executor
    backend.abort_everything()
    backend.abort_everything(ensure_ready=True)
