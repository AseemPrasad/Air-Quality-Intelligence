"""Regression tests for documented PostgreSQL environment overrides."""

from pathlib import Path

from aq_engine.config import ConfigLoader

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"


def _clear_database_env(monkeypatch):
    for name in (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "DATABASE_HOST",
        "DATABASE_PORT",
    ):
        monkeypatch.delenv(name, raising=False)


def test_postgres_host_and_port_override_yaml(monkeypatch):
    _clear_database_env(monkeypatch)
    monkeypatch.setenv("POSTGRES_HOST", "postgres")
    monkeypatch.setenv("POSTGRES_PORT", "6543")

    config = ConfigLoader(str(CONFIG_DIR)).load()

    assert config.database.host == "postgres"
    assert config.database.port == 6543


def test_database_names_remain_supported_as_fallbacks(monkeypatch):
    _clear_database_env(monkeypatch)
    monkeypatch.setenv("DATABASE_HOST", "legacy-host")
    monkeypatch.setenv("DATABASE_PORT", "5544")

    config = ConfigLoader(str(CONFIG_DIR)).load()

    assert config.database.host == "legacy-host"
    assert config.database.port == 5544


def test_postgres_values_take_precedence_over_legacy_names(monkeypatch):
    _clear_database_env(monkeypatch)
    monkeypatch.setenv("POSTGRES_HOST", "preferred-host")
    monkeypatch.setenv("POSTGRES_PORT", "6432")
    monkeypatch.setenv("DATABASE_HOST", "legacy-host")
    monkeypatch.setenv("DATABASE_PORT", "5544")

    config = ConfigLoader(str(CONFIG_DIR)).load()

    assert config.database.host == "preferred-host"
    assert config.database.port == 6432
