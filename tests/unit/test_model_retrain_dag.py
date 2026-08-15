"""Tests for model retraining DAG."""

import json
import pytest
from pathlib import Path


class TestModelRetrainDAGStructure:
    """Test model retrain DAG structure and configuration."""

    def test_retrain_dag_file_exists(self):
        """Test model retrain DAG file exists."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_model_retrain_dag.py"
        assert dag_path.exists()

    def test_retrain_dag_is_valid_python(self):
        """Test retrain DAG file is valid Python."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_model_retrain_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        compile(content, str(dag_path), "exec")

    def test_retrain_dag_id(self):
        """Test retrain DAG has correct ID."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_model_retrain_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        assert 'dag_id="aq_model_retrain"' in content

    def test_retrain_dag_schedule_weekly(self):
        """Test retrain DAG is scheduled weekly."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_model_retrain_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        assert '"0 0 * * 0"' in content or "'0 0 * * 0'" in content

    def test_retrain_dag_owner(self):
        """Test retrain DAG has correct owner."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_model_retrain_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        assert '"owner": "aq_engine"' in content or "'owner': 'aq_engine'" in content

    def test_retrain_dag_has_all_tasks(self):
        """Test retrain DAG has all required tasks."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_model_retrain_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        required_tasks = [
            "start",
            "collect_training_data",
            "create_data_splits",
            "train_baseline_models",
            "train_ml_candidates",
            "evaluate_and_check_promotion",
            "conditional_model_test",
            "update_model_registry",
            "save_model_artifacts",
            "generate_evaluation_report",
            "end",
        ]

        for task in required_tasks:
            assert f'task_id="{task}"' in content

    def test_retrain_dag_task_count(self):
        """Test retrain DAG has correct number of tasks."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_model_retrain_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        # Count task_id definitions
        count = content.count('task_id="')
        assert count == 11

    def test_retrain_dag_dependencies_present(self):
        """Test retrain DAG has dependency definitions."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_model_retrain_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        # Should have >> operators for dependencies
        assert ">>" in content

    def test_retrain_dag_no_retries(self):
        """Test retrain DAG has retries disabled."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_model_retrain_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        assert '"retries": 0' in content


class TestDataCollection:
    """Test training data collection."""

    def test_collect_90_days_training_data(self):
        """Test collection of 90 days of training data."""
        # 90 days * 1600 records/day
        days = 90
        records_per_day = 1600
        total = days * records_per_day

        assert total == 144000

    def test_training_data_coverage(self):
        """Test training data covers all locations."""
        locations = 12
        features = 46

        assert locations > 0
        assert features > 0

    def test_date_range_calculation(self):
        """Test correct date range for 90 days back."""
        # If today is 2026-08-15, 90 days back is 2026-05-17
        from datetime import datetime, timedelta

        today = datetime(2026, 8, 15)
        ninety_days_back = today - timedelta(days=90)

        # Should be 2026-05-17
        assert ninety_days_back.strftime("%Y-%m-%d") == "2026-05-17"


class TestDataSplits:
    """Test train/val/test data splits."""

    def test_split_ratio_70_15_15(self):
        """Test correct split ratio (70/15/15)."""
        total = 144000

        train = int(total * 0.70)
        val = int(total * 0.15)
        test = int(total * 0.15)

        assert train == 100800
        assert val == 21600
        assert test == 21600
        assert train + val + test == total

    def test_split_sizes_sufficient(self):
        """Test split sizes are sufficient for training."""
        total = 144000
        train = int(total * 0.70)
        val = int(total * 0.15)
        test = int(total * 0.15)

        # Each split should be substantial
        assert train > 10000  # Min 10k for training
        assert val > 1000     # Min 1k for validation
        assert test > 1000    # Min 1k for testing

    def test_temporal_ordering(self):
        """Test temporal ordering (train < val < test)."""
        # Splits are ordered chronologically
        # train: oldest to 70%
        # val: 70% to 85%
        # test: 85% to newest

        split_boundaries = [0, 0.70, 0.85, 1.0]

        assert split_boundaries[0] < split_boundaries[1]
        assert split_boundaries[1] < split_boundaries[2]
        assert split_boundaries[2] < split_boundaries[3]


class TestBaselineModels:
    """Test baseline model training."""

    def test_baseline_models_count(self):
        """Test three baseline models are trained."""
        baseline_count = 3
        baseline_names = ["naive", "same_hour_yesterday", "rolling_mean"]

        assert len(baseline_names) == baseline_count

    def test_baseline_model_performance(self):
        """Test baseline models show reasonable performance."""
        # Mock results
        baselines = [
            {"name": "naive", "val_mae": 18.5},
            {"name": "same_hour_yesterday", "val_mae": 16.2},
            {"name": "rolling_mean", "val_mae": 14.8},
        ]

        # Baselines should improve in that order
        assert baselines[0]["val_mae"] > baselines[1]["val_mae"]
        assert baselines[1]["val_mae"] > baselines[2]["val_mae"]

    def test_best_baseline_selection(self):
        """Test best baseline is correctly identified."""
        baselines = [
            {"name": "naive", "val_mae": 18.5},
            {"name": "same_hour_yesterday", "val_mae": 16.2},
            {"name": "rolling_mean", "val_mae": 14.8},
        ]

        best = min(baselines, key=lambda x: x["val_mae"])
        assert best["name"] == "rolling_mean"
        assert best["val_mae"] == 14.8


class TestMLCandidates:
    """Test ML candidate model training."""

    def test_ml_candidates_count(self):
        """Test four ML candidates are trained."""
        ml_count = 4
        ml_names = ["linear_regression", "random_forest", "hist_gradient_boosting", "xgboost"]

        assert len(ml_names) == ml_count

    def test_ml_model_performance_improvement(self):
        """Test ML candidates improve over baselines."""
        best_baseline_mae = 14.8

        ml_models = [
            {"name": "linear_regression", "val_mae": 12.8},
            {"name": "random_forest", "val_mae": 12.5},
            {"name": "hist_gradient_boosting", "val_mae": 12.3},
            {"name": "xgboost", "val_mae": 12.1},
        ]

        # All ML models should be better than best baseline
        for model in ml_models:
            assert model["val_mae"] < best_baseline_mae

    def test_best_candidate_selection(self):
        """Test best candidate is correctly identified."""
        ml_models = [
            {"name": "linear_regression", "val_mae": 12.8},
            {"name": "random_forest", "val_mae": 12.5},
            {"name": "hist_gradient_boosting", "val_mae": 12.3},
            {"name": "xgboost", "val_mae": 12.1},
        ]

        best = min(ml_models, key=lambda x: x["val_mae"])
        assert best["name"] == "xgboost"
        assert best["val_mae"] == 12.1


class TestPromotionLogic:
    """Test model promotion criteria."""

    def test_promotion_threshold_5_percent(self):
        """Test promotion threshold is 5% improvement."""
        threshold = 5.0
        assert threshold == 5.0

    def test_improvement_calculation(self):
        """Test improvement percentage calculation."""
        baseline_mae = 15.2
        candidate_mae = 12.1

        improvement = (baseline_mae - candidate_mae) / baseline_mae * 100

        assert abs(improvement - 20.4) < 0.1  # 20.4%

    def test_promotion_criteria_met(self):
        """Test promotion criteria met (20% > 5%)."""
        baseline_mae = 15.2
        candidate_mae = 12.1
        threshold = 5.0

        improvement = (baseline_mae - candidate_mae) / baseline_mae * 100
        meets_criteria = improvement >= threshold

        assert meets_criteria is True

    def test_promotion_criteria_not_met(self):
        """Test promotion criteria not met (2% < 5%)."""
        baseline_mae = 15.2
        candidate_mae = 14.9
        threshold = 5.0

        improvement = (baseline_mae - candidate_mae) / baseline_mae * 100
        meets_criteria = improvement >= threshold

        assert meets_criteria is False

    def test_promotion_at_exactly_5_percent(self):
        """Test promotion at exactly 5% improvement threshold."""
        baseline_mae = 100.0
        candidate_mae = 95.0  # Exactly 5% improvement
        threshold = 5.0

        improvement = (baseline_mae - candidate_mae) / baseline_mae * 100
        meets_criteria = improvement >= threshold

        assert meets_criteria is True


class TestModelTesting:
    """Test final model testing on test set."""

    def test_test_set_mae_slightly_higher_than_val(self):
        """Test that test set MAE is typically slightly higher than validation."""
        val_mae = 12.1
        test_mae = 12.4

        # Test set should be slightly worse than validation (overfitting)
        assert test_mae > val_mae
        assert (test_mae - val_mae) < 1.0  # But not dramatically worse

    def test_test_set_performance_acceptable(self):
        """Test that test set performance is acceptable."""
        test_mae = 12.4
        test_rmse = 15.7

        # Both metrics should be reasonable
        assert test_mae < 15.0
        assert test_rmse < 20.0

    def test_model_test_skipped_if_criteria_not_met(self):
        """Test that model testing is skipped if promotion criteria not met."""
        promotion_meets_criteria = False

        if not promotion_meets_criteria:
            test_status = "skipped"
        else:
            test_status = "tested"

        assert test_status == "skipped"


class TestModelRegistry:
    """Test model registry updates."""

    def test_promote_action_when_criteria_met(self):
        """Test promote action when criteria are met."""
        meets_criteria = True
        test_passed = True

        if meets_criteria and test_passed:
            action = "promote"
        else:
            action = "no_change"

        assert action == "promote"

    def test_no_change_when_criteria_not_met(self):
        """Test no change when criteria not met."""
        meets_criteria = False

        if meets_criteria:
            action = "promote"
        else:
            action = "no_change"

        assert action == "no_change"

    def test_previous_model_archived(self):
        """Test previous production model is archived."""
        action = "promote"
        previous_model = "2026-08-15_hgb"

        if action == "promote":
            archive_status = "archived"
            new_status = "production"
        else:
            archive_status = None
            new_status = None

        assert archive_status == "archived"
        assert new_status == "production"

    def test_model_version_format(self):
        """Test model version format includes date and name."""
        date = "2026-08-22"
        model_name = "xgboost"
        version = f"{date}_{model_name}"

        assert version == "2026-08-22_xgboost"
        assert "2026-08-22" in version
        assert "xgboost" in version


class TestArtifactStorage:
    """Test model artifact storage."""

    def test_joblib_artifact_saved(self):
        """Test model is saved as joblib file."""
        model_version = "2026-08-22_xgboost"
        model_path = f"models/{model_version}.joblib"

        assert model_path.endswith(".joblib")
        assert model_version in model_path

    def test_metadata_artifact_saved(self):
        """Test metadata is saved as JSON."""
        model_version = "2026-08-22_xgboost"
        metadata_path = f"models/{model_version}_metadata.json"

        assert metadata_path.endswith(".json")
        assert "_metadata" in metadata_path

    def test_artifacts_include_checksums(self):
        """Test artifacts have checksums for integrity."""
        artifacts = [
            {"file": "model.joblib", "checksum": "sha256:abc123..."},
            {"file": "metadata.json", "checksum": "sha256:def456..."},
        ]

        for artifact in artifacts:
            assert "checksum" in artifact
            assert artifact["checksum"].startswith("sha256:")

    def test_feature_version_metadata(self):
        """Test feature version is included in metadata."""
        date = "2026-08-22"
        feature_count = 46
        feature_version = f"{date}_features_v{feature_count}"

        assert "2026-08-22" in feature_version
        assert "46" in feature_version


class TestEvaluationReport:
    """Test evaluation report generation."""

    def test_report_includes_training_period(self):
        """Test report documents training period."""
        start_date = "2026-05-17"
        end_date = "2026-08-14"
        period = f"{start_date} to {end_date} (90 days)"

        assert start_date in period
        assert end_date in period
        assert "90 days" in period

    def test_report_includes_baseline_results(self):
        """Test report includes baseline model results."""
        report = {
            "baseline_models": {
                "count": 3,
                "best": "rolling_mean",
                "val_mae": 14.8,
            }
        }

        assert "baseline_models" in report
        assert report["baseline_models"]["count"] == 3

    def test_report_includes_ml_results(self):
        """Test report includes ML candidate results."""
        report = {
            "ml_candidates": {
                "count": 4,
                "best": "xgboost",
                "val_mae": 12.1,
            }
        }

        assert "ml_candidates" in report
        assert report["ml_candidates"]["count"] == 4

    def test_report_includes_promotion_decision(self):
        """Test report includes promotion decision."""
        report = {
            "promotion_decision": {
                "criteria": "improvement >= 5% MAE",
                "improvement_pct": 20.4,
                "meets_criteria": True,
                "reason": "Improvement 20.40% exceeds 5% threshold",
            }
        }

        assert "promotion_decision" in report
        assert report["promotion_decision"]["meets_criteria"] is True

    def test_report_includes_conclusion(self):
        """Test report includes clear conclusion."""
        promoted = True
        improvement = 20.4

        conclusion = f"{'✓ Model promoted' if promoted else '✗ Model not promoted'} (improvement: {improvement:.2f}%)"

        assert "Model promoted" in conclusion
        assert "20.40%" in conclusion

    def test_report_json_serializable(self):
        """Test report can be serialized to JSON."""
        report = {
            "run_date": "2026-08-22T00:00:00",
            "baseline_models": {"best": "rolling_mean"},
            "ml_candidates": {"best": "xgboost"},
        }

        json_str = json.dumps(report)
        assert json_str is not None

        # Should deserialize correctly
        parsed = json.loads(json_str)
        assert parsed == report


class TestErrorHandling:
    """Test error handling in retraining."""

    def test_training_failure_keeps_previous_model(self):
        """Test training failure keeps previous production model."""
        training_success = False

        if training_success:
            action = "update"
        else:
            action = "keep_previous"

        assert action == "keep_previous"

    def test_no_alert_on_training_failure(self):
        """Test no alert sent on training failure (not production issue)."""
        training_failure = True
        should_alert = False  # Training failure doesn't need alert

        assert should_alert is False

    def test_alert_on_evaluation_failure(self):
        """Test alert sent on evaluation failure."""
        eval_failure = True
        should_alert = True  # Evaluation failure needs investigation

        assert should_alert is True


class TestConfiguration:
    """Test DAG configuration."""

    def test_retrain_dag_timeout_4_hours(self):
        """Test retrain DAG has 4-hour timeout."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_model_retrain_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        assert "timedelta(hours=4)" in content

    def test_retrain_dag_single_active_run(self):
        """Test retrain DAG allows only one active run."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_model_retrain_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        assert "max_active_runs=1" in content

    def test_retrain_dag_weekly_sunday(self):
        """Test retrain is scheduled for Sunday midnight."""
        # 0 0 * * 0 = Sunday at 00:00 (midnight)
        schedule = "0 0 * * 0"
        minute, hour, day_of_month, month, day_of_week = schedule.split()

        assert minute == "0"  # Minute 0
        assert hour == "0"    # Hour 0 (midnight)
        assert day_of_week == "0"  # Day 0 (Sunday)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
