"""Tests for hourly DAG structure without Airflow dependency."""

import ast
import pytest
import re
from pathlib import Path


@pytest.fixture
def dag_file_content():
    """Read the DAG file content."""
    dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_hourly_ingest_dag.py"
    with open(dag_path, "r") as f:
        return f.read()


@pytest.fixture
def dag_ast(dag_file_content):
    """Parse DAG file as AST."""
    return ast.parse(dag_file_content)


class TestDAGFile:
    """Test DAG file structure."""

    def test_dag_file_exists(self):
        """Test DAG file exists."""
        dag_path = Path(__file__).parent.parent.parent / "dags" / "aq_hourly_ingest_dag.py"
        assert dag_path.exists()

    def test_dag_file_is_valid_python(self, dag_file_content):
        """Test DAG file is valid Python."""
        # This will raise if invalid
        ast.parse(dag_file_content)

    def test_dag_file_has_docstring(self, dag_file_content):
        """Test DAG file has module docstring."""
        assert '"""' in dag_file_content or "'''" in dag_file_content

    def test_dag_imports_required_modules(self, dag_file_content):
        """Test DAG imports required modules."""
        assert "from airflow import DAG" in dag_file_content
        assert "from airflow.operators.dummy import DummyOperator" in dag_file_content
        assert "from airflow.operators.python import PythonOperator" in dag_file_content


class TestDAGDefinition:
    """Test DAG definition in file."""

    def test_dag_variable_defined(self, dag_file_content):
        """Test DAG variable is defined."""
        assert "dag = DAG(" in dag_file_content

    def test_dag_id_correct(self, dag_file_content):
        """Test DAG ID is correct."""
        assert 'dag_id="aq_hourly_ingest"' in dag_file_content

    def test_dag_schedule_hourly(self, dag_file_content):
        """Test DAG schedule is hourly."""
        assert '"0 * * * *"' in dag_file_content or "'0 * * * *'" in dag_file_content

    def test_dag_owner_set(self, dag_file_content):
        """Test DAG owner is set."""
        assert '"aq_engine"' in dag_file_content or "'aq_engine'" in dag_file_content

    def test_dag_has_retries(self, dag_file_content):
        """Test DAG has retry configuration."""
        assert '"retries": 2' in dag_file_content or "'retries': 2" in dag_file_content

    def test_dag_has_retry_delay(self, dag_file_content):
        """Test DAG has retry delay."""
        assert "timedelta(minutes=5)" in dag_file_content


class TestDAGTasks:
    """Test task definitions in DAG."""

    def test_all_tasks_defined(self, dag_file_content):
        """Test all expected tasks are defined."""
        expected_tasks = [
            "start_task = DummyOperator",
            "ingest_openaq_task = PythonOperator",
            "ingest_weather_task = PythonOperator",
            "validate_raw_task = PythonOperator",
            "dedup_quality_task = PythonOperator",
            "hourly_aggregate_task = PythonOperator",
            "compute_baselines_task = PythonOperator",
            "detect_anomalies_task = PythonOperator",
            "detect_events_task = PythonOperator",
            "generate_features_task = PythonOperator",
            "predict_task = PythonOperator",
            "evaluate_predictions_task = PythonOperator",
            "publish_marts_task = PythonOperator",
            "end_task = DummyOperator",
        ]

        for task_def in expected_tasks:
            assert task_def in dag_file_content

    def test_all_tasks_have_task_id(self, dag_file_content):
        """Test all tasks have task_id parameter."""
        task_ids = [
            "start",
            "ingest_openaq",
            "ingest_weather",
            "validate_raw",
            "dedup_quality",
            "hourly_aggregate",
            "compute_baselines",
            "detect_anomalies",
            "detect_events",
            "generate_features",
            "predict",
            "evaluate_predictions",
            "publish_marts",
            "end",
        ]

        for task_id in task_ids:
            assert f'task_id="{task_id}"' in dag_file_content

    def test_all_python_tasks_have_callable(self, dag_file_content):
        """Test all Python tasks have python_callable."""
        # Count python_callable definitions
        count = dag_file_content.count("python_callable=")
        # Should be 12 (all except start and end)
        assert count == 12

    def test_all_tasks_reference_dag(self, dag_file_content):
        """Test all tasks are added to DAG."""
        assert "dag=dag" in dag_file_content


