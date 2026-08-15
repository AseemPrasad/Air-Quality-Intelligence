"""Unit tests for pollution event detection and merging logic.

Tests event detection algorithms, severity classification, and event merging.
"""

import pytest
from datetime import datetime, timezone, timedelta
import uuid

from aq_engine.analytics.events import EventDetector


@pytest.fixture
def detector():
    """EventDetector instance."""
    return EventDetector()


@pytest.fixture
def sample_anomalies():
    """Sample anomalies for testing."""
    base_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
    return [
        {
            "location_id": "kolkata",
            "pollutant": "pm25",
            "hour_start": base_time,
            "observed_value": 150.0,
            "robust_z": 3.5,
            "severity": "HIGH",
        },
        {
            "location_id": "kolkata",
            "pollutant": "pm25",
            "hour_start": base_time + timedelta(hours=1),
            "observed_value": 160.0,
            "robust_z": 4.0,
            "severity": "SEVERE",
        },
        {
            "location_id": "kolkata",
            "pollutant": "pm25",
            "hour_start": base_time + timedelta(hours=2),
            "observed_value": 155.0,
            "robust_z": 3.8,
            "severity": "HIGH",
        },
    ]


class TestEventDetection:
    """Test basic event detection."""

    def test_three_consecutive_high_anomalies_creates_event(
        self, detector, sample_anomalies
    ):
        """Test 3 consecutive HIGH anomalies create 1 event."""
        events = detector.detect_events(sample_anomalies)

        assert len(events) == 1
        event = events[0]
        assert event["location_id"] == "kolkata"
        assert event["pollutant"] == "pm25"
        assert event["anomaly_count"] == 3
        assert event["severity"] == "SEVERE"  # Highest severity in event
        assert event["duration_hours"] == 3  # 3 hours from first to last

    def test_three_anomalies_in_4h_window_creates_event(self, detector):
        """Test 3 anomalies in 4-hour window (non-consecutive) create 1 event."""
        base_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        anomalies = [
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time,
                "observed_value": 150.0,
                "robust_z": 3.5,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=2),  # Gap at hour 1
                "observed_value": 160.0,
                "robust_z": 4.0,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=3),  # Within 4h window
                "observed_value": 155.0,
                "robust_z": 3.8,
                "severity": "HIGH",
            },
        ]

        events = detector.detect_events(anomalies)

        assert len(events) == 1
        event = events[0]
        assert event["anomaly_count"] == 3
        assert event["duration_hours"] == 4

    def test_two_high_anomalies_no_event(self, detector):
        """Test only 2 HIGH anomalies don't create event (need 3)."""
        base_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        anomalies = [
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time,
                "observed_value": 150.0,
                "robust_z": 3.5,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=1),
                "observed_value": 160.0,
                "robust_z": 4.0,
                "severity": "HIGH",
            },
        ]

        events = detector.detect_events(anomalies)

        assert len(events) == 0

    def test_elevated_anomalies_below_threshold(self, detector):
        """Test ELEVATED anomalies don't create event."""
        base_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        anomalies = [
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time,
                "observed_value": 100.0,
                "robust_z": 2.5,
                "severity": "ELEVATED",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=1),
                "observed_value": 105.0,
                "robust_z": 2.7,
                "severity": "ELEVATED",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=2),
                "observed_value": 102.0,
                "robust_z": 2.6,
                "severity": "ELEVATED",
            },
        ]

        events = detector.detect_events(anomalies)

        assert len(events) == 0

    def test_empty_anomaly_list(self, detector):
        """Test empty anomaly list returns no events."""
        events = detector.detect_events([])

        assert events == []

    def test_no_high_anomalies(self, detector):
        """Test no HIGH+ anomalies returns no events."""
        base_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        anomalies = [
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time,
                "observed_value": 50.0,
                "robust_z": 1.0,
                "severity": "NORMAL",
            },
        ]

        events = detector.detect_events(anomalies)

        assert len(events) == 0


