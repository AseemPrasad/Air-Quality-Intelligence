"""Integration tests for Issue #18: Airflow Ingestion DAG Failure Propagation.

Verifies that the hourly ingestion DAG (aq_hourly_ingest_dag.py) correctly propagates
ingestion failures to Airflow:
1. Successful ingestion completes normally without raising exceptions
2. Failed ingestion (IngestionFailed exception) propagates to Airflow as AirflowException
3. Ingestion returning status != "success" raises AirflowException for Airflow to handle
4. Failed ingestion batch cannot be interpreted as successful Airflow task
"""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

# Skip tests if Airflow is not installed
pytest.importorskip("airflow")

from airflow.exceptions import AirflowException
from airflow.models import TaskInstance

from aq_engine.common import IngestionFailed


@pytest.fixture
def mock_context():
    """Create a mock Airflow context."""
    task_instance = Mock(spec=TaskInstance)
    task_instance.xcom_push = Mock()

    context = {
        "task_instance": task_instance,
        "execution_date": datetime.now(),
    }
    return context


class TestIngestionFailurePropagation:
    """Test that ingestion failures propagate to Airflow."""

    @patch("dags.aq_hourly_ingest_dag.IngestionOrchestrator")
    def test_successful_openaq_ingestion_completes_normally(
        self, mock_orchestrator_class, mock_context
    ):
        """Test successful OpenAQ ingestion completes without exception.

        Verifies that when IngestionOrchestrator.ingest_source() returns
        a successful result, the task completes normally.
        """
        # Import after patching
        from dags.aq_hourly_ingest_dag import ingest_openaq

        mock_orchestrator = Mock()
        mock_orchestrator_class.return_value = mock_orchestrator

        # Success result from orchestrator
        success_result = {
            "run_id": "test-run-id",
            "source_name": "openaq",
            "status": "success",
            "records_received": 1200,
            "records_written": 1180,
            "records_rejected": 20,
            "duration_seconds": 45.2,
        }
        mock_orchestrator.ingest_source.return_value = success_result

        # Call should complete without exception
        result = ingest_openaq(**mock_context)

        # Verify result is returned unchanged
        assert result == success_result
        assert result["status"] == "success"
        assert result["records_written"] == 1180

        # Verify XCom was pushed with records count
        mock_context["task_instance"].xcom_push.assert_called_once_with(
            key="openaq_records", value=1180
        )

    @patch("dags.aq_hourly_ingest_dag.IngestionOrchestrator")
    def test_successful_weather_ingestion_completes_normally(
        self, mock_orchestrator_class, mock_context
    ):
        """Test successful weather ingestion completes without exception."""
        from dags.aq_hourly_ingest_dag import ingest_weather

        mock_orchestrator = Mock()
        mock_orchestrator_class.return_value = mock_orchestrator

        success_result = {
            "run_id": "test-run-id",
            "source_name": "open_meteo",
            "status": "success",
            "records_received": 450,
            "records_written": 450,
            "records_rejected": 0,
            "duration_seconds": 30.1,
        }
        mock_orchestrator.ingest_source.return_value = success_result

        result = ingest_weather(**mock_context)

        assert result == success_result
        assert result["status"] == "success"

    @patch("dags.aq_hourly_ingest_dag.IngestionOrchestrator")
    def test_ingestion_failed_status_raises_airflow_exception(
        self, mock_orchestrator_class, mock_context
    ):
        """Test that result with status='failed' raises AirflowException.

        This is critical: if orchestrator returns a failed result (without raising),
        we must explicitly raise AirflowException so Airflow marks the task FAILED.
        """
        from dags.aq_hourly_ingest_dag import ingest_openaq

        mock_orchestrator = Mock()
        mock_orchestrator_class.return_value = mock_orchestrator

        # Failed result (orchestrator might return without raising in some cases)
        failed_result = {
            "run_id": "test-run-id",
            "source_name": "openaq",
            "status": "failed",
            "records_received": 1200,
            "records_written": 0,
            "records_rejected": 1200,
            "error_message": "API rate limit exceeded",
            "duration_seconds": 5.0,
        }
        mock_orchestrator.ingest_source.return_value = failed_result

        # Should raise AirflowException with error details
        with pytest.raises(AirflowException) as exc_info:
            ingest_openaq(**mock_context)

        assert "failed" in str(exc_info.value).lower()
        assert "rate limit" in str(exc_info.value).lower()

    @patch("dags.aq_hourly_ingest_dag.IngestionOrchestrator")
    def test_ingestion_failed_exception_propagates_as_airflow_exception(
        self, mock_orchestrator_class, mock_context
    ):
        """Test that IngestionFailed exception propagates as AirflowException.

        This is the main failure path: when orchestrator raises IngestionFailed,
        we must catch it and re-raise as AirflowException for Airflow to handle.
        """
        from dags.aq_hourly_ingest_dag import ingest_openaq

        mock_orchestrator = Mock()
        mock_orchestrator_class.return_value = mock_orchestrator

        # Orchestrator raises IngestionFailed on critical errors
        ingestion_error = IngestionFailed(
            "API error: service unavailable",
            context={"source": "openaq", "run_id": "test-run-id"},
        )
        mock_orchestrator.ingest_source.side_effect = ingestion_error

        # Should raise AirflowException (not IngestionFailed)
        with pytest.raises(AirflowException) as exc_info:
            ingest_openaq(**mock_context)

        assert "API error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, IngestionFailed)

    @patch("dags.aq_hourly_ingest_dag.IngestionOrchestrator")
    def test_ingestion_unexpected_exception_converted_to_airflow_exception(
        self, mock_orchestrator_class, mock_context
    ):
        """Test that unexpected exceptions are converted to AirflowException.

        Ensures that any exception from orchestrator (not just IngestionFailed)
        is properly propagated to Airflow.
        """
        from dags.aq_hourly_ingest_dag import ingest_openaq

        mock_orchestrator = Mock()
        mock_orchestrator_class.return_value = mock_orchestrator

        # Unexpected error
        mock_orchestrator.ingest_source.side_effect = ValueError("Invalid config")

        # Should raise AirflowException
        with pytest.raises(AirflowException) as exc_info:
            ingest_openaq(**mock_context)

        assert "Invalid config" in str(exc_info.value)

    @patch("dags.aq_hourly_ingest_dag.IngestionOrchestrator")
    def test_weather_ingestion_failure_propagates(
        self, mock_orchestrator_class, mock_context
    ):
        """Test weather ingestion also propagates failures properly."""
        from dags.aq_hourly_ingest_dag import ingest_weather

        mock_orchestrator = Mock()
        mock_orchestrator_class.return_value = mock_orchestrator

        ingestion_error = IngestionFailed(
            "Weather API timeout",
            context={"source": "open_meteo", "run_id": "test-run-id"},
        )
        mock_orchestrator.ingest_source.side_effect = ingestion_error

        with pytest.raises(AirflowException) as exc_info:
            ingest_weather(**mock_context)

        assert "timeout" in str(exc_info.value).lower()


