"""Unit tests for station health scoring.

Tests health score calculation, penalty application, and status classification.
"""

import pytest
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch

from aq_engine.analytics.station_health import StationHealthScorer, HealthStatus


@pytest.fixture
def scorer():
    """StationHealthScorer instance."""
    return StationHealthScorer()


@pytest.fixture
def perfect_metrics():
    """Perfect metrics (all 0%)."""
    return {
        "availability_pct": 100.0,
        "missing_rate": 0.0,
        "duplicate_rate": 0.0,
        "stale_rate": 0.0,
        "flatline_rate": 0.0,
        "outlier_rate": 0.0,
    }


class TestHealthScoreCalculation:
    """Test health score calculation."""

    def test_perfect_metrics_score_100(self, scorer, perfect_metrics):
        """Test perfect metrics result in score of 100."""
        score, penalties = scorer._calculate_health_score(perfect_metrics)

        assert score == 100.0
        assert len(penalties) == 0

    def test_low_availability_penalty(self, scorer, perfect_metrics):
        """Test low availability (< 80%) applies -30 penalty."""
        metrics = perfect_metrics.copy()
        metrics["availability_pct"] = 75.0

        score, penalties = scorer._calculate_health_score(metrics)

        assert score == 70.0  # 100 - 30
        assert len(penalties) == 1
        assert penalties[0]["metric"] == "availability"
        assert penalties[0]["penalty"] == 30

    def test_high_missing_rate_penalty(self, scorer, perfect_metrics):
        """Test high missing rate (> 10%) applies -20 penalty."""
        metrics = perfect_metrics.copy()
        metrics["missing_rate"] = 15.0

        score, penalties = scorer._calculate_health_score(metrics)

        assert score == 80.0  # 100 - 20
        assert len(penalties) == 1
        assert penalties[0]["metric"] == "missing_rate"
        assert penalties[0]["penalty"] == 20

    def test_high_duplicate_rate_penalty(self, scorer, perfect_metrics):
        """Test high duplicate rate (> 5%) applies -10 penalty."""
        metrics = perfect_metrics.copy()
        metrics["duplicate_rate"] = 10.0

        score, penalties = scorer._calculate_health_score(metrics)

        assert score == 90.0  # 100 - 10
        assert len(penalties) == 1
        assert penalties[0]["penalty"] == 10

    def test_high_stale_rate_penalty(self, scorer, perfect_metrics):
        """Test high stale rate (> 5%) applies -10 penalty."""
        metrics = perfect_metrics.copy()
        metrics["stale_rate"] = 8.0

        score, penalties = scorer._calculate_health_score(metrics)

        assert score == 90.0  # 100 - 10
        assert len(penalties) == 1
        assert penalties[0]["metric"] == "stale_rate"

    def test_high_flatline_rate_penalty(self, scorer, perfect_metrics):
        """Test high flatline rate (> 10%) applies -10 penalty."""
        metrics = perfect_metrics.copy()
        metrics["flatline_rate"] = 12.0

        score, penalties = scorer._calculate_health_score(metrics)

        assert score == 90.0  # 100 - 10
        assert penalties[0]["metric"] == "flatline_rate"

    def test_high_outlier_rate_penalty(self, scorer, perfect_metrics):
        """Test high outlier rate (> 2%) applies -5 penalty."""
        metrics = perfect_metrics.copy()
        metrics["outlier_rate"] = 5.0

        score, penalties = scorer._calculate_health_score(metrics)

        assert score == 95.0  # 100 - 5
        assert penalties[0]["metric"] == "outlier_rate"
        assert penalties[0]["penalty"] == 5

    def test_multiple_penalties_cumulative(self, scorer, perfect_metrics):
        """Test multiple penalties are cumulative."""
        metrics = {
            "availability_pct": 75.0,  # -30
            "missing_rate": 15.0,  # -20
            "duplicate_rate": 10.0,  # -10
            "stale_rate": 0.0,
            "flatline_rate": 0.0,
            "outlier_rate": 0.0,
        }

        score, penalties = scorer._calculate_health_score(metrics)

        assert score == 40.0  # 100 - 30 - 20 - 10
        assert len(penalties) == 3

    def test_score_clamped_to_100_max(self, scorer, perfect_metrics):
        """Test score doesn't exceed 100."""
        metrics = perfect_metrics.copy()
        metrics["availability_pct"] = 150.0  # Invalid but shouldn't go > 100

        score, penalties = scorer._calculate_health_score(metrics)

        assert score == 100.0

    def test_score_clamped_to_0_min(self, scorer):
        """Test score doesn't go below 0."""
        metrics = {
            "availability_pct": 0.0,  # -30
            "missing_rate": 50.0,  # -20
            "duplicate_rate": 10.0,  # -10
            "stale_rate": 10.0,  # -10
            "flatline_rate": 20.0,  # -10
            "outlier_rate": 10.0,  # -5
        }

        score, penalties = scorer._calculate_health_score(metrics)

        # 100 - 30 - 20 - 10 - 10 - 10 - 5 = 15
        assert score == 15.0
        assert score >= 0.0


