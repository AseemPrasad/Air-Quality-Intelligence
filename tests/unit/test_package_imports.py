"""Regression tests for package-level imports."""

import os
import subprocess
import sys
from pathlib import Path


def test_storage_can_be_imported_before_quality():
    """Storage and quality public APIs must not depend on import order."""
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from aq_engine.storage import ParquetWriter; "
                "from aq_engine.quality import Deduplicator"
            ),
        ],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
