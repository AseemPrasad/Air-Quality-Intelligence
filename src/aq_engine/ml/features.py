"""Feature engineering for PM2.5 forecasting with future-leakage prevention.

All features use only observations strictly BEFORE target_time to prevent
data leakage from the future into the training set.
"""

import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict

from aq_engine.common import ensure_utc

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """Generates ML features for PM2.5 forecasting without future leakage.

    All features are computed using observations strictly before target_time.
    The prediction horizon is specified separately and does NOT inform features.

    Example:
        >>> engineer = FeatureEngineer()
        >>> features = engineer.generate_features(
        ...     target_time=datetime(2026, 8, 15, 10, 0, 0, tzinfo=timezone.utc),
        ...     location_id="kolkata",
        ...     horizon_minutes=60,
        ...     hourly_facts={...},
        ...     weather_facts={...}
        ... )
        >>> print(f"PM2.5 lag 1h: {features['pm25_lag_1h']}")
    """

    # Feature version for reproducibility
    FEATURE_VERSION = "1.0.0"

    # Lag windows for lagged features (hours)
    PM25_LAG_HOURS = [1, 2, 3, 6, 12, 24]
    WEATHER_LAG_HOURS = [1]

    # Rolling window sizes (hours)
    PM25_ROLLING_WINDOWS = [3, 6, 12, 24]
    WEATHER_ROLLING_WINDOWS = [6, 24]

    # Maximum forward-fill hours (don't fill if missing > this)
    MAX_FORWARD_FILL_HOURS = 3

    def __init__(self):
        """Initialize feature engineer."""
        pass

    def generate_features(
        self,
        target_time: datetime,
        location_id: str,
        horizon_minutes: int,
        hourly_facts: Dict[Tuple[str, str, str], Dict[str, Any]],
        weather_facts: Dict[Tuple[str, str], Dict[str, Any]],
        citywide_pm25_baseline: Optional[Dict[str, Any]] = None,
        citywide_weather_baseline: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate features for PM2.5 forecasting.

        Args:
            target_time: Reference time for feature extraction (UTC)
            location_id: Location identifier
            horizon_minutes: Prediction horizon (not used for features, only for logging)
            hourly_facts: Dict mapping (location_id, pollutant, hour_start) → fact dict
                         Only facts with hour_start < target_time are valid
            weather_facts: Dict mapping (location_id, hour_start) → weather fact dict
            citywide_pm25_baseline: City-wide PM2.5 stats for imputation fallback
            citywide_weather_baseline: City-wide weather stats for imputation fallback

        Returns:
            Dict with all features and metadata

        Raises:
            ValueError: If invalid time configuration detected
        """
        target_time = ensure_utc(target_time)

        logger.debug(
            f"Generating features for {location_id} at {target_time} "
            f"(horizon={horizon_minutes}min)"
        )

        # Validate time configuration
        if horizon_minutes < 0:
            raise ValueError(f"horizon_minutes must be >= 0, got {horizon_minutes}")

        # Initialize feature dict
        features = {
            "location_id": location_id,
            "target_time": target_time.isoformat(),
            "horizon_minutes": horizon_minutes,
            "imputation_count": 0,
            "feature_version": self.FEATURE_VERSION,
        }

        imputation_count = 0

        # PM2.5 lag features
        pm25_lags, pm25_imputations = self._extract_pm25_lags(
            target_time, location_id, hourly_facts, citywide_pm25_baseline
        )
        features.update(pm25_lags)
        imputation_count += pm25_imputations

        # PM2.5 rolling statistics
        pm25_rolling, pm25_rolling_imputations = (
            self._extract_pm25_rolling_statistics(
                target_time, location_id, hourly_facts, citywide_pm25_baseline
            )
        )
        features.update(pm25_rolling)
        imputation_count += pm25_rolling_imputations

        # Weather lag features
        weather_lags, weather_imputations = self._extract_weather_lags(
            target_time, location_id, weather_facts, citywide_weather_baseline
        )
        features.update(weather_lags)
        imputation_count += weather_imputations

        # Weather rolling statistics
        weather_rolling, weather_rolling_imputations = (
            self._extract_weather_rolling_statistics(
                target_time, location_id, weather_facts, citywide_weather_baseline
            )
        )
        features.update(weather_rolling)
        imputation_count += weather_rolling_imputations

        # Wind direction (sin/cos transform)
        if "wind_direction_deg_lag_1h" in features:
            wind_sin, wind_cos = self._transform_wind_direction(
                features.get("wind_direction_deg_lag_1h")
            )
            features["wind_dir_sin"] = wind_sin
            features["wind_dir_cos"] = wind_cos

        # Calendar features
        calendar_features = self._extract_calendar_features(target_time)
        features.update(calendar_features)

        # Domain features
        domain_features = self._extract_domain_features(target_time)
        features.update(domain_features)

        # Set imputation count
        features["imputation_count"] = imputation_count

        if imputation_count > 0:
            logger.info(
                f"Generated features for {location_id}/{target_time} "
                f"with {imputation_count} imputed values"
            )

        return features

    def _extract_pm25_lags(
        self,
        target_time: datetime,
        location_id: str,
        hourly_facts: Dict[Tuple[str, str, str], Dict[str, Any]],
        citywide_baseline: Optional[Dict[str, Any]],
    ) -> Tuple[Dict[str, float], int]:
        """Extract PM2.5 lag features.

        Args:
            target_time: Reference time (UTC)
            location_id: Location identifier
            hourly_facts: Hourly facts dict
            citywide_baseline: City-wide PM2.5 for fallback

        Returns:
            Tuple of (features_dict, imputation_count)
        """
        features = {}
        imputation_count = 0

        for lag_hours in self.PM25_LAG_HOURS:
            feature_name = f"pm25_lag_{lag_hours}h"
            lag_time = target_time - timedelta(hours=lag_hours)

            # Fetch observation at lag_time
            value = self._get_hourly_fact(
                hourly_facts, location_id, "pm25", lag_time, "observed_value"
            )

            if value is None:
                # Try forward-fill (backward within 3 hours)
                value, was_imputed = self._forward_fill_or_fallback(
                    hourly_facts,
                    location_id,
                    "pm25",
                    lag_time,
                    self.MAX_FORWARD_FILL_HOURS,
                    citywide_baseline,
                    "historical_median" if citywide_baseline else None,
                )
                if was_imputed:
                    imputation_count += 1

            features[feature_name] = value

        return features, imputation_count

    def _extract_pm25_rolling_statistics(
        self,
        target_time: datetime,
        location_id: str,
        hourly_facts: Dict[Tuple[str, str, str], Dict[str, Any]],
        citywide_baseline: Optional[Dict[str, Any]],
    ) -> Tuple[Dict[str, float], int]:
        """Extract PM2.5 rolling statistics.

        Args:
            target_time: Reference time (UTC)
            location_id: Location identifier
            hourly_facts: Hourly facts dict
            citywide_baseline: City-wide PM2.5 for fallback

        Returns:
            Tuple of (features_dict, imputation_count)
        """
        features = {}
        imputation_count = 0

        # Rolling mean for multiple windows
        for window_hours in self.PM25_ROLLING_WINDOWS:
            feature_name = f"pm25_rolling_mean_{window_hours}h"
            values = self._get_rolling_window(
                hourly_facts,
                location_id,
                "pm25",
                target_time,
                window_hours,
                "observed_value",
            )

            mean_val = self._calculate_mean(values)
            if mean_val is None and citywide_baseline:
                mean_val = citywide_baseline.get("historical_median")
                imputation_count += 1

            features[feature_name] = mean_val

        # Rolling std for select windows
        for window_hours in [6, 24]:
            feature_name = f"pm25_rolling_std_{window_hours}h"
            values = self._get_rolling_window(
                hourly_facts,
                location_id,
                "pm25",
                target_time,
                window_hours,
                "observed_value",
            )

            std_val = self._calculate_std(values)
            if std_val is None:
                std_val = 0.0  # Default to 0 if all missing

            features[feature_name] = std_val

        # Rolling max
        feature_name = "pm25_rolling_max_24h"
        values = self._get_rolling_window(
            hourly_facts,
            location_id,
            "pm25",
            target_time,
            24,
            "observed_value",
        )
        max_val = self._calculate_max(values)
        if max_val is None and citywide_baseline:
            max_val = citywide_baseline.get("p99", citywide_baseline.get("historical_median"))
            imputation_count += 1

        features[feature_name] = max_val

        return features, imputation_count

    def _extract_weather_lags(
        self,
        target_time: datetime,
        location_id: str,
        weather_facts: Dict[Tuple[str, str], Dict[str, Any]],
        citywide_baseline: Optional[Dict[str, Any]],
    ) -> Tuple[Dict[str, Optional[float]], int]:
        """Extract weather lag features.

        Args:
            target_time: Reference time (UTC)
            location_id: Location identifier
            weather_facts: Weather facts dict
            citywide_baseline: City-wide weather for fallback

        Returns:
            Tuple of (features_dict, imputation_count)
        """
        features = {}
        imputation_count = 0

        weather_vars = [
            ("temperature_c", "temp_lag_1h"),
            ("humidity_pct", "humidity_lag_1h"),
            ("wind_speed_ms", "wind_speed_lag_1h"),
            ("pressure_hpa", "pressure_lag_1h"),
            ("wind_direction_deg", "wind_direction_deg_lag_1h"),
        ]

        for var_name, feature_name in weather_vars:
            lag_time = target_time - timedelta(hours=1)

            value = self._get_hourly_fact(
                weather_facts, location_id, None, lag_time, var_name
            )

            if value is None:
                # Try forward-fill
                value, was_imputed = self._forward_fill_or_fallback_weather(
                    weather_facts,
                    location_id,
                    lag_time,
                    var_name,
                    self.MAX_FORWARD_FILL_HOURS,
                    citywide_baseline,
                )
                if was_imputed:
                    imputation_count += 1

            features[feature_name] = value

        return features, imputation_count

    def _extract_weather_rolling_statistics(
        self,
        target_time: datetime,
        location_id: str,
        weather_facts: Dict[Tuple[str, str], Dict[str, Any]],
        citywide_baseline: Optional[Dict[str, Any]],
    ) -> Tuple[Dict[str, Optional[float]], int]:
        """Extract weather rolling statistics.

        Args:
            target_time: Reference time (UTC)
            location_id: Location identifier
            weather_facts: Weather facts dict
            citywide_baseline: City-wide weather for fallback

        Returns:
            Tuple of (features_dict, imputation_count)
        """
        features = {}
        imputation_count = 0

        weather_vars = [
            ("temperature_c", "temp_rolling_mean"),
            ("humidity_pct", "humidity_rolling_mean"),
            ("wind_speed_ms", "wind_speed_rolling_mean"),
            ("pressure_hpa", "pressure_rolling_mean"),
        ]

        for var_name, feature_prefix in weather_vars:
            for window_hours in self.WEATHER_ROLLING_WINDOWS:
                feature_name = f"{feature_prefix}_{window_hours}h"
                values = self._get_rolling_window_weather(
                    weather_facts, location_id, target_time, window_hours, var_name
                )

                mean_val = self._calculate_mean(values)
                if mean_val is None and citywide_baseline:
                    mean_val = citywide_baseline.get(f"{var_name}_mean")
                    imputation_count += 1

                features[feature_name] = mean_val

        return features, imputation_count

    def _extract_calendar_features(self, target_time: datetime) -> Dict[str, int]:
        """Extract calendar-based features.

        Args:
            target_time: Reference time (UTC)

        Returns:
            Dict with calendar features
        """
        return {
            "hour_of_day": target_time.hour,
            "day_of_week": target_time.weekday(),  # Monday=0
            "month": target_time.month,
            "day_of_year": target_time.timetuple().tm_yday,
            "is_weekend": 1 if target_time.weekday() >= 5 else 0,
        }

    def _extract_domain_features(self, target_time: datetime) -> Dict[str, int]:
        """Extract domain-specific features.

        Args:
            target_time: Reference time (UTC)

        Returns:
            Dict with domain features
        """
        hour_since_midnight = target_time.hour
        month = target_time.month

        # Season: 0=winter, 1=spring, 2=summer, 3=fall
        if month in [12, 1, 2]:
            season = 0
        elif month in [3, 4, 5]:
            season = 1
        elif month in [6, 7, 8]:
            season = 2
        else:
            season = 3

        return {
            "hour_since_midnight": hour_since_midnight,
            "season": season,
        }

    def _transform_wind_direction(self, wind_direction_deg: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
        """Transform wind direction to sin/cos components.

        Avoids circular discontinuity at 0°/360°.

        Args:
            wind_direction_deg: Wind direction in degrees (0-360)

        Returns:
            Tuple of (sin_component, cos_component)
        """
        if wind_direction_deg is None:
            return None, None

        # Convert degrees to radians
        radians = wind_direction_deg * math.pi / 180.0

        sin_val = math.sin(radians)
        cos_val = math.cos(radians)

        return sin_val, cos_val

    def _get_hourly_fact(
        self,
        facts_dict: Dict,
        location_id: str,
        pollutant: Optional[str],
        hour_start: datetime,
        field_name: str,
    ) -> Optional[float]:
        """Get a single hourly fact value.

        Args:
            facts_dict: Dict of facts
            location_id: Location identifier
            pollutant: Pollutant name (None for weather)
            hour_start: Hour timestamp
            field_name: Field to extract

        Returns:
            Value or None
        """
        hour_start = ensure_utc(hour_start)

        # Verify we're not peeking into the future
        # Note: We don't know target_time here, so caller must ensure no future data

        if pollutant:
            key = (location_id, pollutant, hour_start.isoformat())
        else:
            key = (location_id, hour_start.isoformat())

        fact = facts_dict.get(key)
        if fact is None:
            return None

        return fact.get(field_name)

    def _get_rolling_window(
        self,
        facts_dict: Dict,
        location_id: str,
        pollutant: str,
        target_time: datetime,
        window_hours: int,
        field_name: str,
    ) -> List[float]:
        """Get values in a rolling window (backward from target_time).

        Args:
            facts_dict: Dict of facts
            location_id: Location identifier
            pollutant: Pollutant name
            target_time: End of window (exclusive)
            window_hours: Window size in hours
            field_name: Field to extract

        Returns:
            List of values (may be empty)
        """
        target_time = ensure_utc(target_time)
        values = []

        for i in range(window_hours):
            hour_time = target_time - timedelta(hours=i + 1)
            value = self._get_hourly_fact(
                facts_dict, location_id, pollutant, hour_time, field_name
            )
            if value is not None:
                values.append(value)

        return values

    def _get_rolling_window_weather(
        self,
        facts_dict: Dict,
        location_id: str,
        target_time: datetime,
        window_hours: int,
        field_name: str,
    ) -> List[float]:
        """Get weather values in a rolling window.

        Args:
            facts_dict: Dict of weather facts
            location_id: Location identifier
            target_time: End of window (exclusive)
            window_hours: Window size in hours
            field_name: Field to extract

        Returns:
            List of values (may be empty)
        """
        target_time = ensure_utc(target_time)
        values = []

        for i in range(window_hours):
            hour_time = target_time - timedelta(hours=i + 1)
            value = self._get_hourly_fact(
                facts_dict, location_id, None, hour_time, field_name
            )
            if value is not None:
                values.append(value)

        return values

    def _forward_fill_or_fallback(
        self,
        facts_dict: Dict,
        location_id: str,
        pollutant: str,
        target_hour: datetime,
        max_fill_hours: int,
        citywide_baseline: Optional[Dict],
        fallback_field: Optional[str],
    ) -> Tuple[Optional[float], bool]:
        """Forward-fill missing value or use city-wide fallback.

        Args:
            facts_dict: Dict of facts
            location_id: Location identifier
            pollutant: Pollutant name
            target_hour: Target hour (UTC)
            max_fill_hours: Max hours to look back for fill
            citywide_baseline: City-wide baseline dict
            fallback_field: Field name in baseline for fallback

        Returns:
            Tuple of (value, was_imputed)
        """
        target_hour = ensure_utc(target_hour)

        # Try forward-fill (look backward up to max_fill_hours)
        for i in range(1, max_fill_hours + 1):
            fill_time = target_hour - timedelta(hours=i)
            value = self._get_hourly_fact(
                facts_dict, location_id, pollutant, fill_time, "observed_value"
            )
            if value is not None:
                logger.debug(
                    f"Forward-filled {location_id}/{pollutant} at {target_hour} "
                    f"from {fill_time} ({i}h back)"
                )
                return value, True

        # Fall back to city-wide baseline
        if citywide_baseline and fallback_field:
            value = citywide_baseline.get(fallback_field)
            if value is not None:
                logger.debug(
                    f"Using city-wide baseline for {location_id}/{pollutant} "
                    f"at {target_hour}"
                )
                return value, True

        return None, False

    def _forward_fill_or_fallback_weather(
        self,
        facts_dict: Dict,
        location_id: str,
        target_hour: datetime,
        field_name: str,
        max_fill_hours: int,
        citywide_baseline: Optional[Dict],
    ) -> Tuple[Optional[float], bool]:
        """Forward-fill or fallback for weather features.

        Args:
            facts_dict: Dict of weather facts
            location_id: Location identifier
            target_hour: Target hour (UTC)
            field_name: Field name to extract
            max_fill_hours: Max hours to look back for fill
            citywide_baseline: City-wide baseline dict

        Returns:
            Tuple of (value, was_imputed)
        """
        target_hour = ensure_utc(target_hour)

        # Try forward-fill
        for i in range(1, max_fill_hours + 1):
            fill_time = target_hour - timedelta(hours=i)
            value = self._get_hourly_fact(
                facts_dict, location_id, None, fill_time, field_name
            )
            if value is not None:
                return value, True

        # Fall back to city-wide baseline
        if citywide_baseline:
            value = citywide_baseline.get(f"{field_name}_mean")
            if value is not None:
                return value, True

        return None, False

    @staticmethod
    def _calculate_mean(values: List[float]) -> Optional[float]:
        """Calculate mean of values.

        Args:
            values: List of numeric values

        Returns:
            Mean or None if empty
        """
        if not values:
            return None
        return sum(values) / len(values)

    @staticmethod
    def _calculate_std(values: List[float]) -> Optional[float]:
        """Calculate standard deviation.

        Args:
            values: List of numeric values

        Returns:
            Std dev or None if empty
        """
        if not values or len(values) < 2:
            return None

        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return math.sqrt(variance)

    @staticmethod
    def _calculate_max(values: List[float]) -> Optional[float]:
        """Calculate maximum.

        Args:
            values: List of numeric values

        Returns:
            Max or None if empty
        """
        if not values:
            return None
        return max(values)