class TestStatusClassification:
    """Test status classification from score."""

    def test_healthy_status_score_80_plus(self, scorer):
        """Test score >= 80 classified as healthy."""
        assert scorer._classify_status(100.0) == HealthStatus.HEALTHY.value
        assert scorer._classify_status(90.0) == HealthStatus.HEALTHY.value
        assert scorer._classify_status(80.0) == HealthStatus.HEALTHY.value

    def test_degraded_status_score_50_to_79(self, scorer):
        """Test score 50-79 classified as degraded."""
        assert scorer._classify_status(79.0) == HealthStatus.DEGRADED.value
        assert scorer._classify_status(65.0) == HealthStatus.DEGRADED.value
        assert scorer._classify_status(50.0) == HealthStatus.DEGRADED.value

    def test_offline_status_score_below_50(self, scorer):
        """Test score < 50 classified as offline."""
        assert scorer._classify_status(49.0) == HealthStatus.OFFLINE.value
        assert scorer._classify_status(25.0) == HealthStatus.OFFLINE.value
        assert scorer._classify_status(0.0) == HealthStatus.OFFLINE.value


class TestStationHealthScoring:
    """Test full station health scoring."""

    def test_perfect_health_high_score(self, scorer):
        """Test perfect metrics yield high health score."""
        with patch.object(
            scorer,
            "_calculate_station_metrics",
            return_value={
                "availability_pct": 100.0,
                "missing_rate": 0.0,
                "duplicate_rate": 0.0,
                "stale_rate": 0.0,
                "flatline_rate": 0.0,
                "outlier_rate": 0.0,
            },
        ):
            result = scorer.score_station_health(
                station_id="station_1",
                window_days=30,
                end_date=date(2026, 8, 15),
            )

        assert result["station_id"] == "station_1"
        assert result["window_days"] == 30
        assert result["health_score"] == 100.0
        assert result["status"] == HealthStatus.HEALTHY.value
        assert len(result["penalties_applied"]) == 0

    def test_degraded_health_50_percent_availability(self, scorer):
        """Test 50% availability results in degraded status."""
        with patch.object(
            scorer,
            "_calculate_station_metrics",
            return_value={
                "availability_pct": 50.0,  # -30
                "missing_rate": 0.0,
                "duplicate_rate": 0.0,
                "stale_rate": 0.0,
                "flatline_rate": 0.0,
                "outlier_rate": 0.0,
            },
        ):
            result = scorer.score_station_health(
                station_id="station_2",
                window_days=30,
            )

        assert result["health_score"] == 70.0
        assert result["status"] == HealthStatus.DEGRADED.value
        assert len(result["penalties_applied"]) == 1

    def test_offline_station_low_score(self, scorer):
        """Test offline station recommendation (score < 50)."""
        with patch.object(
            scorer,
            "_calculate_station_metrics",
            return_value={
                "availability_pct": 0.0,  # -30
                "missing_rate": 50.0,  # -20
                "duplicate_rate": 0.0,
                "stale_rate": 0.0,
                "flatline_rate": 0.0,
                "outlier_rate": 0.0,
            },
        ):
            result = scorer.score_station_health(
                station_id="station_3",
                window_days=30,
            )

        assert result["health_score"] == 50.0
        assert result["status"] == HealthStatus.DEGRADED.value

    def test_high_outlier_rate_penalty(self, scorer):
        """Test high outlier rate applies penalty."""
        with patch.object(
            scorer,
            "_calculate_station_metrics",
            return_value={
                "availability_pct": 100.0,
                "missing_rate": 0.0,
                "duplicate_rate": 0.0,
                "stale_rate": 0.0,
                "flatline_rate": 0.0,
                "outlier_rate": 5.0,  # -5
            },
        ):
            result = scorer.score_station_health(
                station_id="station_4",
                window_days=30,
            )

        assert result["health_score"] == 95.0
        assert len(result["penalties_applied"]) == 1
        assert result["penalties_applied"][0]["metric"] == "outlier_rate"

    def test_computed_at_timestamp(self, scorer):
        """Test computed_at timestamp is set."""
        with patch.object(
            scorer, "_calculate_station_metrics", return_value={
                "availability_pct": 100.0,
                "missing_rate": 0.0,
                "duplicate_rate": 0.0,
                "stale_rate": 0.0,
                "flatline_rate": 0.0,
                "outlier_rate": 0.0,
            }
        ):
            result = scorer.score_station_health(
                station_id="station_5",
                window_days=30,
            )

        assert "computed_at" in result
        assert isinstance(result["computed_at"], str)
        # Verify it's a valid ISO format timestamp
        datetime.fromisoformat(result["computed_at"])


