"""Regression test for direct runtime dependency declarations."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_pytz_is_declared_as_a_runtime_dependency():
    with open(ROOT / "pyproject.toml", "rb") as file:
        pyproject = tomllib.load(file)

    dependencies = pyproject["project"]["dependencies"]
    names = {
        dependency.split("==")[0].split(">=")[0].split("[")[0].strip()
        for dependency in dependencies
    }

    assert "pytz" in names
