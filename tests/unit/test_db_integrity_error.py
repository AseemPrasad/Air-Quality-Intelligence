"""Regression tests for transaction error reporting."""

import pytest

from aq_engine.common import DatabaseError
from aq_engine.storage.db import Database, Source


def test_integrity_error_is_raised_to_the_caller():
    db = Database("sqlite:///:memory:")
    db.create_tables()

    try:
        with db.session() as session:
            session.add(Source(source_name="duplicate", source_type="air_quality"))

        with pytest.raises(DatabaseError) as exc_info:
            with db.session() as session:
                session.add(Source(source_name="duplicate", source_type="air_quality"))

        assert exc_info.value.context["integrity_error"] is True

        with db.session() as session:
            assert session.query(Source).count() == 1
    finally:
        db.drop_tables()
