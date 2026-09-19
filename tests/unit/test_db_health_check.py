"""Database.health_check must actually probe the connection."""

from aq_engine.storage.db import Database


def test_health_check_passes_for_a_reachable_database(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'health.db'}", echo=False)

    assert db.health_check() is True


def test_health_check_fails_for_an_unreachable_database(tmp_path):
    missing_dir = tmp_path / "does-not-exist" / "health.db"
    db = Database(f"sqlite:///{missing_dir}", echo=False)

    assert db.health_check() is False
