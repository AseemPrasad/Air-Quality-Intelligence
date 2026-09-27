"""The control-plane schema must work on SQLite, which the test suite uses.

Two column types only worked on PostgreSQL: ``postgresql.UUID`` (SQLite cannot
compile it, so ``create_tables`` failed) and BIGINT surrogate keys (SQLite only
auto-increments ``INTEGER PRIMARY KEY``, so every insert hit NOT NULL).
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql

from aq_engine.storage.db import (
    Database,
    IngestionRun,
    IngestionRunRepository,
    Source,
)


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'control.db'}", echo=False)
    database.create_tables()
    yield database
    database.drop_tables()


def test_create_tables_and_autoincrement_keys_on_sqlite(db):
    with db.session() as session:
        session.add(Source(source_name="openaq", source_type="air_quality"))
        session.add(Source(source_name="open_meteo", source_type="weather"))

    with db.session() as session:
        ids = sorted(s.source_id for s in session.query(Source).all())

    assert ids == [1, 2]


def test_record_run_accepts_the_string_run_id_the_orchestrator_passes(db):
    with db.session() as session:
        session.add(Source(source_name="openaq", source_type="air_quality"))

    run_id = str(uuid4())
    IngestionRunRepository(db).record_run(
        run_id=run_id,
        source_id=1,
        started_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
        status="success",
    )

    with db.session() as session:
        stored = session.query(IngestionRun).one().run_id

    assert stored == UUID(run_id)


def test_postgres_still_gets_native_uuid_and_bigint():
    dialect = postgresql.dialect()

    run_id_type = IngestionRun.__table__.c.run_id.type.compile(dialect=dialect)
    source_id_type = Source.__table__.c.source_id.type.compile(dialect=dialect)

    assert run_id_type == "UUID"
    assert source_id_type == "BIGINT"
