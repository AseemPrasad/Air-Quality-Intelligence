"""An in-memory SQLite Database must keep one database across connections.

``sqlite:///:memory:`` is what the tests and local runs use. With a connection
pool, each new connection opened its own empty database, so tables created by
``create_tables()`` were missing when another connection was checked out.
"""

from sqlalchemy import Column, Integer, String, text
from sqlalchemy.orm import declarative_base

from aq_engine.storage.db import Database

_Base = declarative_base()


class _Probe(_Base):
    __tablename__ = "probe"

    probe_id = Column(Integer, primary_key=True)
    name = Column(String(20))


def test_table_created_on_one_connection_is_visible_on_others():
    db = Database("sqlite:///:memory:", echo=False)
    _Base.metadata.create_all(db.engine)

    # Hold one connection open so the next checkout cannot reuse it.
    with db.engine.connect() as first, db.engine.connect() as second:
        first.execute(text("INSERT INTO probe (probe_id, name) VALUES (1, 'a')"))
        first.commit()
        rows = second.execute(text("SELECT name FROM probe")).all()

    assert rows == [("a",)]


def test_file_backed_sqlite_still_uses_a_pool(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'file.db'}", echo=False)

    assert type(db.engine.pool).__name__ == "QueuePool"
