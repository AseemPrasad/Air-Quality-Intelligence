"""Analytics layer for baselines, aggregation, station health, anomaly detection, and event detection."""

from aq_engine.analytics.baselines import BaselineCalculator
from aq_engine.analytics.aggregation import LocationAggregator
from aq_engine.analytics.station_health import StationHealthScorer, HealthStatus
from aq_engine.analytics.anomaly import AnomalyDetector, AnomalySeverity
from aq_engine.analytics.events import EventDetector

__all__ = [
    "BaselineCalculator",
    "LocationAggregator",
    "StationHealthScorer",
    "HealthStatus",
    "AnomalyDetector",
    "AnomalySeverity",
    "EventDetector",
]
