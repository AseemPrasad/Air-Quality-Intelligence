"""Regression test for finalized ingestion run metadata."""

from datetime import datetime, timezone

from aq_engine.connectors.base import BaseConnector
from aq_engine.connectors.models import (
    ConnectorConfig,
    IngestionRunMetadata,
    SourceResponse,
)


class _RecordingConnector(BaseConnector):
    def __init__(self):
        super().__init__(
            ConnectorConfig(
                source_name="test",
                source_type="air_quality",
                base_url="https://example.test",
            )
        )
        self.saved_metadata = []

    def fetch(self, start_time, end_time):
        return SourceResponse(
            status_code=200,
            headers={},
            body={},
            elapsed_seconds=0.0,
            timestamp=datetime.now(timezone.utc),
        )

    def parse(self, response, start_time, end_time):
        return [object()]

    def write_raw(self, records, run_id):
        return 1, 0

    def record_run(self, metadata: IngestionRunMetadata, success: bool):
        self.saved_metadata.append(metadata)


def test_successful_run_is_persisted_after_metadata_is_finalized():
    connector = _RecordingConnector()
    now = datetime.now(timezone.utc)

    _, returned = connector.ingest(
        start_time=now.replace(minute=0, second=0, microsecond=0),
        end_time=now,
    )

    saved = connector.saved_metadata[0]
    assert saved.status == "success"
    assert saved.finished_at is not None
    assert saved.is_complete()
    assert returned.status == "success"
