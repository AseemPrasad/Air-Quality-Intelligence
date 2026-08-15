"""ML model evaluation and comparison."""

import logging
from typing import Dict, List, Tuple, Optional
import numpy as np

logger = logging.getLogger(__name__)


class ModelEvaluator:
    """Evaluate and compare PM2.5 models."""

    def __init__(self):
        """Initialize evaluator."""
        pass

    @staticmethod
    def evaluate(
        predictions: np.ndarray,
        actuals: np.ndarray,
    ) -> Dict[str, float]:
        """Compute evaluation metrics.

        Args:
            predictions: Predicted values
            actuals: Actual values

        Returns:
            Dict with mae, rmse, mape, median_ae
        """
        if len(predictions) != len(actuals):
            raise ValueError("Predictions and actuals must have same length")

        # Remove NaN pairs
        valid = ~(np.isnan(predictions) | np.isnan(actuals))
        pred = predictions[valid]
        actual = actuals[valid]

        if len(pred) == 0:
            return {"mae": None, "rmse": None, "mape": None, "median_ae": None}

        errors = np.abs(pred - actual)
        squared_errors = (pred - actual) ** 2

        mae = float(np.mean(errors))
        rmse = float(np.sqrt(np.mean(squared_errors)))
        median_ae = float(np.median(errors))

        # MAPE (handle division by zero)
        mape_values = np.divide(
            errors,
            np.maximum(np.abs(actual), 1e-10),
            out=np.zeros_like(errors),
            where=np.abs(actual) > 1e-10,
        )
        mape = float(np.mean(mape_values) * 100) if np.any(actual > 1e-10) else None

        return {
            "mae": mae,
            "rmse": rmse,
            "mape": mape,
            "median_ae": median_ae,
            "n_samples": len(pred),
        }

    @staticmethod
    def compare_models(
        model_scores: Dict[str, Dict[str, float]],
    ) -> List[Tuple[str, float]]:
        """Rank models by MAE (best to worst).

        Args:
            model_scores: Dict mapping model_type → metrics

        Returns:
            List of (model_type, mae) sorted best to worst
        """
        ranked = sorted(
            [(m, s["mae"]) for m, s in model_scores.items() if s.get("mae") is not None],
            key=lambda x: x[1],
        )
        return ranked

    @staticmethod
    def check_promotion_criteria(
        candidate_mae: float,
        current_mae: float,
        min_improvement_pct: float = 5.0,
    ) -> bool:
        """Check if candidate model meets promotion criteria.

        Args:
            candidate_mae: Candidate model MAE
            current_mae: Current production MAE
            min_improvement_pct: Required improvement (%)

        Returns:
            True if candidate should be promoted
        """
        if current_mae is None or current_mae <= 0:
            return True

        improvement_pct = ((current_mae - candidate_mae) / current_mae) * 100
        should_promote = improvement_pct >= min_improvement_pct

        logger.info(
            f"Promotion check: candidate_mae={candidate_mae:.2f}, "
            f"current_mae={current_mae:.2f}, "
            f"improvement={improvement_pct:.1f}% "
            f"(required={min_improvement_pct}%) → {'PROMOTE' if should_promote else 'REJECT'}"
        )

        return should_promote
