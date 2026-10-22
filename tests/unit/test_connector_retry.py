"""Regression tests for retry handling of wrapped connector errors."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import requests

from aq_engine.common import IngestionFailed
from aq_engine.connectors.base import BaseConnector
from aq_engine.connectors.models import ConnectorConfig, RetryConfig


class _FailingConnector(BaseConnector):
    def __init__(self, error):
        super().__init__(
            ConnectorConfig(
                source_name="test",
                source_type="air_quality",
                base_url="https://example.test",
                retry=RetryConfig(max_attempts=1, delays_seconds=[0.0]),
            )
        )
        self.error = error
        self.fetch_calls = 0

    def fetch(self, start_time, end_time):
        self.fetch_calls += 1
        raise self.error

    def parse(self, response, start_time, end_time):
        return []

    def write_raw(self, records, run_id):
        return 0, 0

    def record_run(self, metadata, success):
        pass


def _run(connector):
    now = datetime.now(timezone.utc)
    with patch.object(connector, "_get_retry_delay", return_value=0.0):
        with pytest.raises(IngestionFailed):
            connector._fetch_with_retry(now, now)


def test_wrapped_connection_error_is_retried():
    try:
        raise requests.ConnectionError("connection reset")
    except requests.ConnectionError as cause:
        error = IngestionFailed("fetch failed", context={"source": "test"})
        error.__cause__ = cause

    connector = _FailingConnector(error)
    _run(connector)

    assert connector.fetch_calls == 2


def test_wrapped_transient_status_is_retried():
    connector = _FailingConnector(
        IngestionFailed("server error", context={"status_code": 503})
    )
    _run(connector)

    assert connector.fetch_calls == 2


def test_permanent_status_is_not_retried():
    connector = _FailingConnector(
        IngestionFailed("unauthorized", context={"status_code": 401})
    )
    _run(connector)

    assert connector.fetch_calls == 1
