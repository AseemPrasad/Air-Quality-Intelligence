"""Pollution event detection and merging logic.

Detects multi-hour pollution events from anomaly sequences and merges
nearby events to create comprehensive pollution incident reports.
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
import hashlib

from aq_engine.common import ensure_utc

logger = logging.getLogger(__name__)


class EventDetector:
    """Detects and merges pollution events from anomaly sequences.

    An event is defined as:
    - HIGH or EXTREME severity anomalies
    - >= 3 consecutive hours OR >= 3 anomalies in a 4-hour rolling window
    - Same location + pollutant

    Nearby events (<=1 hour apart) are automatically merged.

    Example:
        >>> detector = EventDetector()
        >>> anomalies = [
        ...     {"location_id": "kolkata", "pollutant": "pm25", "severity": "HIGH", ...},
        ...     {"location_id": "kolkata", "pollutant": "pm25", "severity": "EXTREME", ...},
        ...     {"location_id": "kolkata", "pollutant": "pm25", "severity": "HIGH", ...},
        ... ]
        >>> events = detector.detect_events(anomalies)
        >>> print(f"Detected {len(events)} events")
    """

    # Minimum consecutive anomalies to form an event
    MIN_CONSECUTIVE_ANOMALIES = 3

    # Minimum anomalies in 4-hour window
    MIN_ANOMALIES_IN_WINDOW = 3
    ROLLING_WINDOW_HOURS = 4

    # Maximum gap between events to merge
    MAX_GAP_FOR_MERGE_HOURS = 1

    # Severity levels that qualify as anomalous for event creation
    ANOMALOUS_SEVERITIES = ["HIGH", "SEVERE", "EXTREME"]

    def __init__(self):
        """Initialize event detector."""
        pass

    def detect_events(
        self,
        anomaly_series: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Detect pollution events from anomaly sequences.

        Args:
            anomaly_series: List of anomaly dicts (from AnomalyDetector.detect_batch)
                           Must include: location_id, pollutant, hour_start,
                                       severity, observed_value, robust_z

        Returns:
            List of event dicts with event_id, start/end times, statistics.
        """
        if not anomaly_series:
            logger.debug("No anomalies provided for event detection")
            return []

        logger.info(
            f"Detecting pollution events from {len(anomaly_series)} anomalies"
        )

        # Filter to anomalous severity only
        anomalous = [
            a for a in anomaly_series
            if a.get("severity") in self.ANOMALOUS_SEVERITIES
        ]

        if not anomalous:
            logger.debug("No anomalies with HIGH+ severity")
            return []

        # Group by (location_id, pollutant)
        grouped = self._group_by_location_pollutant(anomalous)

        # Detect events for each location-pollutant pair
        events = []
        for (location_id, pollutant), anomalies in grouped.items():
            location_events = self._detect_events_for_location(
                location_id, pollutant, anomalies
            )
            events.extend(location_events)

        # Merge nearby events
        merged_events = self._merge_nearby_events(events)

        logger.info(
            f"Detected {len(events)} raw events, "
            f"merged to {len(merged_events)} final events"
        )

        return merged_events

    def _group_by_location_pollutant(
        self, anomalies: List[Dict[str, Any]]
    ) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
        """Group anomalies by location_id + pollutant.

        Args:
            anomalies: List of anomaly dicts

        Returns:
            Dict mapping (location_id, pollutant) → list of anomalies
        """
        grouped = defaultdict(list)
        for anomaly in anomalies:
            key = (anomaly["location_id"], anomaly["pollutant"])
            grouped[key].append(anomaly)

        # Sort each group by hour_start
        for key in grouped:
            grouped[key].sort(
                key=lambda x: x.get("hour_start", datetime.min)
            )

        return grouped

    def _detect_events_for_location(
        self,
        location_id: str,
        pollutant: str,
        anomalies: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Detect events for a single location-pollutant pair.

        Args:
            location_id: Location identifier
            pollutant: Pollutant name
            anomalies: Sorted list of anomalies for this location-pollutant

        Returns:
            List of event dicts
        """
        events = []
        i = 0

        while i < len(anomalies):
            # Check for event starting at position i
            event_indices = self._find_event_starting_at(anomalies, i)

            if event_indices:
                # Create event from these anomalies
                event_anomalies = [anomalies[j] for j in event_indices]
                event = self._create_event(location_id, pollutant, event_anomalies)
                events.append(event)

                # Continue after this event
                i = max(event_indices) + 1
            else:
                i += 1

        return events

    def _find_event_starting_at(
        self, anomalies: List[Dict[str, Any]], start_idx: int
    ) -> List[int]:
        """Find anomaly indices for an event starting at position start_idx.

        Checks both consecutive anomalies and 4-hour rolling window.

        Args:
            anomalies: Sorted list of anomalies
            start_idx: Starting index to check

        Returns:
            List of indices (empty if no event found)
        """
        # Check consecutive anomalies
        consecutive_indices = self._find_consecutive_anomalies(
            anomalies, start_idx, self.MIN_CONSECUTIVE_ANOMALIES
        )
        if consecutive_indices:
            return consecutive_indices

        # Check 4-hour rolling window
        window_indices = self._find_anomalies_in_window(
            anomalies,
            start_idx,
            self.MIN_ANOMALIES_IN_WINDOW,
            self.ROLLING_WINDOW_HOURS,
        )
        if window_indices:
            return window_indices

        return []

    def _find_consecutive_anomalies(
        self,
        anomalies: List[Dict[str, Any]],
        start_idx: int,
        min_count: int,
    ) -> List[int]:
        """Find consecutive hourly anomalies.

        Args:
            anomalies: Sorted list of anomalies
            start_idx: Starting index
            min_count: Minimum consecutive required

        Returns:
            List of indices if found, empty otherwise
        """
        indices = []

        for i in range(start_idx, len(anomalies)):
            # Check if consecutive hour from previous
            if indices and i > 0:
                prev_time = anomalies[indices[-1]].get("hour_start")
                curr_time = anomalies[i].get("hour_start")

                if prev_time and curr_time:
                    # Convert to UTC if needed
                    prev_time = ensure_utc(prev_time)
                    curr_time = ensure_utc(curr_time)

                    time_diff = (curr_time - prev_time).total_seconds() / 3600
                    if time_diff != 1.0:  # Not consecutive hour
                        break

            indices.append(i)

            if len(indices) >= min_count:
                return indices

        return [] if len(indices) < min_count else indices

    def _find_anomalies_in_window(
        self,
        anomalies: List[Dict[str, Any]],
        start_idx: int,
        min_count: int,
        window_hours: int,
    ) -> List[int]:
        """Find anomalies within a rolling time window.

        Args:
            anomalies: Sorted list of anomalies
            start_idx: Starting index
            min_count: Minimum anomalies required
            window_hours: Window size in hours

        Returns:
            List of indices if found, empty otherwise
        """
        window_start = anomalies[start_idx].get("hour_start")
        if not window_start:
            return []

        window_start = ensure_utc(window_start)
        window_end = window_start + timedelta(hours=window_hours)

        indices = []
        for i in range(start_idx, len(anomalies)):
            anomaly_time = ensure_utc(anomalies[i].get("hour_start"))

            if window_start <= anomaly_time <= window_end:
                indices.append(i)
            elif anomaly_time > window_end:
                break

        return indices if len(indices) >= min_count else []

    def _create_event(
        self,
        location_id: str,
        pollutant: str,
        anomalies: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Create event dict from anomalies.

        Args:
            location_id: Location identifier
            pollutant: Pollutant name
            anomalies: List of anomalies (sorted by time)

        Returns:
            Event dict
        """
        if not anomalies:
            return {}

        start_time = ensure_utc(anomalies[0]["hour_start"])
        end_time = ensure_utc(anomalies[-1]["hour_start"])
        duration_hours = int((end_time - start_time).total_seconds() / 3600) + 1

        observed_values = [a.get("observed_value") for a in anomalies if a.get("observed_value")]
        robust_zs = [abs(a.get("robust_z", 0)) for a in anomalies]

        peak_value = max(observed_values) if observed_values else None
        mean_value = sum(observed_values) / len(observed_values) if observed_values else None
        peak_anomaly_score = max(robust_zs) if robust_zs else None

        # Determine severity (highest among anomalies)
        severity = max(
            [a.get("severity") for a in anomalies],
            key=lambda s: ["HIGH", "SEVERE", "EXTREME"].index(s)
            if s in ["HIGH", "SEVERE", "EXTREME"]
            else -1,
        )

        # Generate deterministic event_id
        event_id = self._generate_event_id(location_id, pollutant, start_time)

        return {
            "event_id": event_id,
            "location_id": location_id,
            "pollutant": pollutant,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_hours": duration_hours,
            "peak_value": peak_value,
            "mean_value": mean_value,
            "peak_anomaly_score": peak_anomaly_score,
            "severity": severity,
            "anomaly_count": len(anomalies),
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }

    def _generate_event_id(
        self, location_id: str, pollutant: str, start_time: datetime
    ) -> str:
        """Generate deterministic event ID.

        Args:
            location_id: Location identifier
            pollutant: Pollutant name
            start_time: Event start time

        Returns:
            UUID string derived from (location, pollutant, start_time)
        """
        # Create deterministic hash from (location, pollutant, start_time)
        key = f"{location_id}:{pollutant}:{start_time.isoformat()}"
        hash_bytes = hashlib.sha256(key.encode()).digest()

        # Convert hash to UUID
        return str(uuid.UUID(bytes=hash_bytes[:16]))

    def _merge_nearby_events(
        self, events: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Merge events for same location-pollutant separated by <=1 hour.

        Args:
            events: List of event dicts

        Returns:
            List of merged event dicts
        """
        if len(events) <= 1:
            return events

        # Sort events by location, pollutant, start_time
        sorted_events = sorted(
            events,
            key=lambda e: (e["location_id"], e["pollutant"], e["start_time"]),
        )

        merged = []
        current_event = sorted_events[0]

        for i in range(1, len(sorted_events)):
            next_event = sorted_events[i]

            # Check if should merge
            if (
                current_event["location_id"] == next_event["location_id"]
                and current_event["pollutant"] == next_event["pollutant"]
                and self._events_are_adjacent(current_event, next_event)
            ):
                # Merge events
                current_event = self._merge_two_events(current_event, next_event)
                logger.debug(
                    f"Merged events for {current_event['location_id']}/"
                    f"{current_event['pollutant']}"
                )
            else:
                # Save current and start new
                merged.append(current_event)
                current_event = next_event

        merged.append(current_event)
        return merged

    def _events_are_adjacent(
        self, event1: Dict[str, Any], event2: Dict[str, Any]
    ) -> bool:
        """Check if two events should be merged (<=1 hour gap).

        Args:
            event1: First event (earlier)
            event2: Second event (later)

        Returns:
            True if events should be merged
        """
        end_time1 = ensure_utc(datetime.fromisoformat(event1["end_time"]))
        start_time2 = ensure_utc(datetime.fromisoformat(event2["start_time"]))

        gap = start_time2 - end_time1
        return gap <= timedelta(hours=self.MAX_GAP_FOR_MERGE_HOURS)

    def _merge_two_events(
        self, event1: Dict[str, Any], event2: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Merge two events into one.

        Args:
            event1: First event (earlier)
            event2: Second event (later)

        Returns:
            Merged event dict
        """
        start_time = ensure_utc(datetime.fromisoformat(event1["start_time"]))
        end_time = ensure_utc(datetime.fromisoformat(event2["end_time"]))
        duration_hours = int((end_time - start_time).total_seconds() / 3600) + 1

        # Combine peaks and means
        peak_value = max(event1.get("peak_value", 0), event2.get("peak_value", 0))
        total_anomalies = event1.get("anomaly_count", 0) + event2.get("anomaly_count", 0)

        mean_value1 = event1.get("mean_value", 0) or 0
        mean_value2 = event2.get("mean_value", 0) or 0

        mean_value = (
            (mean_value1 * event1.get("anomaly_count", 1) +
             mean_value2 * event2.get("anomaly_count", 1)) /
            total_anomalies
            if total_anomalies > 0
            else None
        )

        peak_anomaly_score = max(
            event1.get("peak_anomaly_score", 0),
            event2.get("peak_anomaly_score", 0),
        )

        # Keep more severe severity
        severity_order = ["HIGH", "SEVERE", "EXTREME"]
        severity1_idx = (
            severity_order.index(event1.get("severity"))
            if event1.get("severity") in severity_order
            else -1
        )
        severity2_idx = (
            severity_order.index(event2.get("severity"))
            if event2.get("severity") in severity_order
            else -1
        )
        severity = severity_order[max(severity1_idx, severity2_idx)]

        # Generate new event_id from merged period
        event_id = self._generate_event_id(
            event1["location_id"], event1["pollutant"], start_time
        )

        return {
            "event_id": event_id,
            "location_id": event1["location_id"],
            "pollutant": event1["pollutant"],
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_hours": duration_hours,
            "peak_value": peak_value,
            "mean_value": mean_value,
            "peak_anomaly_score": peak_anomaly_score,
            "severity": severity,
            "anomaly_count": total_anomalies,
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }
