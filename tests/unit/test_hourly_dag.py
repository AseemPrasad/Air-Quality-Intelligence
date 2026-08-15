"""Tests for hourly Air Quality ingestion DAG."""

import pytest
from datetime import datetime

# Import Airflow modules, skip tests if not installed
pytest.importorskip("airflow")
from airflow.models import DAG
from airflow.operators.dummy import DummyOperator
from airflow.operators.python import PythonOperator


@pytest.fixture
def dag():
    """Load the hourly ingestion DAG."""
    # Import the DAG - this tests that it loads without error
    from dags.aq_hourly_ingest_dag import dag as test_dag

    return test_dag


class TestDAGStructure:
    """Test DAG structure and configuration."""

    def test_dag_loads(self, dag):
        """Test DAG loads without error."""
        assert dag is not None
        assert isinstance(dag, DAG)

    def test_dag_id(self, dag):
        """Test DAG has correct ID."""
        assert dag.dag_id == "aq_hourly_ingest"

    def test_dag_schedule(self, dag):
        """Test DAG has hourly schedule."""
        assert dag.schedule_interval == "0 * * * *"

    def test_dag_owner(self, dag):
        """Test DAG has correct owner."""
        assert dag.owner == "aq_engine"

    def test_dag_retries(self, dag):
        """Test DAG has correct retry configuration."""
        assert dag.default_args["retries"] == 2

    def test_dag_retry_delay(self, dag):
        """Test DAG has correct retry delay."""
        from datetime import timedelta

        expected_delay = timedelta(minutes=5)
        assert dag.default_args["retry_delay"] == expected_delay

    def test_dag_catchup_disabled(self, dag):
        """Test catchup is disabled (prevents backfill)."""
        assert dag.catchup is False

    def test_dag_max_active_runs(self, dag):
        """Test only one run at a time."""
        assert dag.max_active_runs == 1

    def test_dag_has_tags(self, dag):
        """Test DAG has meaningful tags."""
        tags = dag.tags
        assert "air_quality" in tags
        assert "ingestion" in tags
        assert "hourly" in tags


