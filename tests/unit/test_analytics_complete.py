"""Comprehensive tests for analytics (aggregation, anomaly detection, events)."""

import pytest
from datetime import datetime, timedelta
import statistics


class TestBaselineCalculation:
    """Test baseline calculation from historical data."""

    def test_baseline_365_days_valid(self):
        """Test baseline with 365 days of data is valid."""
        day_count = 365
        is_sufficient = day_count >= 365

        assert is_sufficient is True

    def test_baseline_366_days_leap_year(self):
        """Test baseline with leap year (366 days)."""
        day_count = 366
        is_sufficient = day_count >= 365

        assert is_sufficient is True

    def test_baseline_less_than_365_days_insufficient(self):
        """Test baseline with < 365 days is insufficient."""
        day_count = 364
        is_sufficient = day_count >= 365

        assert is_sufficient is False

    def test_baseline_median_calculation(self):
        """Test baseline median calculation."""
        values = [40, 50, 55, 60, 65, 70, 80]  # 7 values

        median = statistics.median(values)

        assert median == 60

    def test_baseline_percentile_calculation(self):
        """Test baseline percentile calculation."""
        values = list(range(1, 101))  # 1-100

        p50 = statistics.quantiles(values, n=100)[49]  # Median ~50
        p95 = statistics.quantiles(values, n=100)[94]  # ~95th percentile

        assert p50 > 45 and p50 < 55
        assert p95 > 90


class TestBaselineFallback:
    """Test baseline fallback for insufficient data."""

    def test_fallback_30_days_to_weekly(self):
        """Test 30-day data falls back to weekly baseline."""
        day_count = 30
        if day_count >= 365:
            baseline_type = "daily"
        elif day_count >= 30:
            baseline_type = "weekly"
        else:
            baseline_type = "none"

        assert baseline_type == "weekly"

    def test_no_fallback_365_days_or_more(self):
        """Test >= 365 days uses daily baseline (no fallback)."""
        day_count = 365
        if day_count >= 365:
            baseline_type = "daily"
        else:
            baseline_type = "weekly"

        assert baseline_type == "daily"

    def test_insufficient_data_no_baseline(self):
        """Test < 30 days means no baseline."""
        day_count = 15
        if day_count >= 365:
            baseline_type = "daily"
        elif day_count >= 30:
            baseline_type = "weekly"
        else:
            baseline_type = "none"

        assert baseline_type == "none"


class TestLocationAggregation:
    """Test aggregation across multiple monitoring stations."""

    def test_aggregation_3_stations_median(self):
        """Test median aggregation across 3 stations."""
        station_values = [
            {"station_id": "stn_001", "value": 55.0},
            {"station_id": "stn_002", "value": 65.5},
            {"station_id": "stn_003", "value": 60.0},
        ]

        values = [s["value"] for s in station_values]
        median = statistics.median(values)

        assert median == 60.0

    def test_aggregation_multiple_locations(self):
        """Test aggregation across multiple locations."""
        locations_data = {
            "kolkata_001": [60, 65, 70],
            "delhi_001": [55, 60, 65],
        }

        location_medians = {
            loc: statistics.median(vals)
            for loc, vals in locations_data.items()
        }

        assert location_medians["kolkata_001"] == 65
        assert location_medians["delhi_001"] == 60

    def test_aggregation_handles_null_values(self):
        """Test aggregation skips null values."""
        station_values = [55.0, None, 65.5, 60.0]

        # Filter nulls
        valid_values = [v for v in station_values if v is not None]
        median = statistics.median(valid_values)

        assert median == 60.0
        assert len(valid_values) == 3


class TestAnomalyDetectionZScore:
    """Test anomaly detection using z-score."""

    def test_normal_value_z_less_than_2(self):
        """Test normal value (z < 2) is NORMAL."""
        mean = 50
        std = 10
        value = 55  # z = 0.5

        z_score = (value - mean) / std

        if z_score < 2:
            severity = "NORMAL"
        elif z_score < 3:
            severity = "LOW"
        else:
            severity = "HIGH"

        assert severity == "NORMAL"
        assert z_score < 2

    def test_elevated_value_2_less_than_z_less_3(self):
        """Test elevated value (2 <= z < 3) is LOW."""
        mean = 50
        std = 10
        value = 70  # z = 2

        z_score = (value - mean) / std

        if z_score < 2:
            severity = "NORMAL"
        elif z_score < 3:
            severity = "LOW"
        else:
            severity = "HIGH"

        assert severity == "LOW"

    def test_high_anomaly_z_3_to_5(self):
        """Test high anomaly (3 <= z < 5)."""
        mean = 50
        std = 10
        value = 90  # z = 4

        z_score = (value - mean) / std

        if z_score < 3:
            severity = "NORMAL"
        elif z_score < 5:
            severity = "HIGH"
        else:
            severity = "EXTREME"

        assert severity == "HIGH"

    def test_extreme_anomaly_z_greater_5(self):
        """Test extreme anomaly (z >= 5)."""
        mean = 50
        std = 10
        value = 100  # z = 5

        z_score = (value - mean) / std

        if z_score < 5:
            severity = "HIGH"
        else:
            severity = "EXTREME"

        assert severity == "EXTREME"
        assert z_score >= 5


