"""The installed ``aq`` console script must be importable outside the repo root.

``cli.py`` imported its siblings as ``src.aq_engine.*``. That only resolves when
the repository root happens to be on ``sys.path`` (pytest, ``python -c`` from the
checkout). The console script ``aq = "aq_engine.cli:cli_app"`` runs from anywhere,
so it failed with ``ModuleNotFoundError: No module named 'src'``.
"""

import subprocess
import sys


def test_cli_module_imports_from_outside_the_repository(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", "from aq_engine.cli import cli_app; print(cli_app.info.name)"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "No module named 'src'" not in result.stderr