class TestEventStatistics:
    """Test event statistics calculation."""

    def test_peak_value_calculation(self, detector, sample_anomalies):
        """Test peak value is max of anomalies."""
        events = detector.detect_events(sample_anomalies)

        assert len(events) == 1
        event = events[0]
        assert event["peak_value"] == 160.0

    def test_mean_value_calculation(self, detector, sample_anomalies):
        """Test mean value is average of anomalies."""
        events = detector.detect_events(sample_anomalies)

        assert len(events) == 1
        event = events[0]
        expected_mean = (150.0 + 160.0 + 155.0) / 3
        assert pytest.approx(event["mean_value"], abs=0.1) == expected_mean

    def test_peak_anomaly_score_calculation(self, detector, sample_anomalies):
        """Test peak anomaly score is max |robust_z|."""
        events = detector.detect_events(sample_anomalies)

        assert len(events) == 1
        event = events[0]
        assert event["peak_anomaly_score"] == 4.0  # Max of 3.5, 4.0, 3.8

    def test_duration_calculation(self, detector, sample_anomalies):
        """Test duration is calculated in hours."""
        events = detector.detect_events(sample_anomalies)

        assert len(events) == 1
        event = events[0]
        # From hour 0 to hour 2, duration = 3 (inclusive)
        assert event["duration_hours"] == 3

    def test_severity_is_highest_in_event(self, detector):
        """Test event severity is highest among anomalies."""
        base_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        anomalies = [
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time,
                "observed_value": 150.0,
                "robust_z": 3.5,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=1),
                "observed_value": 200.0,
                "robust_z": 6.0,
                "severity": "EXTREME",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=2),
                "observed_value": 155.0,
                "robust_z": 3.8,
                "severity": "HIGH",
            },
        ]

        events = detector.detect_events(anomalies)

        assert events[0]["severity"] == "EXTREME"