class TestBatchScoring:
    """Test batch health scoring."""

    def test_batch_scoring_multiple_stations(self, scorer):
        """Test scoring multiple stations."""
        with patch.object(
            scorer, "score_station_health"
        ) as mock_score:
            mock_score.return_value = {
                "station_id": "st_1",
                "health_score": 85.0,
                "status": "healthy",
            }

            results = scorer.score_batch(
                station_ids=["st_1", "st_2", "st_3"],
                window_days=30,
            )

            assert len(results) == 3
            assert mock_score.call_count == 3

    def test_batch_scoring_call_order(self, scorer):
        """Test batch scoring processes stations in order."""
        call_order = []

        def mock_score(station_id, **kwargs):
            call_order.append(station_id)
            return {"station_id": station_id, "health_score": 80.0}

        with patch.object(scorer, "score_station_health", side_effect=mock_score):
            scorer.score_batch(
                station_ids=["st_a", "st_b", "st_c"],
                window_days=30,
            )

        assert call_order == ["st_a", "st_b", "st_c"]


class TestHealthSummary:
    """Test health summary statistics."""

    def test_summary_all_healthy(self, scorer):
        """Test summary with all healthy stations."""
        health_scores = [
            {"station_id": "st_1", "health_score": 90.0, "status": "healthy"},
            {"station_id": "st_2", "health_score": 85.0, "status": "healthy"},
            {"station_id": "st_3", "health_score": 95.0, "status": "healthy"},
        ]

        summary = scorer.get_health_summary(health_scores)

        assert summary["total_stations"] == 3
        assert summary["healthy"] == 3
        assert summary["degraded"] == 0
        assert summary["offline"] == 0
        assert summary["healthy_pct"] == 100.0
        assert summary["mean_health_score"] == 90.0

    def test_summary_mixed_status(self, scorer):
        """Test summary with mixed health statuses."""
        health_scores = [
            {"station_id": "st_1", "health_score": 90.0, "status": "healthy"},
            {"station_id": "st_2", "health_score": 60.0, "status": "degraded"},
            {"station_id": "st_3", "health_score": 40.0, "status": "offline"},
        ]

        summary = scorer.get_health_summary(health_scores)

        assert summary["total_stations"] == 3
        assert summary["healthy"] == 1
        assert summary["degraded"] == 1
        assert summary["offline"] == 1
        assert summary["healthy_pct"] == pytest.approx(33.33, abs=0.1)

    def test_summary_median_calculation(self, scorer):
        """Test median health score calculation."""
        health_scores = [
            {"health_score": 100.0, "status": "healthy"},
            {"health_score": 80.0, "status": "healthy"},
            {"health_score": 60.0, "status": "degraded"},
            {"health_score": 40.0, "status": "offline"},
            {"health_score": 20.0, "status": "offline"},
        ]

        summary = scorer.get_health_summary(health_scores)

        # Sorted: [20, 40, 60, 80, 100]
        # Median (5 items): 60
        assert summary["median_health_score"] == 60.0

    def test_summary_empty_list(self, scorer):
        """Test summary with empty list."""
        summary = scorer.get_health_summary([])

        assert summary["total_stations"] == 0
        assert summary["mean_health_score"] is None
        assert summary["median_health_score"] is None


class TestPenaltyThresholds:
    """Test penalty threshold boundaries."""

    def test_availability_threshold_boundary_80(self, scorer, perfect_metrics):
        """Test availability penalty threshold at 80%."""
        # At 80%: should NOT apply penalty
        metrics = perfect_metrics.copy()
        metrics["availability_pct"] = 80.0
        score, penalties = scorer._calculate_health_score(metrics)
        assert score == 100.0
        assert len(penalties) == 0

        # At 79.9%: should apply penalty
        metrics["availability_pct"] = 79.9
        score, penalties = scorer._calculate_health_score(metrics)
        assert score == 70.0
        assert len(penalties) == 1

    def test_missing_rate_threshold_boundary_10(self, scorer, perfect_metrics):
        """Test missing rate penalty threshold at 10%."""
        # At 10%: should NOT apply penalty
        metrics = perfect_metrics.copy()
        metrics["missing_rate"] = 10.0
        score, penalties = scorer._calculate_health_score(metrics)
        assert score == 100.0

        # At 10.1%: should apply penalty
        metrics["missing_rate"] = 10.1
        score, penalties = scorer._calculate_health_score(metrics)
        assert score == 80.0

    def test_duplicate_rate_threshold_boundary_5(self, scorer, perfect_metrics):
        """Test duplicate rate penalty threshold at 5%."""
        # At 5%: should NOT apply penalty
        metrics = perfect_metrics.copy()
        metrics["duplicate_rate"] = 5.0
        score, penalties = scorer._calculate_health_score(metrics)
        assert score == 100.0

        # At 5.1%: should apply penalty
        metrics["duplicate_rate"] = 5.1
        score, penalties = scorer._calculate_health_score(metrics)
        assert score == 90.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
