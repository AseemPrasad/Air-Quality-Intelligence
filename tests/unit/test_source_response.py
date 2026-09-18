"""Tests for SourceResponse payload hashing."""

from datetime import date, datetime, timezone

import pytest
from aq_engine.connectors.models import SourceResponse


def _response(body):
    return SourceResponse(
        status_code=200,
        headers={},
        body=body,
        elapsed_seconds=0.0,
        timestamp=datetime(2026, 8, 15, tzinfo=timezone.utc),
    )


def test_hashes_body_containing_datetimes():
    """Open-Meteo builds its body from parsed records whose observed_at is a datetime."""
    body = {
        "results": [
            {
                "observed_at": datetime(2026, 8, 15, 12, tzinfo=timezone.utc),
                "value": 1.0,
            }
        ],
        "meta": {"total": 1, "day": date(2026, 8, 15)},
    }

    response = _response(body)

    assert response.raw_payload_hash is not None
    assert len(response.raw_payload_hash) == 64


def test_hash_is_stable_and_distinguishes_timestamps():
    first = _response({"observed_at": datetime(2026, 8, 15, 12, tzinfo=timezone.utc)})
    same = _response({"observed_at": datetime(2026, 8, 15, 12, tzinfo=timezone.utc)})
    later = _response({"observed_at": datetime(2026, 8, 15, 13, tzinfo=timezone.utc)})

    assert first.raw_payload_hash == same.raw_payload_hash
    assert first.raw_payload_hash != later.raw_payload_hash


def test_still_rejects_other_unserialisable_values():
    with pytest.raises(TypeError):
        _response({"value": object()})
