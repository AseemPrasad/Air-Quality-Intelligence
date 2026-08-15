"""Quarantine handling for invalid/suspicious records.

Routes records to data/quarantine/{source}/year=YYYY/month=MM/day=DD/
with rejection reason, rule metadata, and timestamps for investigation.
"""

import logging
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple, Dict, Any

from aq_engine.common import date_partition_path

logger = logging.getLogger(__name__)


class QuarantineManager:
    """Manages quarantine storage for invalid/suspicious records."""

    def __init__(self, quarantine_root: str = "data/quarantine"):
        """Initialize quarantine manager.

        Args:
            quarantine_root: Root path for quarantine storage.
        """
        self.quarantine_root = Path(quarantine_root)
        self.quarantine_root.mkdir(parents=True, exist_ok=True)

    def quarantine_invalid_records(
        self,
        source: str,
        records: List[Tuple[dict, List[str]]],
        record_type: str = "air_quality",
    ) -> None:
        """Write invalid records to quarantine storage.

        Args:
            source: Data source name (e.g., "openaq").
            records: List of (record, reasons) tuples.
            record_type: "air_quality" or "weather".

        Example:
            >>> manager = QuarantineManager()
            >>> records = [
            ...     ({"value": -5, ...}, ["Pollutant value must be non-negative"]),
            ... ]
            >>> manager.quarantine_invalid_records("openaq", records)
        """
        if not records:
            return

        # Enrich records with quarantine metadata
        enriched_records = []
        for record, reasons in records:
            quarantined = {
                **record,
                "quarantine_timestamp": datetime.now(timezone.utc).isoformat(),
                "rejection_reasons": reasons,
                "record_type": record_type,
            }
            enriched_records.append(quarantined)

        # Get observed_at or ingested_at for partitioning
        timestamp = enriched_records[0].get("observed_at") or enriched_records[0].get("ingested_at")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        # Write to quarantine partitioned by source + date
        partition_path = date_partition_path(timestamp)
        target_dir = self.quarantine_root / source / partition_path

        # Write as JSONL for investigation (more human-readable)
        self._write_quarantine_jsonl(target_dir, enriched_records, source)

        logger.info(
            f"Quarantined {len(enriched_records)} invalid {record_type} records "
            f"from {source} to {target_dir}"
        )

    def quarantine_suspicious_records(
        self,
        source: str,
        records: List[Tuple[dict, List[str]]],
        record_type: str = "air_quality",
    ) -> None:
        """Write suspicious records to quarantine for review.

        Args:
            source: Data source name.
            records: List of (record, warnings) tuples.
            record_type: "air_quality" or "weather".
        """
        if not records:
            return

        enriched_records = []
        for record, warnings in records:
            quarantined = {
                **record,
                "quarantine_timestamp": datetime.now(timezone.utc).isoformat(),
                "warnings": warnings,
                "record_type": record_type,
                "quarantine_reason": "SUSPICIOUS",
            }
            enriched_records.append(quarantined)

        timestamp = enriched_records[0].get("observed_at") or enriched_records[0].get("ingested_at")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        partition_path = date_partition_path(timestamp)
        target_dir = self.quarantine_root / source / "suspicious" / partition_path

        self._write_quarantine_jsonl(target_dir, enriched_records, source)

        logger.info(
            f"Quarantined {len(enriched_records)} suspicious {record_type} records "
            f"from {source} to {target_dir}"
        )

    def _write_quarantine_jsonl(
        self, target_dir: Path, records: List[dict], source: str
    ) -> None:
        """Write records to JSONL format for investigation.

        Args:
            target_dir: Target directory path.
            records: List of records to write.
            source: Source name (used for filename).
        """
        target_dir.mkdir(parents=True, exist_ok=True)

        # Use timestamp-based filename to avoid collisions
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"{source}_quarantine_{timestamp}.jsonl"
        filepath = target_dir / filename

        with open(filepath, "w") as f:
            for record in records:
                f.write(json.dumps(record, default=str) + "\n")

        logger.debug(f"Wrote {len(records)} quarantine records to {filepath}")

    def read_quarantine_records(
        self, source: str, record_type: str = "invalid"
    ) -> List[dict]:
        """Read quarantine records for investigation.

        Args:
            source: Source name to read from.
            record_type: "invalid" or "suspicious".

        Returns:
            List of quarantine records.
        """
        if record_type == "suspicious":
            search_path = self.quarantine_root / source / "suspicious"
        else:
            search_path = self.quarantine_root / source

        records = []
        for filepath in search_path.glob("**/*.jsonl"):
            try:
                with open(filepath, "r") as f:
                    for line in f:
                        if line.strip():
                            records.append(json.loads(line))
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to read {filepath}: {e}")

        return records

    def get_quarantine_stats(self, source: str) -> Dict[str, int]:
        """Get quarantine statistics for source.

        Returns:
            Dict with counts of invalid/suspicious records.
        """
        invalid_path = self.quarantine_root / source
        suspicious_path = self.quarantine_root / source / "suspicious"

        invalid_files = list(invalid_path.glob("**/*.jsonl"))
        # Filter out suspicious files from invalid count
        invalid_files = [f for f in invalid_files if "suspicious" not in f.parts]

        suspicious_files = list(suspicious_path.glob("**/*.jsonl"))

        invalid_count = sum(self._count_jsonl_lines(f) for f in invalid_files)
        suspicious_count = sum(self._count_jsonl_lines(f) for f in suspicious_files)

        return {
            "invalid": invalid_count,
            "suspicious": suspicious_count,
            "total": invalid_count + suspicious_count,
        }

    @staticmethod
    def _count_jsonl_lines(filepath: Path) -> int:
        """Count lines in JSONL file."""
        try:
            with open(filepath, "r") as f:
                return sum(1 for _ in f if _.strip())
        except IOError:
            return 0
