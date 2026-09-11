"""Regression tests for model evaluation metrics."""

import numpy as np
import pytest

from aq_engine.ml.evaluation import ModelEvaluator


def test_mape_excludes_zero_targets_from_denominator():
    metrics = ModelEvaluator.evaluate(
        predictions=np.array([12.0, 5.0]),
        actuals=np.array([10.0, 0.0]),
    )

    assert metrics["mape"] == pytest.approx(20.0)
    # Other metrics still use every valid sample.
    assert metrics["mae"] == pytest.approx(3.5)
    assert metrics["n_samples"] == 2


def test_mape_returns_none_when_all_targets_are_zero():
    metrics = ModelEvaluator.evaluate(
        predictions=np.array([1.0, 5.0]),
        actuals=np.array([0.0, 0.0]),
    )

    assert metrics["mape"] is None
    assert metrics["mae"] == pytest.approx(3.0)


def test_mape_uses_absolute_negative_targets():
    metrics = ModelEvaluator.evaluate(
        predictions=np.array([-8.0, -18.0]),
        actuals=np.array([-10.0, -20.0]),
    )

    assert metrics["mape"] == pytest.approx(15.0)


def test_nan_pairs_are_removed_before_mape_filtering():
    metrics = ModelEvaluator.evaluate(
        predictions=np.array([12.0, np.nan, 3.0]),
        actuals=np.array([10.0, 2.0, 0.0]),
    )

    assert metrics["mape"] == pytest.approx(20.0)
    assert metrics["n_samples"] == 2


def test_standard_nonzero_mape_is_unchanged():
    metrics = ModelEvaluator.evaluate(
        predictions=np.array([9.0, 22.0]),
        actuals=np.array([10.0, 20.0]),
    )

    assert metrics["mape"] == pytest.approx(10.0)


def test_length_mismatch_still_raises():
    with pytest.raises(ValueError, match="same length"):
        ModelEvaluator.evaluate(
            predictions=np.array([1.0]),
            actuals=np.array([1.0, 2.0]),
        )
