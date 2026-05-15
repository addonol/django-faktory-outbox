"""Unit tests for checking database dialect SQL string generation."""

import pytest

from faktory_outbox.dialects import (
    BaseDialect,
    MariaDbDialect,
    OracleDialect,
    PostgresDialect,
    SqliteDialect,
)


def test_base_dialect_raises_not_implemented_error() -> None:
    """Ensures the abstract BaseDialect forces parameter style overrides."""
    dialect = BaseDialect()
    with pytest.raises(NotImplementedError):
        _ = dialect.param_style


def test_sqlite_dialect_properties() -> None:
    """Validates query format behaviors unique to the SQLite dialect."""
    dialect = SqliteDialect()
    assert dialect.param_style == "?"
    assert dialect.get_bool_value(True) == 1
    assert dialect.get_bool_value(False) == 0

    query = dialect.get_pending_query(10)
    assert "LIMIT ?" in query
    assert "FOR UPDATE SKIP LOCKED" not in query


def test_postgres_dialect_properties() -> None:
    """Validates query format behaviors unique to the Postgres dialect."""
    dialect = PostgresDialect()
    assert dialect.param_style == "%s"
    assert dialect.get_bool_value(True) is True

    query = dialect.get_pending_query(50)
    assert "LIMIT %s" in query
    assert "FOR UPDATE SKIP LOCKED" in query


def test_mariadb_dialect_properties() -> None:
    """Validates query format behaviors unique to the MariaDB dialect."""
    dialect = MariaDbDialect()
    assert dialect.param_style == "%s"
    assert dialect.get_bool_value(True) is True

    query = dialect.get_pending_query(25)
    assert "LIMIT %s" in query
    assert "FOR UPDATE SKIP LOCKED" in query


def test_oracle_dialect_properties() -> None:
    """Validates query format behaviors unique to the Oracle dialect."""
    dialect = OracleDialect()
    assert dialect.param_style == ":1"
    assert dialect.get_bool_value(True) == 1

    query = dialect.get_pending_query(5)
    assert "FETCH FIRST :1 ROWS ONLY" in query
    assert "FOR UPDATE SKIP LOCKED" in query
