"""Regression tests for batch source type validation."""

import pytest

from aq_engine.quality.validator import QualityValidator


def test_validate_batch_rejects_unknown_source_type():
    validator = QualityValidator()

    with pytest.raises(ValueError, match="Unsupported source_type 'unknown'"):
        validator.validate_batch([], source_type="unknown")


def test_validate_batch_accepts_supported_source_types(monkeypatch):
    validator = QualityValidator()
    monkeypatch.setattr(validator, "validate_air_quality", lambda record: (validator.VALID, []))
    monkeypatch.setattr(validator, "validate_weather", lambda record: (validator.VALID, []))

    assert validator.validate_batch([{}], source_type="air_quality")[validator.VALID] == 1
    assert validator.validate_batch([{}], source_type="weather")[validator.VALID] == 1