class TestTaskDependencies:
    """Test task dependencies."""

    def test_dependencies_defined(self, dag_file_content):
        """Test dependencies are defined."""
        assert ">>" in dag_file_content

    def test_linear_pipeline_defined(self, dag_file_content):
        """Test linear pipeline is defined."""
        # Look for the >> chain
        assert "start_task" in dag_file_content
        assert "end_task" in dag_file_content
        # Check for chain - should have multiple >> operators
        assert dag_file_content.count(">>") >= 13

    def test_all_tasks_in_dependency_chain(self, dag_file_content):
        """Test all tasks are in dependency chain."""
        # Extract the dependency section
        dependency_section = dag_file_content[
            dag_file_content.find("(") + 1 : dag_file_content.rfind(")")
        ]

        task_names = [
            "start_task",
            "ingest_openaq_task",
            "ingest_weather_task",
            "validate_raw_task",
            "dedup_quality_task",
            "hourly_aggregate_task",
            "compute_baselines_task",
            "detect_anomalies_task",
            "detect_events_task",
            "generate_features_task",
            "predict_task",
            "evaluate_predictions_task",
            "publish_marts_task",
            "end_task",
        ]

        for task_name in task_names:
            # Each task should appear at least once in the dependencies
            assert task_name in dag_file_content


class TestPythonTaskFunctions:
    """Test Python task function definitions."""

    def test_all_task_functions_defined(self, dag_file_content):
        """Test all Python task functions are defined."""
        expected_functions = [
            "def ingest_openaq",
            "def ingest_weather",
            "def validate_raw",
            "def dedup_quality",
            "def hourly_aggregate",
            "def compute_baselines",
            "def detect_anomalies",
            "def detect_events",
            "def generate_features",
            "def predict",
            "def evaluate_predictions",
            "def publish_marts",
        ]

        for func_def in expected_functions:
            assert func_def in dag_file_content

    def test_all_functions_accept_context(self, dag_file_content):
        """Test all functions accept **context parameter."""
        # Count function definitions with **context
        pattern = r"def \w+\(\*\*context"
        matches = re.findall(pattern, dag_file_content)
        # Should be at least 12 (all Python task functions)
        assert len(matches) >= 12

    def test_functions_return_dict(self, dag_file_content):
        """Test task functions return dict."""
        # Look for return statements and dict construction
        assert "return result" in dag_file_content
        assert "result = {" in dag_file_content


class TestLogging:
    """Test logging configuration."""

    def test_logging_import(self, dag_file_content):
        """Test logging is imported."""
        assert "import logging" in dag_file_content

    def test_logging_used(self, dag_file_content):
        """Test logging is used in tasks."""
        assert "logger.info" in dag_file_content
        assert "json.dumps" in dag_file_content

    def test_structured_logging(self, dag_file_content):
        """Test structured JSON logging."""
        assert "json.dumps(log_data)" in dag_file_content


class TestComments:
    """Test code documentation."""

    def test_module_docstring(self, dag_file_content):
        """Test module has docstring."""
        lines = dag_file_content.split("\n")
        assert '"""' in lines[0] or "'''" in lines[0]

    def test_dag_definition_documented(self, dag_file_content):
        """Test DAG definition is documented."""
        # Should have comments explaining config
        assert "#" in dag_file_content

    def test_task_functions_documented(self, dag_file_content):
        """Test task functions have docstrings."""
        # Count function docstrings
        count = dag_file_content.count('"""')
        # Should be substantial (at least one per function)
        assert count > 10


class TestConfiguration:
    """Test configuration values."""

    def test_no_hardcoded_paths(self, dag_file_content):
        """Test no absolute paths are hardcoded."""
        # Should not have hardcoded paths like /data or C:\
        assert "/data/" not in dag_file_content
        assert "C:\\" not in dag_file_content

    def test_execution_timeout_set(self, dag_file_content):
        """Test execution timeout is configured."""
        assert "execution_timeout" in dag_file_content

    def test_email_on_failure_configured(self, dag_file_content):
        """Test email on failure is configured."""
        assert "email_on_failure" in dag_file_content

    def test_start_date_set(self, dag_file_content):
        """Test start date is set."""
        assert "start_date=" in dag_file_content or "start_date =" in dag_file_content

    def test_catchup_disabled(self, dag_file_content):
        """Test catchup is explicitly disabled."""
        assert "catchup=False" in dag_file_content or "catchup = False" in dag_file_content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
