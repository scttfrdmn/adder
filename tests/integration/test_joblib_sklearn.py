"""Integration tests for the adder joblib backend with scikit-learn.

Requires: BURST_INTEGRATION_TEST=1, substrate in PATH, scikit-learn installed.
"""

from __future__ import annotations

from unittest.mock import patch

import boto3
import pytest

from adder.config import load as load_config
from adder.session import Session


def test_joblib_backend_registered():
    """AdderBackend is registered as 'adder' in joblib."""
    import adder  # noqa: F401 — registers the backend
    import joblib

    with joblib.parallel_backend("adder"):
        pass  # Should not raise


def test_joblib_parallel_basic(substrate_config):
    """joblib.Parallel with adder backend dispatches work via cloud."""
    import adder  # noqa: F401
    import joblib

    cfg = load_config()
    s3 = boto3.client("s3", region_name=cfg.region)
    s3.create_bucket(Bucket=cfg.s3_bucket)

    def double(x):
        return x * 2

    items = list(range(6))
    expected = [x * 2 for x in items]

    # We need to intercept Session.run to simulate workers

    def fake_run(self, items_arg, fn, image_uri):
        # Simulate all workers completing synchronously
        return [fn(x) for x in items_arg]

    with patch.object(Session, "run", fake_run):
        with joblib.parallel_backend("adder", workers=2):
            results = joblib.Parallel(n_jobs=-1)(joblib.delayed(double)(x) for x in items)

    assert results == expected


def test_joblib_sklearn_grid_search(substrate_config):
    """GridSearchCV works transparently with the adder backend.

    This test verifies the joblib integration surface without requiring
    real AWS — Session.run is patched to execute locally.
    """
    pytest.importorskip("sklearn")
    from sklearn.datasets import make_classification
    from sklearn.model_selection import GridSearchCV
    from sklearn.svm import SVC
    import adder  # noqa: F401

    import joblib

    cfg = load_config()
    s3 = boto3.client("s3", region_name=cfg.region)
    s3.create_bucket(Bucket=cfg.s3_bucket)

    X, y = make_classification(n_samples=50, n_features=4, random_state=42)
    param_grid = {"C": [0.1, 1.0], "kernel": ["rbf", "linear"]}


    def fake_run(self, items_arg, fn, image_uri):
        return [fn(x) for x in items_arg]

    with patch.object(Session, "run", fake_run):
        with joblib.parallel_backend("adder", workers=4):
            clf = GridSearchCV(SVC(), param_grid, cv=2, n_jobs=-1)
            clf.fit(X, y)

    assert clf.best_params_ is not None
    assert "C" in clf.best_params_
