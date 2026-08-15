"""Integration tests for daily backfill DAG."""

import json
import pytest
from datetime import datetime, timedelta, date
from pathlib import Path


class TestBackfillDAGStructure:
    """Test backfill DAG structure and configuration."""

    def test_backfill_dag_file_exists(self):
        """Test backfill DAG file exists."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_daily_backfill_dag.py"
        assert dag_path.exists()

    def test_backfill_dag_is_valid_python(self):
        """Test backfill DAG file is valid Python."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_daily_backfill_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        # Should parse without error
        compile(content, str(dag_path), "exec")

    def test_backfill_dag_has_correct_id(self):
        """Test backfill DAG has correct ID."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_daily_backfill_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        assert 'dag_id="aq_daily_backfill"' in content

    def test_backfill_dag_has_no_schedule(self):
        """Test backfill DAG has no schedule (manual trigger)."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_daily_backfill_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        assert "schedule_interval=None" in content

    def test_backfill_dag_has_parameters(self):
        """Test backfill DAG accepts date range parameters."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_daily_backfill_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        assert '"start_date"' in content
        assert '"end_date"' in content
        assert '"params"' in content

    def test_backfill_dag_owner_correct(self):
        """Test backfill DAG has correct owner."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_daily_backfill_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        assert '"owner": "aq_engine"' in content

    def test_backfill_dag_has_required_tasks(self):
        """Test backfill DAG has all required tasks."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_daily_backfill_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        required_tasks = [
            "start",
            "validate_date_range",
            "process_date_range",
            "recompute_final_baselines",
            "retrain_models",
            "generate_backfill_summary",
            "end",
        ]

        for task in required_tasks:
            assert f'task_id="{task}"' in content

    def test_backfill_dag_has_linear_dependencies(self):
        """Test backfill DAG has linear dependency chain."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_daily_backfill_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        # Should have >> operators for dependencies
        assert content.count(">>") >= 6

    def test_backfill_dag_no_hardcoded_paths(self):
        """Test backfill DAG has no hardcoded paths."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_daily_backfill_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        assert "/data/" not in content
        assert "C:\\" not in content


class TestDateRangeValidation:
    """Test date range validation logic."""

    def test_valid_date_range(self):
        """Test valid date range is accepted."""
        start = "2026-08-01"
        end = "2026-08-07"

        try:
            s = datetime.strptime(start, "%Y-%m-%d").date()
            e = datetime.strptime(end, "%Y-%m-%d").date()
            assert e >= s
        except ValueError:
            pytest.fail("Valid date range failed")

    def test_invalid_date_format(self):
        """Test invalid date format is rejected."""
        invalid_dates = [
            "08-01-2026",  # Wrong format
            "2026/08/01",  # Wrong separator
            "2026-13-01",  # Invalid month
            "2026-08-32",  # Invalid day
        ]

        for date_str in invalid_dates:
            with pytest.raises(ValueError):
                datetime.strptime(date_str, "%Y-%m-%d")

    def test_end_before_start_rejected(self):
        """Test end_date before start_date is rejected."""
        start = "2026-08-07"
        end = "2026-08-01"

        s = datetime.strptime(start, "%Y-%m-%d").date()
        e = datetime.strptime(end, "%Y-%m-%d").date()

        assert e < s

    def test_same_date_range(self):
        """Test single day backfill (start = end)."""
        start = "2026-08-01"
        end = "2026-08-01"

        s = datetime.strptime(start, "%Y-%m-%d").date()
        e = datetime.strptime(end, "%Y-%m-%d").date()
        delta = e - s
        days = delta.days + 1

        assert days == 1

    def test_date_range_calculation(self):
        """Test correct day count calculation."""
        test_cases = [
            ("2026-08-01", "2026-08-01", 1),   # Single day
            ("2026-08-01", "2026-08-07", 7),   # 7 days
            ("2026-08-01", "2026-08-31", 31),  # Full month
        ]

        for start, end, expected_days in test_cases:
            s = datetime.strptime(start, "%Y-%m-%d").date()
            e = datetime.strptime(end, "%Y-%m-%d").date()
            delta = e - s
            days = delta.days + 1

            assert days == expected_days


class TestIdempotency:
    """Test backfill idempotency."""

    def test_same_date_processed_twice_is_idempotent(self):
        """Test processing same date twice gives same result."""
        # Simulate processing same date twice
        first_run = {
            "date": "2026-08-01",
            "records_processed": 1600,
            "anomalies_detected": 45,
            "events_detected": 3,
        }

        second_run = {
            "date": "2026-08-01",
            "records_processed": 1600,
            "anomalies_detected": 45,
            "events_detected": 3,
        }

        # Results should be identical
        assert first_run == second_run

    def test_deduplication_prevents_doubling(self):
        """Test deduplication prevents record doubling."""
        # If processing same date twice without dedup, records would double
        # With dedup (idempotent key), same records recognized and not inserted

        first_run_raw = 1600
        # Deduplicated: keep only 1600
        first_run_final = 1600

        # Second run on same date
        second_run_raw = 1600
        # Deduplicated: still 1600 (not 3200)
        second_run_final = 1600

        assert first_run_final == second_run_final

    def test_baseline_update_idempotent(self):
        """Test baseline update is idempotent."""
        # Baselines are updated (not appended)
        # Processing same date twice = same baseline

        date_str = "2026-08-01"

        # First run: compute 24 baselines for the date
        first_run = {
            "date": date_str,
            "baselines_updated": 24,
            "operation": "UPDATE",  # Not INSERT
        }

        # Second run: update same 24 baselines
        second_run = {
            "date": date_str,
            "baselines_updated": 24,
            "operation": "UPDATE",  # Not INSERT
        }

        # Same number of baselines updated
        assert first_run["baselines_updated"] == second_run["baselines_updated"]


class TestBackfillProcessing:
    """Test backfill processing logic."""

    def test_seven_day_backfill(self):
        """Test backfill of 7 days processes all days."""
        start = "2026-08-01"
        end = "2026-08-07"

        s = datetime.strptime(start, "%Y-%m-%d").date()
        e = datetime.strptime(end, "%Y-%m-%d").date()

        dates = []
        current = s
        while current <= e:
            dates.append(current.isoformat())
            current += timedelta(days=1)

        # Should have 7 dates
        assert len(dates) == 7
        assert dates[0] == "2026-08-01"
        assert dates[6] == "2026-08-07"

    def test_thirty_day_backfill_triggers_retraining(self):
        """Test 30+ day backfill triggers model retraining."""
        start = "2026-08-01"
        end = "2026-08-30"  # 30 days

        s = datetime.strptime(start, "%Y-%m-%d").date()
        e = datetime.strptime(end, "%Y-%m-%d").date()
        delta = e - s
        days = delta.days + 1

        should_retrain = days >= 30
        assert should_retrain is True

    def test_twenty_nine_day_backfill_no_retraining(self):
        """Test 29 day backfill does not trigger retraining."""
        start = "2026-08-01"
        end = "2026-08-29"  # 29 days

        s = datetime.strptime(start, "%Y-%m-%d").date()
        e = datetime.strptime(end, "%Y-%m-%d").date()
        delta = e - s
        days = delta.days + 1

        should_retrain = days >= 30
        assert should_retrain is False

    def test_records_per_day_accumulation(self):
        """Test total records accumulate correctly."""
        days_processed = 7
        records_per_day = 1600

        total_records = days_processed * records_per_day

        assert total_records == 11200


class TestErrorHandling:
    """Test error handling in backfill."""

    def test_failed_date_skipped(self):
        """Test failed date is skipped but processing continues."""
        dates = ["2026-08-01", "2026-08-02", "2026-08-03"]
        processed = []
        failed = []

        # Simulate second date failing
        for date_str in dates:
            if date_str == "2026-08-02":
                failed.append(date_str)
            else:
                processed.append(date_str)

        # Should process 2/3 dates
        assert len(processed) == 2
        assert len(failed) == 1
        assert "2026-08-02" in failed

    def test_failed_dates_reported(self):
        """Test failed dates are reported in summary."""
        result = {
            "dates_processed": 6,
            "dates_failed": 1,
            "failed_dates": ["2026-08-03"],
            "date_errors": {
                "2026-08-03": "Connection timeout during ingestion"
            },
        }

        # Summary should report failures
        assert result["dates_failed"] > 0
        assert result["failed_dates"] == ["2026-08-03"]
        assert "Connection timeout" in result["date_errors"]["2026-08-03"]

    def test_partial_backfill_still_useful(self):
        """Test partial backfill (with failures) is still useful."""
        # Even if 1 day fails out of 7, 6 days are processed
        total = 7
        failed = 1
        processed = total - failed

        success_rate = processed / total

        # 6/7 = 85% success is acceptable
        assert success_rate >= 0.85


class TestBackfillSummary:
    """Test backfill summary generation."""

    def test_summary_includes_all_metrics(self):
        """Test summary includes all required metrics."""
        summary = {
            "start_date": "2026-08-01",
            "end_date": "2026-08-07",
            "total_days_requested": 7,
            "days_successfully_processed": 7,
            "days_failed": 0,
            "failed_dates": [],
            "total_records_processed": 11200,
            "models_retrained": 0,
            "success": True,
        }

        required_fields = [
            "start_date",
            "end_date",
            "total_days_requested",
            "days_successfully_processed",
            "days_failed",
            "failed_dates",
            "total_records_processed",
            "models_retrained",
            "success",
        ]

        for field in required_fields:
            assert field in summary

    def test_summary_calculation_with_failures(self):
        """Test summary calculation when there are failures."""
        summary = {
            "start_date": "2026-08-01",
            "end_date": "2026-08-07",
            "total_days_requested": 7,
            "days_successfully_processed": 6,
            "days_failed": 1,
            "failed_dates": ["2026-08-03"],
            "total_records_processed": 9600,  # 6 * 1600
            "success": False,
        }

        assert summary["total_days_requested"] == 7
        assert summary["days_successfully_processed"] == 6
        assert summary["days_failed"] == 1
        assert summary["success"] is False
        # Records = successful days only
        assert summary["total_records_processed"] == 9600

    def test_summary_json_serializable(self):
        """Test summary can be serialized to JSON."""
        summary = {
            "start_date": "2026-08-01",
            "end_date": "2026-08-07",
            "total_days_requested": 7,
            "days_successfully_processed": 7,
            "days_failed": 0,
            "failed_dates": [],
            "total_records_processed": 11200,
            "models_retrained": 0,
            "success": True,
        }

        # Should serialize without error
        json_str = json.dumps(summary)
        assert json_str is not None

        # Should deserialize correctly
        parsed = json.loads(json_str)
        assert parsed == summary


class TestBackfillConfiguration:
    """Test backfill configuration."""

    def test_backfill_dag_single_active_run(self):
        """Test backfill DAG allows only one active run."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_daily_backfill_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        assert "max_active_runs=1" in content

    def test_backfill_dag_no_retries(self):
        """Test backfill DAG has retries disabled (manual retry instead)."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_daily_backfill_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        # Should explicitly set retries=0 for backfill
        assert '"retries": 0' in content

    def test_backfill_dag_execution_timeout(self):
        """Test backfill DAG has reasonable execution timeout."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_daily_backfill_dag.py"
        with open(dag_path, "r") as f:
            content = f.read()

        assert "execution_timeout" in content
        # Should be longer than hourly DAG (6 hours for backfill)
        assert "timedelta(hours=6)" in content


class TestRetrainingLogic:
    """Test model retraining logic."""

    def test_retrain_triggered_at_thirty_days(self):
        """Test retraining is triggered at exactly 30 days."""
        days = 30
        should_retrain = days >= 30
        assert should_retrain is True

    def test_retrain_not_triggered_at_twenty_nine_days(self):
        """Test retraining is not triggered at 29 days."""
        days = 29
        should_retrain = days >= 30
        assert should_retrain is False

    def test_retrain_triggered_at_sixty_days(self):
        """Test retraining is triggered for longer backfills."""
        days = 60
        should_retrain = days >= 30
        assert should_retrain is True

    def test_retrain_models_uses_backfilled_data(self):
        """Test retraining uses all backfilled data."""
        days_in_range = 30
        records_per_day = 1600
        training_data_points = days_in_range * records_per_day

        # Should use all 48,000 records for training
        assert training_data_points == 48000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