class TestEventMerging:
    """Test event merging logic."""

    def test_events_30_min_apart_merge(self, detector):
        """Test two events 30 min apart merge into 1."""
        base_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        anomalies = [
            # First event: hour 0, 1, 2
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time,
                "observed_value": 150.0,
                "robust_z": 3.5,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=1),
                "observed_value": 160.0,
                "robust_z": 4.0,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=2),
                "observed_value": 155.0,
                "robust_z": 3.8,
                "severity": "HIGH",
            },
            # Gap: 30 minutes (< 1 hour threshold)
            # Second event: hour 2.5, 3.5, 4.5 (gap from hour 2)
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=2, minutes=30),
                "observed_value": 145.0,
                "robust_z": 3.2,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=3, minutes=30),
                "observed_value": 170.0,
                "robust_z": 4.1,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=4, minutes=30),
                "observed_value": 152.0,
                "robust_z": 3.6,
                "severity": "HIGH",
            },
        ]

        events = detector.detect_events(anomalies)

        # Should be 1 merged event
        assert len(events) == 1
        event = events[0]
        assert event["anomaly_count"] == 6  # All 6 anomalies merged
        assert event["peak_value"] == 170.0  # Max from both events
        assert event["severity"] == "HIGH"

    def test_events_90_min_apart_no_merge(self, detector):
        """Test two events 90 min apart stay separate."""
        base_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        anomalies = [
            # First event: hours 0, 1, 2
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time,
                "observed_value": 150.0,
                "robust_z": 3.5,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=1),
                "observed_value": 160.0,
                "robust_z": 4.0,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=2),
                "observed_value": 155.0,
                "robust_z": 3.8,
                "severity": "HIGH",
            },
            # Gap: 1.5 hours (> 1 hour threshold)
            # Second event: hours 3.5, 4.5, 5.5
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=3, minutes=30),
                "observed_value": 145.0,
                "robust_z": 3.2,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=4, minutes=30),
                "observed_value": 170.0,
                "robust_z": 4.1,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=5, minutes=30),
                "observed_value": 152.0,
                "robust_z": 3.6,
                "severity": "HIGH",
            },
        ]

        events = detector.detect_events(anomalies)

        # Should be 2 separate events
        assert len(events) == 2
        assert events[0]["anomaly_count"] == 3
        assert events[1]["anomaly_count"] == 3

    def test_events_exactly_1_hour_apart_merge(self, detector):
        """Test events exactly 1 hour apart (boundary) merge."""
        base_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        anomalies = [
            # First event: hours 0, 1, 2
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time,
                "observed_value": 150.0,
                "robust_z": 3.5,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=1),
                "observed_value": 160.0,
                "robust_z": 4.0,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=2),
                "observed_value": 155.0,
                "robust_z": 3.8,
                "severity": "HIGH",
            },
            # Gap: exactly 1 hour
            # Second event: hours 3, 4, 5
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=3),
                "observed_value": 145.0,
                "robust_z": 3.2,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=4),
                "observed_value": 170.0,
                "robust_z": 4.1,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=5),
                "observed_value": 152.0,
                "robust_z": 3.6,
                "severity": "HIGH",
            },
        ]

        events = detector.detect_events(anomalies)

        # Should merge (<=1 hour)
        assert len(events) == 1
        assert events[0]["anomaly_count"] == 6

    def test_event_merging_updates_statistics(self, detector):
        """Test merged event has updated statistics."""
        base_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        anomalies = [
            # First event
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time,
                "observed_value": 150.0,
                "robust_z": 3.5,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=1),
                "observed_value": 160.0,
                "robust_z": 4.0,
                "severity": "EXTREME",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=2),
                "observed_value": 155.0,
                "robust_z": 3.8,
                "severity": "HIGH",
            },
            # Second event (30 min gap)
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=2, minutes=30),
                "observed_value": 140.0,
                "robust_z": 3.0,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=3, minutes=30),
                "observed_value": 165.0,
                "robust_z": 4.2,
                "severity": "SEVERE",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=4, minutes=30),
                "observed_value": 158.0,
                "robust_z": 3.9,
                "severity": "HIGH",
            },
        ]

        events = detector.detect_events(anomalies)

        assert len(events) == 1
        event = events[0]
        assert event["anomaly_count"] == 6
        assert event["peak_value"] == 165.0  # Max from all 6
        assert event["severity"] == "EXTREME"  # Highest severity
        assert event["peak_anomaly_score"] == 4.2
        # Mean of all values
        expected_mean = (150 + 160 + 155 + 140 + 165 + 158) / 6
        assert pytest.approx(event["mean_value"], abs=0.1) == expected_mean

    def test_multiple_location_pollutant_pairs_no_cross_merge(self, detector):
        """Test events from different locations/pollutants don't merge."""
        base_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        anomalies = [
            # Location 1, PM25
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time,
                "observed_value": 150.0,
                "robust_z": 3.5,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=1),
                "observed_value": 160.0,
                "robust_z": 4.0,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=2),
                "observed_value": 155.0,
                "robust_z": 3.8,
                "severity": "HIGH",
            },
            # Location 2, PM25
            {
                "location_id": "delhi",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=1),
                "observed_value": 140.0,
                "robust_z": 3.2,
                "severity": "HIGH",
            },
            {
                "location_id": "delhi",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=2),
                "observed_value": 170.0,
                "robust_z": 4.1,
                "severity": "HIGH",
            },
            {
                "location_id": "delhi",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=3),
                "observed_value": 152.0,
                "robust_z": 3.6,
                "severity": "HIGH",
            },
        ]

        events = detector.detect_events(anomalies)

        assert len(events) == 2
        locations = {e["location_id"] for e in events}
        assert locations == {"kolkata", "delhi"}


