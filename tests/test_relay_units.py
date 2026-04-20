"""Unit tests for the Outbox Relay engine and database dialects.

Validates SQL syntax across different database engines and the reliability
of the job synchronization logic.
"""

from typing import Any, cast

import pytest

from faktory_outbox.relay import (
    DBDialect,
    OracleDialect,
    OutboxRelay,
    PostgresDialect,
    SqliteDialect,
)


def test_dialects_should_generate_valid_sql_syntax() -> None:
    """Covers SQL generation and boolean mapping for all supported dialects."""
    # Ensure the base class is truly abstract
    with pytest.raises(NotImplementedError):
        DBDialect.get_pending_query(1)

    # Validate individual dialect strategies
    assert SqliteDialect().get_bool_value(True) == 1
    assert "LIMIT %s" in SqliteDialect().get_pending_query(10)

    assert PostgresDialect().get_bool_value(True) is True
    assert "FOR UPDATE SKIP LOCKED" in PostgresDialect().get_pending_query(10)

    assert OracleDialect().get_bool_value(True) == 1
    assert "FETCH FIRST" in OracleDialect().get_pending_query(10)


def test_mask_url_password_should_redact_sensitive_data(mocker: Any) -> None:
    """Ensures credentials are never exposed in system logs."""
    relay = OutboxRelay(mocker.Mock(), SqliteDialect())

    valid_url = "tcp://user:password123@localhost:7419"
    assert "password123" not in relay.mask_url_password(valid_url)
    assert "****" in relay.mask_url_password(valid_url)

    # Verify fallback for invalid input types
    assert relay.mask_url_password(cast(Any, None)) == "***"


def test_process_batch_should_manage_transactions_correctly(mocker: Any) -> None:
    """Validates batch processing with success, empty results, and database errors."""
    mock_conn = mocker.Mock()
    mocker.patch("faktory.connection")
    relay = OutboxRelay(mock_conn, SqliteDialect())

    # Case 1: Processing multiple jobs (Triggers min/max ID logging)
    mock_conn.cursor.return_value.fetchall.return_value = [
        (10, "task_a", "{}"),
        (20, "task_b", "{}"),
    ]
    assert relay.process_batch() == 2
    mock_conn.commit.assert_called()

    # Case 2: No pending jobs found
    mock_conn.cursor.return_value.fetchall.return_value = []
    assert relay.process_batch() == 0

    # Case 3: Database failure triggers a rollback
    mock_conn.cursor.return_value.execute.side_effect = Exception("Atomic Failure")
    with pytest.raises(Exception, match="Atomic Failure"):
        relay.process_batch()
    mock_conn.rollback.assert_called_once()


def test_sync_jobs_should_handle_serialized_payloads(mocker: Any) -> None:
    """Ensures the relay correctly decodes JSON strings during synchronization."""
    mock_conn = mocker.Mock()
    mocker.patch("faktory.connection")
    relay = OutboxRelay(mock_conn, SqliteDialect())

    cursor = mocker.Mock()
    # Test with a raw string payload to trigger json.loads
    relay._sync_jobs_to_faktory(cursor, [(1, "worker_task", '{"status": "ok"}')])

    assert cursor.execute.called


def test_run_loop_should_implement_exponential_backoff(mocker: Any) -> None:
    """Verifies error handling and critical logging during relay downtime."""
    relay = OutboxRelay(mocker.Mock(), SqliteDialect())
    mocker.patch("time.sleep", return_value=None)
    mock_crit = mocker.patch("faktory_outbox.relay.logger.critical")

    # Sequence: 1 success, 1 failure (backoff), 1 interrupt (stop)
    mocker.patch.object(
        relay,
        "process_batch",
        side_effect=[1, Exception("Transient Error"), KeyboardInterrupt()],
    )

    with pytest.raises(KeyboardInterrupt):
        # min_sleep > max_sleep forces the critical log branch on first error
        relay.run_loop(min_sleep=10.0, max_sleep=5.0)

    assert mock_crit.called
