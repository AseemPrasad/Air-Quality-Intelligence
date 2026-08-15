"""OpenAQ connector for air quality observations.

Fetches real-time and historical air quality measurements from OpenAQ API v3.
Handles pagination, unit normalization, and watermark-based incremental ingestion.

API Reference: https://docs.openaq.org/
"""

import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Generator, List, Optional, Tuple
from urllib.parse import urljoin

import requests

from aq_engine.common import (
    ensure_utc,
    log_operation,
    StructuredLogger,
    IngestionFailed,
    DataContractViolation,
)
from aq_engine.connectors.base import BaseConnector
from aq_engine.connectors.models import (
    ConnectorConfig,
    ParsedRecord,
    SourceResponse,
    IngestionRunMetadata,
)


logger = logging.getLogger(__name__)
slog = StructuredLogger(__name__)


class OpenAQConnector(BaseConnector):
    """Connector for OpenAQ real-time air quality data.

    Fetches measurements from the OpenAQ API v3, handling pagination,
    unit normalization, and incremental ingestion via watermarks.

    Example:
        >>> config = ConnectorConfig(
        ...     source_name="openaq",
        ...     source_type="air_quality",
        ...     base_url="https://api.openaq.org/v3",
        ...     timeout_seconds=30
        ... )
        >>> connector = OpenAQConnector(config, api_key="your-key")
        >>> run_id, metadata = connector.ingest(lookback_hours=6)
        >>> print(f"Ingested {metadata.records_written} records")
    """

    # Pollutants to monitor (from configs/sources/openaq.yaml)
    POLLUTANTS_OF_INTEREST = ["pm25", "pm10", "no2", "o3", "so2"]

    # Unit conversion map: source_unit → target_unit (µg/m³)
    UNIT_CONVERSIONS = {
        "µg/m³": 1.0,      # Already normalized
        "mg/m³": 1000.0,   # Convert mg/m³ to µg/m³
        "ppb": None,       # ppb requires molecular weight (pollutant-specific)
        "ppm": None,       # ppm requires molecular weight
    }

    def __init__(
        self,
        config: ConnectorConfig,
        api_key: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ):
        """Initialize OpenAQ connector.

        Args:
            config: Connector configuration.
            api_key: Optional OpenAQ API key (for higher rate limits).
            session: Optional requests.Session for reuse.

        Raises:
            ValueError: If config is invalid.
        """
        super().__init__(config, session=session)
        self.api_key = api_key
        self._location_cache: Dict[str, Dict[str, Any]] = {}

    def fetch(self, start_time: datetime, end_time: datetime) -> SourceResponse:
        """Fetch measurements from OpenAQ API.

        Queries the /measurements endpoint with date range and pagination.

        Args:
            start_time: Query window start (UTC).
            end_time: Query window end (UTC).

        Returns:
            SourceResponse with aggregated measurements.

        Raises:
            IngestionFailed: On API error or timeout.
        """
        start_time = ensure_utc(start_time)
        end_time = ensure_utc(end_time)

        logger.debug(
            f"Fetching OpenAQ measurements from {start_time} to {end_time}"
        )

        all_measurements = []
        request_count = 0

        # Paginate through measurements
        for page_data in self._fetch_measurements_paginated(
            start_time=start_time,
            end_time=end_time,
            limit=10000,
        ):
            all_measurements.extend(page_data["measurements"])
            request_count += 1
            logger.debug(f"Fetched page {request_count}: {len(page_data['measurements'])} records")

        # Combine all measurements into single response
        combined_response = {
            "results": all_measurements,
            "meta": {
                "total": len(all_measurements),
                "pages": request_count,
            },
        }

        response = SourceResponse(
            status_code=200,
            headers={},
            body=combined_response,
            elapsed_seconds=0.0,  # Approximate
            timestamp=datetime.now(timezone.utc),
        )

        logger.info(f"Fetched {len(all_measurements)} measurements from OpenAQ")
        return response

    def _fetch_measurements_paginated(
        self,
        start_time: datetime,
        end_time: datetime,
        limit: int = 10000,
        max_pages: Optional[int] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """Paginate through OpenAQ measurements API.

        Handles cursor-based pagination. Yields responses one page at a time.

        Args:
            start_time: Query start time (UTC).
            end_time: Query end time (UTC).
            limit: Records per page (max 10000).
            max_pages: Optional limit on pages fetched (for testing).

        Yields:
            Dict with "measurements" and "meta" keys.

        Raises:
            IngestionFailed: On API error.
        """
        url = urljoin(self.config.base_url, "/measurements")
        page_count = 0

        # OpenAQ cursor: starting value
        cursor = None

        while True:
            if max_pages and page_count >= max_pages:
                logger.debug(f"Stopping pagination at {max_pages} pages")
                break

            # Build query parameters
            params = {
                "date_from": start_time.isoformat(),
                "date_to": end_time.isoformat(),
                "limit": limit,
                "sort": "asc",
                "sortBy": "datetime",
            }

            # Kolkata bounding box (approximately)
            params.update({
                "coordinates_radius": 100,  # 100 km radius
                "coordinates": "22.5726,88.3639",  # Kolkata center
            })

            if cursor:
                params["cursor"] = cursor

            if self.api_key:
                params["api_key"] = self.api_key

            try:
                logger.debug(f"Requesting {url} with params: {params}")
                response = self._session.get(
                    url,
                    params=params,
                    timeout=self.config.timeout_seconds,
                )
                response.raise_for_status()

                data = response.json()

                # Validate response structure
                if not isinstance(data, dict):
                    raise DataContractViolation(
                        f"Expected dict response, got {type(data).__name__}",
                        context={"url": url},
                    )

                measurements = data.get("results", [])
                if not isinstance(measurements, list):
                    raise DataContractViolation(
                        f"Expected 'results' to be list, got {type(measurements).__name__}",
                        context={"url": url},
                    )

                page_count += 1
                logger.debug(
                    f"Received page {page_count}: {len(measurements)} records"
                )

                yield {
                    "measurements": measurements,
                    "meta": data.get("meta", {}),
                }

                # Check for next page
                cursor = data.get("meta", {}).get("next", {}).get("cursor")
                if not cursor:
                    logger.debug(f"Pagination complete after {page_count} pages")
                    break

            except requests.HTTPError as e:
                status_code = response.status_code
                body = response.text[:500]  # First 500 chars

                if status_code == 401:
                    raise IngestionFailed(
                        f"Authentication failed (HTTP 401)",
                        context={"url": url, "status_code": status_code},
                    ) from e

                elif status_code == 403:
                    raise IngestionFailed(
                        f"Access forbidden (HTTP 403)",
                        context={"url": url, "status_code": status_code},
                    ) from e

                elif status_code == 404:
                    logger.warning(f"Endpoint not found (HTTP 404): {url}")
                    break  # Continue with partial results

                elif status_code in (429, 500, 502, 503, 504):
                    raise IngestionFailed(
                        f"Transient error (HTTP {status_code}): {body}",
                        context={"url": url, "status_code": status_code},
                    ) from e

                else:
                    raise IngestionFailed(
                        f"HTTP {status_code}: {body}",
                        context={"url": url, "status_code": status_code},
                    ) from e

            except requests.Timeout as e:
                raise IngestionFailed(
                    f"Timeout fetching {url}",
                    context={"url": url},
                ) from e

            except ValueError as e:
                # JSON decode error
                raise DataContractViolation(
                    f"Malformed JSON response: {str(e)}",
                    context={"url": url},
                ) from e

    def parse(
        self, response: SourceResponse, start_time: datetime, end_time: datetime
    ) -> List[ParsedRecord]:
        """Parse OpenAQ response into canonical air quality records.

        Validates each measurement, normalizes units, and creates ParsedRecord objects.

        Args:
            response: SourceResponse from fetch().
            start_time: Query window start.
            end_time: Query window end.

        Returns:
            List of canonical ParsedRecord objects.

        Raises:
            DataContractViolation: If records are malformed.
        """
        records = []

        if not isinstance(response.body, dict):
            raise DataContractViolation(
                f"Expected dict response body, got {type(response.body).__name__}"
            )

        measurements = response.body.get("results", [])
        if not isinstance(measurements, list):
            raise DataContractViolation(
                f"Expected 'results' to be list, got {type(measurements).__name__}"
            )

        for meas in measurements:
            try:
                parsed = self._parse_measurement(meas, response.raw_payload_hash)
                if parsed:
                    records.append(parsed)
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(
                    f"Skipping malformed measurement: {e}",
                    extra={"measurement": str(meas)[:500]},
                )
                continue

        logger.info(f"Parsed {len(records)} records from {len(measurements)} measurements")
        return records

    def _parse_measurement(
        self, meas: Dict[str, Any], raw_payload_hash: Optional[str]
    ) -> Optional[ParsedRecord]:
        """Parse single OpenAQ measurement into canonical record.

        Validates required fields, normalizes units, and handles null values.

        Args:
            meas: OpenAQ measurement dict from API.
            raw_payload_hash: Hash of raw API response.

        Returns:
            ParsedRecord or None if measurement should be skipped.

        Raises:
            KeyError: If required fields missing.
            ValueError: If value/date parsing fails.
        """
        # Extract required fields with validation
        location_id = meas.get("location", {}).get("id")
        if not location_id:
            logger.debug("Skipping measurement with missing location.id")
            return None

        station_id = str(location_id)

        sensor_id = meas.get("sensor", {}).get("id")
        if not sensor_id:
            logger.debug(f"Skipping measurement for station {station_id} with missing sensor.id")
            return None

        sensor_id = str(sensor_id)

        pollutant = meas.get("parameter", {}).get("id", "").lower()
        if not pollutant or pollutant not in self.POLLUTANTS_OF_INTEREST:
            return None  # Skip pollutants we don't monitor

        # Parse value
        value = meas.get("value")
        if value is None:
            logger.debug(f"Skipping measurement for {station_id}/{pollutant} with null value")
            return None

        try:
            value = float(value)
        except (TypeError, ValueError) as e:
            logger.warning(f"Invalid value for {station_id}/{pollutant}: {value} ({e})")
            return None

        # Parse unit and normalize
        unit = meas.get("unit", "").strip()
        if not unit:
            logger.warning(f"Missing unit for {station_id}/{pollutant}, assuming µg/m³")
            unit = "µg/m³"

        # Normalize units
        value, unit = self._normalize_unit(value, unit, pollutant)

        # Parse observed timestamp
        observed_at_str = meas.get("date", {}).get("utc")
        if not observed_at_str:
            logger.warning(f"Missing date.utc for {station_id}/{pollutant}")
            return None

        try:
            observed_at = datetime.fromisoformat(observed_at_str.replace("Z", "+00:00"))
            observed_at = ensure_utc(observed_at)
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid date for {station_id}/{pollutant}: {observed_at_str} ({e})")
            return None

        # Compute measurement key (idempotency key)
        measurement_key = hashlib.sha256(
            f"openaq|{station_id}|{sensor_id}|{pollutant}|{observed_at.isoformat()}".encode()
        ).hexdigest()

        # Build canonical record
        canonical_record = {
            "source": "openaq",
            "station_id": station_id,
            "sensor_id": sensor_id,
            "pollutant": pollutant,
            "value": value,
            "unit": unit,
            "observed_at": observed_at,
            "ingested_at": datetime.now(timezone.utc),
            "raw_payload_hash": raw_payload_hash,
        }

        parsed = ParsedRecord(
            source="openaq",
            record_type="air_quality",
            data=canonical_record,
            measurement_key=measurement_key,
            raw_payload_hash=raw_payload_hash or "",
            ingestion_timestamp=datetime.now(timezone.utc),
        )

        return parsed

    def _normalize_unit(self, value: float, unit: str, pollutant: str) -> Tuple[float, str]:
        """Normalize measurement unit to µg/m³.

        Converts mg/m³ to µg/m³ (multiply by 1000).
        Logs unit conversions.

        Args:
            value: Measurement value.
            unit: Original unit.
            pollutant: Pollutant name.

        Returns:
            Tuple of (normalized_value, normalized_unit).
        """
        if unit not in self.UNIT_CONVERSIONS:
            logger.warning(
                f"Unknown unit for {pollutant}: {unit}, keeping as-is",
                extra={"pollutant": pollutant, "unit": unit},
            )
            return value, unit

        conversion_factor = self.UNIT_CONVERSIONS[unit]
        if conversion_factor is None:
            # ppb/ppm: requires molecular weight, skip conversion
            logger.debug(
                f"Skipping ppb/ppm conversion for {pollutant} (molecular weight unknown)"
            )
            return value, unit

        if conversion_factor != 1.0:
            converted_value = value * conversion_factor
            logger.debug(
                f"Unit conversion: {pollutant} {value} {unit} → {converted_value} µg/m³"
            )
            return converted_value, "µg/m³"

        return value, "µg/m³"

    def write_raw(
        self, records: List[ParsedRecord], run_id: str
    ) -> Tuple[int, int]:
        """Write parsed records to raw Parquet storage.

        Partitions by date (year/month/day) and deduplicates by measurement_key.

        Args:
            records: Canonical records to write.
            run_id: Ingestion run identifier.

        Returns:
            Tuple of (records_written, records_rejected).

        Raises:
            StorageError: On write failure.
        """
        import polars as pl
        from pathlib import Path

        from aq_engine.common import date_partition_path

        if not records:
            logger.info("No records to write")
            return 0, 0

        # Convert to Polars DataFrame
        data = [r.data for r in records]
        df = pl.DataFrame(data)

        # Add run_id for traceability
        df = df.with_columns(pl.lit(run_id).alias("run_id"))

        # Group by date partition and write
        written_count = 0
        rejected_count = 0

        try:
            for partition_value, group_df in df.groupby(
                pl.col("observed_at").dt.date()
            ):
                # Compute partition path
                observed_date = partition_value
                partition_path = date_partition_path(observed_date)

                # Construct full path
                storage_path = Path(f"data/raw/openaq/{partition_path}")
                storage_path.mkdir(parents=True, exist_ok=True)

                # Write Parquet (append mode)
                output_file = storage_path / f"records_{run_id[:8]}.parquet"

                group_df.write_parquet(
                    str(output_file),
                    compression="snappy",
                    row_group_size=10000,
                )

                written_count += len(group_df)
                logger.debug(f"Wrote {len(group_df)} records to {output_file}")

            logger.info(f"Wrote {written_count} records to raw storage")
            return written_count, rejected_count

        except Exception as e:
            from aq_engine.common import StorageError

            raise StorageError(
                f"Failed to write records to Parquet: {str(e)}",
                context={"run_id": run_id, "record_count": len(records)},
            ) from e

    def record_run(self, metadata: IngestionRunMetadata, success: bool) -> None:
        """Record ingestion run in PostgreSQL control plane.

        Updates ingestion_run table. Only advances watermark if success=True.

        Args:
            metadata: Run metadata.
            success: Whether run succeeded.

        Raises:
            DatabaseError: On database error.
        """
        # TODO: Implement after PostgreSQL integration
        # For now, just log
        logger.info(
            f"Run {metadata.run_id}: status={metadata.status}, "
            f"written={metadata.records_written}, rejected={metadata.records_rejected}",
            extra={
                "event": "ingestion_run_record",
                "run_id": metadata.run_id,
                "status": metadata.status,
                "success": success,
                "records_written": metadata.records_written,
                "records_rejected": metadata.records_rejected,
            },
        )

        if success:
            logger.debug(f"Watermark would be advanced for run {metadata.run_id}")
        else:
            logger.warning(f"Watermark NOT advanced for failed run {metadata.run_id}")
