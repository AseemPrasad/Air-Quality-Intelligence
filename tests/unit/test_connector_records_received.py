"""Regression test for ingestion run record counts."""

from datetime import datetime, timezone

from aq_engine.connectors.base import BaseConnector
from aq_engine.connectors.models import (
    ConnectorConfig,
    IngestionRunMetadata,
    SourceResponse,
)


class _CountingConnector(BaseConnector):
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
            body={"results": [1, 2, 3]},
            elapsed_seconds=0.0,
            timestamp=datetime.now(timezone.utc),
        )

    def parse(self, response, start_time, end_time):
        return [object(), object(), object()]

    def write_raw(self, records, run_id):
        return len(records), 0

    def record_run(self, metadata: IngestionRunMetadata, success: bool):
        self.saved_metadata.append(metadata)


def test_records_received_matches_parsed_record_count():
    connector = _CountingConnector()
    end = datetime.now(timezone.utc)

    _, metadata = connector.ingest(
        start_time=end.replace(minute=0, second=0, microsecond=0),
        end_time=end,
    )

    assert metadata.records_received == 3
    assert connector.saved_metadata[0].records_received == 3