class TestDAGTasks:
    """Test DAG tasks."""

    def test_dag_has_all_tasks(self, dag):
        """Test all expected tasks are present."""
        task_ids = dag.task_ids

        expected_tasks = [
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

        for task_id in expected_tasks:
            assert task_id in task_ids, f"Task {task_id} not found"

    def test_task_count(self, dag):
        """Test DAG has correct number of tasks."""
        assert len(dag.task_ids) == 14

    def test_start_task_is_dummy(self, dag):
        """Test start task is dummy operator."""
        start_task = dag.get_task("start")
        assert isinstance(start_task, DummyOperator)

    def test_end_task_is_dummy(self, dag):
        """Test end task is dummy operator."""
        end_task = dag.get_task("end")
        assert isinstance(end_task, DummyOperator)

    def test_ingest_openaq_is_python(self, dag):
        """Test ingest_openaq is Python operator."""
        task = dag.get_task("ingest_openaq")
        assert isinstance(task, PythonOperator)

    def test_ingest_weather_is_python(self, dag):
        """Test ingest_weather is Python operator."""
        task = dag.get_task("ingest_weather")
        assert isinstance(task, PythonOperator)

    def test_validate_raw_is_python(self, dag):
        """Test validate_raw is Python operator."""
        task = dag.get_task("validate_raw")
        assert isinstance(task, PythonOperator)

    def test_dedup_quality_is_python(self, dag):
        """Test dedup_quality is Python operator."""
        task = dag.get_task("dedup_quality")
        assert isinstance(task, PythonOperator)

    def test_hourly_aggregate_is_python(self, dag):
        """Test hourly_aggregate is Python operator."""
        task = dag.get_task("hourly_aggregate")
        assert isinstance(task, PythonOperator)

    def test_compute_baselines_is_python(self, dag):
        """Test compute_baselines is Python operator."""
        task = dag.get_task("compute_baselines")
        assert isinstance(task, PythonOperator)

    def test_detect_anomalies_is_python(self, dag):
        """Test detect_anomalies is Python operator."""
        task = dag.get_task("detect_anomalies")
        assert isinstance(task, PythonOperator)

    def test_detect_events_is_python(self, dag):
        """Test detect_events is Python operator."""
        task = dag.get_task("detect_events")
        assert isinstance(task, PythonOperator)

    def test_generate_features_is_python(self, dag):
        """Test generate_features is Python operator."""
        task = dag.get_task("generate_features")
        assert isinstance(task, PythonOperator)

    def test_predict_is_python(self, dag):
        """Test predict is Python operator."""
        task = dag.get_task("predict")
        assert isinstance(task, PythonOperator)

    def test_evaluate_predictions_is_python(self, dag):
        """Test evaluate_predictions is Python operator."""
        task = dag.get_task("evaluate_predictions")
        assert isinstance(task, PythonOperator)

    def test_publish_marts_is_python(self, dag):
        """Test publish_marts is Python operator."""
        task = dag.get_task("publish_marts")
        assert isinstance(task, PythonOperator)


class TestDAGDependencies:
    """Test task dependencies."""

    def test_no_circular_dependencies(self, dag):
        """Test DAG has no circular dependencies."""
        # This should not raise an exception
        assert dag.is_dag_valid()

    def test_start_has_downstream(self, dag):
        """Test start task has downstream task."""
        start_task = dag.get_task("start")
        assert len(start_task.downstream_list) == 1
        assert start_task.downstream_list[0].task_id == "ingest_openaq"

    def test_ingest_openaq_depends_on_start(self, dag):
        """Test ingest_openaq depends on start."""
        task = dag.get_task("ingest_openaq")
        upstream_ids = [t.task_id for t in task.upstream_list]
        assert "start" in upstream_ids

    def test_ingest_openaq_upstream_to_weather(self, dag):
        """Test ingest_openaq is upstream to ingest_weather."""
        openaq_task = dag.get_task("ingest_openaq")
        downstream_ids = [t.task_id for t in openaq_task.downstream_list]
        assert "ingest_weather" in downstream_ids

    def test_ingest_weather_depends_on_openaq(self, dag):
        """Test ingest_weather depends on ingest_openaq."""
        task = dag.get_task("ingest_weather")
        upstream_ids = [t.task_id for t in task.upstream_list]
        assert "ingest_openaq" in upstream_ids

    def test_validate_raw_downstream_of_weather(self, dag):
        """Test validate_raw comes after weather ingestion."""
        task = dag.get_task("validate_raw")
        upstream_ids = [t.task_id for t in task.upstream_list]
        assert "ingest_weather" in upstream_ids

    def test_linear_pipeline_order(self, dag):
        """Test tasks are in expected linear order."""
        task_order = [
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

        for i in range(len(task_order) - 1):
            current_task = dag.get_task(task_order[i])
            next_task = dag.get_task(task_order[i + 1])

            downstream_ids = [t.task_id for t in current_task.downstream_list]
            assert next_task.task_id in downstream_ids

    def test_end_task_has_no_downstream(self, dag):
        """Test end task has no downstream tasks."""
        end_task = dag.get_task("end")
        assert len(end_task.downstream_list) == 0

    def test_end_task_has_upstream(self, dag):
        """Test end task has upstream task."""
        end_task = dag.get_task("end")
        upstream_ids = [t.task_id for t in end_task.upstream_list]
        assert "publish_marts" in upstream_ids


class TestDAGTaskProperties:
    """Test individual task properties."""

    def test_all_tasks_have_owner(self, dag):
        """Test all tasks inherit owner from DAG."""
        for task_id in dag.task_ids:
            task = dag.get_task(task_id)
            assert task.owner == "aq_engine"

    def test_all_tasks_have_retries(self, dag):
        """Test all tasks have retry configuration."""
        for task_id in dag.task_ids:
            task = dag.get_task(task_id)
            # Note: dummy operators may not have retries set
            if isinstance(task, PythonOperator):
                assert task.retries == 2

    def test_python_tasks_have_callable(self, dag):
        """Test all Python tasks have callable function."""
        python_task_ids = [
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
        ]

        for task_id in python_task_ids:
            task = dag.get_task(task_id)
            assert task.python_callable is not None


class TestDAGIntegration:
    """Test DAG integration scenarios."""

    def test_task_count_matches_defined(self, dag):
        """Test task count matches implementation."""
        assert len(dag.task_ids) == 14

    def test_all_task_ids_unique(self, dag):
        """Test all task IDs are unique."""
        task_ids = dag.task_ids
        assert len(task_ids) == len(set(task_ids))

    def test_dag_can_be_serialized(self, dag):
        """Test DAG can be serialized (Airflow 2.0 requirement)."""
        # This is tested implicitly by DAG loading
        assert dag.serialize()

    def test_task_graph_acyclic(self, dag):
        """Test task graph is acyclic (no cycles)."""
        # Using topological sort to verify no cycles
        visited = set()
        rec_stack = set()

        def has_cycle(node, visited, rec_stack, adj_list):
            """Check for cycle using DFS."""
            visited.add(node)
            rec_stack.add(node)

            for neighbor in adj_list.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor, visited, rec_stack, adj_list):
                        return True
                elif neighbor in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        # Build adjacency list
        adj_list = {}
        for task_id in dag.task_ids:
            task = dag.get_task(task_id)
            downstream = [t.task_id for t in task.downstream_list]
            adj_list[task_id] = downstream

        # Check for cycles
        for task_id in dag.task_ids:
            if task_id not in visited:
                assert not has_cycle(task_id, visited, rec_stack, adj_list)

    def test_critical_path_exists(self, dag):
        """Test there is a clear critical path from start to end."""
        # Start should reach end
        start_task = dag.get_task("start")

        # Traverse to find end
        visited = set()
        queue = list(start_task.downstream_list)
        found_end = False

        while queue:
            task = queue.pop(0)
            if task.task_id in visited:
                continue
            visited.add(task.task_id)

            if task.task_id == "end":
                found_end = True
                break

            queue.extend(task.downstream_list)

        assert found_end, "End task not reachable from start"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