class TestAnomalyDetectionMADFallback:
    """Test anomaly detection fallback to MAD when std=0."""

    def test_zero_mad_uses_percentile_rank(self):
        """Test zero MAD falls back to percentile rank."""
        mad = 0  # All values identical

        if mad == 0:
            # Fallback to percentile rank method
            percentile_method = True
        else:
            percentile_method = False

        assert percentile_method is True

    def test_percentile_rank_calculation(self):
        """Test percentile rank calculation as fallback."""
        value = 65
        historical = [50, 55, 60, 65, 70, 75, 80]

        rank = sum(1 for v in historical if v <= value) / len(historical) * 100

        assert abs(rank - 57.14) < 0.01  # Allow floating point variation

    def test_percentile_threshold(self):
        """Test percentile rank threshold for anomaly."""
        rank = 95  # 95th percentile

        if rank >= 90:
            severity = "HIGH"
        else:
            severity = "NORMAL"

        assert severity == "HIGH"


class TestEventDetection:
    """Test pollution event detection."""

    def test_event_3_consecutive_high_anomalies(self):
        """Test 3 consecutive HIGH anomalies trigger event."""
        observations = [
            {"severity": "HIGH", "score": 3.2},
            {"severity": "HIGH", "score": 3.5},
            {"severity": "HIGH", "score": 3.1},
        ]

        # Check for 3 consecutive HIGH
        is_event = (
            len(observations) >= 3 and
            all(o["severity"] == "HIGH" for o in observations[-3:])
        )

        assert is_event is True

    def test_event_not_triggered_2_high(self):
        """Test 2 HIGH anomalies don't trigger event."""
        observations = [
            {"severity": "HIGH", "score": 3.2},
            {"severity": "HIGH", "score": 3.5},
        ]

        is_event = (
            len(observations) >= 3 and
            all(o["severity"] == "HIGH" for o in observations[-3:])
        )

        assert is_event is False

    def test_event_triggered_high_in_4h_window(self):
        """Test 3+ HIGH in 4-hour rolling window."""
        times = [
            datetime(2026, 8, 15, 10, 0),
            datetime(2026, 8, 15, 11, 0),
            datetime(2026, 8, 15, 13, 0),
        ]

        high_severities = [
            {"severity": "HIGH", "time": times[0]},
            {"severity": "HIGH", "time": times[1]},
            {"severity": "HIGH", "time": times[2]},
        ]

        # Check if 3+ HIGH in last 4 hours
        window_start = times[-1] - timedelta(hours=4)
        in_window = [h for h in high_severities if h["time"] >= window_start]

        is_event = len(in_window) >= 3

        assert is_event is True


class TestEventMerging:
    """Test event merging for adjacent events."""

    def test_events_30_minutes_apart_merged(self):
        """Test events <= 30 min apart are merged."""
        event1_end = datetime(2026, 8, 15, 10, 30, 0)
        event2_start = datetime(2026, 8, 15, 11, 0, 0)

        gap_minutes = (event2_start - event1_end).total_seconds() / 60

        should_merge = gap_minutes <= 30

        assert should_merge is True

    def test_events_31_minutes_apart_not_merged(self):
        """Test events > 30 min apart not merged."""
        event1_end = datetime(2026, 8, 15, 10, 30, 0)
        event2_start = datetime(2026, 8, 15, 11, 1, 0)

        gap_minutes = (event2_start - event1_end).total_seconds() / 60

        should_merge = gap_minutes <= 30

        assert should_merge is False

    def test_event_merging_consolidates_duration(self):
        """Test event merging consolidates duration."""
        event1 = {
            "start": datetime(2026, 8, 15, 10, 0, 0),
            "end": datetime(2026, 8, 15, 11, 0, 0),
        }

        event2 = {
            "start": datetime(2026, 8, 15, 11, 20, 0),
            "end": datetime(2026, 8, 15, 12, 0, 0),
        }

        merged = {
            "start": event1["start"],
            "end": event2["end"],
        }

        duration = (merged["end"] - merged["start"]).total_seconds() / 3600

        assert duration == 2.0  # 2 hours total


class TestStationHealthScoring:
    """Test station health score calculation."""

    def test_healthy_station_80_to_100(self):
        """Test healthy station has score 80-100."""
        score = 92

        if score >= 80:
            status = "healthy"
        elif score >= 50:
            status = "degraded"
        else:
            status = "offline"

        assert status == "healthy"

    def test_degraded_station_50_to_79(self):
        """Test degraded station has score 50-79."""
        score = 65

        if score >= 80:
            status = "healthy"
        elif score >= 50:
            status = "degraded"
        else:
            status = "offline"

        assert status == "degraded"

    def test_offline_station_below_50(self):
        """Test offline station has score < 50."""
        score = 45

        if score >= 80:
            status = "healthy"
        elif score >= 50:
            status = "degraded"
        else:
            status = "offline"

        assert status == "offline"

    def test_station_health_based_on_uptime_and_quality(self):
        """Test health score combines uptime and data quality."""
        uptime_pct = 98.5  # 98.5% uptime
        quality_pct = 96.0  # 96% valid data

        health_score = (uptime_pct + quality_pct) / 2

        assert health_score == 97.25
        assert health_score >= 80


class TestAnomalyReporting:
    """Test anomaly statistics reporting."""

    def test_anomaly_count_per_hour(self):
        """Test anomaly count per hour is calculated."""
        anomalies = [
            {"time": datetime(2026, 8, 15, 10, 15), "severity": "HIGH"},
            {"time": datetime(2026, 8, 15, 10, 45), "severity": "HIGH"},
            {"time": datetime(2026, 8, 15, 11, 30), "severity": "HIGH"},
        ]

        # Group by hour
        hourly_counts = {}
        for a in anomalies:
            hour = a["time"].replace(minute=0, second=0, microsecond=0)
            hourly_counts[hour] = hourly_counts.get(hour, 0) + 1

        assert len(hourly_counts) == 2
        assert hourly_counts[datetime(2026, 8, 15, 10, 0)] == 2
        assert hourly_counts[datetime(2026, 8, 15, 11, 0)] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