class TestEventIDGeneration:
    """Test event ID generation and idempotency."""

    def test_event_id_is_uuid(self, detector, sample_anomalies):
        """Test event_id is a valid UUID string."""
        events = detector.detect_events(sample_anomalies)

        assert len(events) == 1
        event_id = events[0]["event_id"]
        # Should be valid UUID format
        try:
            import uuid
            uuid.UUID(event_id)
        except ValueError:
            pytest.fail(f"Invalid UUID: {event_id}")

    def test_event_id_deterministic(self, detector):
        """Test event_id is deterministic from (location, pollutant, start_time)."""
        base_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        anomalies = [
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time,
                "observed_value": 150.0,
                "robust_z": 3.5,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=1),
                "observed_value": 160.0,
                "robust_z": 4.0,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=2),
                "observed_value": 155.0,
                "robust_z": 3.8,
                "severity": "HIGH",
            },
        ]

        events1 = detector.detect_events(anomalies)
        events2 = detector.detect_events(anomalies)

        assert events1[0]["event_id"] == events2[0]["event_id"]

    def test_different_start_times_different_ids(self, detector):
        """Test different start times produce different IDs."""
        base_time1 = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        base_time2 = datetime(2026, 8, 15, 13, 0, 0, tzinfo=timezone.utc)

        anomalies1 = [
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time1,
                "observed_value": 150.0,
                "robust_z": 3.5,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time1 + timedelta(hours=1),
                "observed_value": 160.0,
                "robust_z": 4.0,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time1 + timedelta(hours=2),
                "observed_value": 155.0,
                "robust_z": 3.8,
                "severity": "HIGH",
            },
        ]

        anomalies2 = [
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time2,
                "observed_value": 150.0,
                "robust_z": 3.5,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time2 + timedelta(hours=1),
                "observed_value": 160.0,
                "robust_z": 4.0,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time2 + timedelta(hours=2),
                "observed_value": 155.0,
                "robust_z": 3.8,
                "severity": "HIGH",
            },
        ]

        events1 = detector.detect_events(anomalies1)
        events2 = detector.detect_events(anomalies2)

        assert events1[0]["event_id"] != events2[0]["event_id"]


class TestEventOutputSchema:
    """Test event output schema and timestamps."""

    def test_event_has_all_required_fields(self, detector, sample_anomalies):
        """Test event dict has all required fields."""
        events = detector.detect_events(sample_anomalies)

        assert len(events) == 1
        event = events[0]

        required_fields = [
            "event_id",
            "location_id",
            "pollutant",
            "start_time",
            "end_time",
            "duration_hours",
            "peak_value",
            "mean_value",
            "peak_anomaly_score",
            "severity",
            "anomaly_count",
            "detected_at",
        ]

        for field in required_fields:
            assert field in event

    def test_timestamps_are_iso_format(self, detector, sample_anomalies):
        """Test timestamps are ISO 8601 format."""
        events = detector.detect_events(sample_anomalies)

        event = events[0]
        # Try to parse as ISO format
        start = datetime.fromisoformat(event["start_time"])
        end = datetime.fromisoformat(event["end_time"])
        detected = datetime.fromisoformat(event["detected_at"])

        assert start.tzinfo is not None
        assert end.tzinfo is not None
        assert detected.tzinfo is not None

    def test_start_time_before_end_time(self, detector, sample_anomalies):
        """Test start_time is before end_time."""
        events = detector.detect_events(sample_anomalies)

        event = events[0]
        start = datetime.fromisoformat(event["start_time"])
        end = datetime.fromisoformat(event["end_time"])

        assert start <= end

    def test_detected_at_recent(self, detector, sample_anomalies):
        """Test detected_at is recent (within last minute)."""
        now = datetime.now(timezone.utc)
        events = detector.detect_events(sample_anomalies)

        event = events[0]
        detected = datetime.fromisoformat(event["detected_at"])

        time_diff = (now - detected).total_seconds()
        assert time_diff < 60  # Within 1 minute


class TestMultipleEventSequences:
    """Test detection of multiple separate events."""

    def test_two_separate_events_same_location(self, detector):
        """Test detecting 2 separate events at same location."""
        base_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        anomalies = [
            # First event: hours 0-2
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time,
                "observed_value": 150.0,
                "robust_z": 3.5,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=1),
                "observed_value": 160.0,
                "robust_z": 4.0,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=2),
                "observed_value": 155.0,
                "robust_z": 3.8,
                "severity": "HIGH",
            },
            # Gap: large (> 1 hour)
            # Second event: hours 8-10
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=8),
                "observed_value": 145.0,
                "robust_z": 3.2,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=9),
                "observed_value": 170.0,
                "robust_z": 4.1,
                "severity": "HIGH",
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": base_time + timedelta(hours=10),
                "observed_value": 152.0,
                "robust_z": 3.6,
                "severity": "HIGH",
            },
        ]

        events = detector.detect_events(anomalies)

        assert len(events) == 2
        assert events[0]["anomaly_count"] == 3
        assert events[1]["anomaly_count"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