class TestAirflowFailureRecovery:
    """Test Airflow retry and failure handling with ingestion failures."""

    @patch("dags.aq_hourly_ingest_dag.IngestionOrchestrator")
    def test_airflow_can_retry_on_ingestion_failure(
        self, mock_orchestrator_class, mock_context
    ):
        """Test that Airflow can retry task when AirflowException is raised.

        This verifies that our AirflowException is properly configured for Airflow
        to see it as a retriable failure (not a permanent error).
        """
        from dags.aq_hourly_ingest_dag import ingest_openaq

        mock_orchestrator = Mock()
        mock_orchestrator_class.return_value = mock_orchestrator

        # Simulate transient failure
        mock_orchestrator.ingest_source.side_effect = IngestionFailed(
            "Temporary network issue"
        )

        # Raise AirflowException (which Airflow can retry)
        with pytest.raises(AirflowException):
            ingest_openaq(**mock_context)

        # On retry (if configured), next attempt could succeed
        mock_orchestrator.ingest_source.side_effect = None
        mock_orchestrator.ingest_source.return_value = {
            "run_id": "retry-run-id",
            "source_name": "openaq",
            "status": "success",
            "records_written": 1200,
            "records_received": 1200,
        }

        # Retry succeeds
        result = ingest_openaq(**mock_context)
        assert result["status"] == "success"

    def test_airflow_exception_class_is_used(self, mock_context):
        """Verify AirflowException is the proper Airflow exception class."""
        from airflow.exceptions import AirflowException as AirflowExceptionClass

        from dags.aq_hourly_ingest_dag import ingest_openaq

        with patch("dags.aq_hourly_ingest_dag.IngestionOrchestrator") as mock_orch:
            mock_orch.return_value.ingest_source.side_effect = Exception("Test")

            with pytest.raises(AirflowExceptionClass):
                ingest_openaq(**mock_context)
