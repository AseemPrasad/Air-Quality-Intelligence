"""Objects returned from Database.session() must stay readable after it closes.

The repositories (``LocationRepository.get_or_create``, ``record_run``, ...) return
ORM instances created or loaded inside ``session()``, which commits and closes the
session before returning.
"""

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

from aq_engine.storage.db import Database

_Base = declarative_base()


class _Widget(_Base):
    __tablename__ = "widget"

    widget_id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)


def _db(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'objects.db'}", echo=False)
    _Base.metadata.create_all(db.engine)
    return db


def test_created_object_is_readable_after_the_session_commits(tmp_path):
    db = _db(tmp_path)

    with db.session() as session:
        widget = _Widget(widget_id=1, name="sensor")
        session.add(widget)
        session.flush()

    assert widget.widget_id == 1
    assert widget.name == "sensor"


def test_loaded_object_is_readable_after_the_session_commits(tmp_path):
    db = _db(tmp_path)
    with db.session() as session:
        session.add(_Widget(widget_id=2, name="station"))

    with db.session() as session:
        loaded = session.query(_Widget).filter_by(widget_id=2).one()

    assert loaded.name == "station"
