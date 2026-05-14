"""Unit tests for the Outbox Relay engine and database dialects.

Validates SQL syntax across different database engines and the
reliability of the job synchronization logic.
"""

import sys
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
    """Covers SQL generation and boolean mapping for all dialects."""
    with pytest.raises(NotImplementedError):
        DBDialect.get_pending_query(1)

    assert SqliteDialect().get_bool_value(True) == 1
    assert "LIMIT ?" in SqliteDialect().get_pending_query(10)

    assert PostgresDialect().get_bool_value(True) is True
    assert "FOR UPDATE SKIP LOCKED" in PostgresDialect().get_pending_query(10)

    assert OracleDialect().get_bool_value(True) == 1
    assert "FETCH FIRST" in OracleDialect().get_pending_query(10)


def test_mask_url_password_should_redact_sensitive_data(
    mocker: Any,
) -> None:
    """Ensures credentials are never exposed in system logs."""
    relay = OutboxRelay(mocker.Mock(), SqliteDialect())

    valid_url = "tcp://user:password123@localhost:7419"
    assert "password123" not in relay.mask_url_password(valid_url)
    assert "****" in relay.mask_url_password(valid_url)
    assert relay.mask_url_password(cast(Any, None)) == "***"


def test_process_batch_should_manage_transactions_correctly(
    mocker: Any,
) -> None:
    """Validates batch processing with success, empty, and errors."""
    mock_conn = mocker.Mock()
    mocker.patch("faktory.connection")
    relay = OutboxRelay(mock_conn, SqliteDialect())

    mock_conn.cursor.return_value.fetchall.return_value = [
        (10, "task_a", "{}"),
        (20, "task_b", "{}"),
    ]
    assert relay.process_batch() == 2
    mock_conn.commit.assert_called()

    mock_conn.cursor.return_value.fetchall.return_value = []
    assert relay.process_batch() == 0

    mock_conn.cursor.return_value.execute.side_effect = Exception("Atomic Failure")
    with pytest.raises(Exception, match="Atomic Failure"):
        relay.process_batch()
    mock_conn.rollback.assert_called_once()


def test_sync_jobs_should_handle_serialized_payloads(
    mocker: Any,
) -> None:
    """Ensures the relay decodes JSON strings during sync."""
    mock_conn = mocker.Mock()
    mocker.patch("faktory.connection")
    relay = OutboxRelay(mock_conn, SqliteDialect())

    cursor = mocker.Mock()
    relay._sync_jobs_to_faktory(cursor, [(1, "worker_task", '{"status": "ok"}')])
    assert cursor.execute.called


def test_run_loop_should_implement_exponential_backoff(
    mocker: Any,
) -> None:
    """Verifies error handling and critical logging during downtime."""
    relay = OutboxRelay(mocker.Mock(), SqliteDialect())
    mocker.patch("time.sleep", return_value=None)
    mock_crit = mocker.patch("faktory_outbox.relay.logger.critical")

    mocker.patch.object(
        relay,
        "process_batch",
        side_effect=[
            0,
            Exception("Transient Error"),
            KeyboardInterrupt(),
        ],
    )

    with pytest.raises(KeyboardInterrupt):
        relay.run_loop(min_sleep_seconds=10.0, max_sleep_seconds=5.0)

    assert mock_crit.called


def test_unwrap_payload_arguments_orm_mode(mocker: Any) -> None:
    """Ensures ORM extraction blocks yield raw collection dicts."""
    relay = OutboxRelay(mocker.Mock(), SqliteDialect())
    cursor = mocker.Mock()

    orm_payload = {
        "mode": "orm",
        "model_identifier": "auth.user",
        "content": [{"pk": 1, "username": "alice"}],
    }
    arguments = relay._unwrap_payload_arguments(cursor, orm_payload)
    assert arguments == [[{"pk": 1, "username": "alice"}]]


def test_unwrap_payload_arguments_raw_sql_mode(mocker: Any) -> None:
    """Ensures raw SQL templates are evaluated JIT via cursors."""
    relay = OutboxRelay(mocker.Mock(), SqliteDialect())
    cursor = mocker.Mock()

    cursor.description = [("pk", None), ("amount", None)]
    cursor.fetchall.return_value = [(42, 100.00)]

    sql_payload = {
        "mode": "sql",
        "query_string": "SELECT pk, amount FROM invoice WHERE pk = ?",
        "parameters": [],
    }

    arguments = relay._unwrap_payload_arguments(cursor, sql_payload)

    cursor.execute.assert_called_once_with(
        "SELECT pk, amount FROM invoice WHERE pk = ?", []
    )
    assert arguments == [[{"pk": 42, "amount": 100.00}]]


def test_unwrap_payload_arguments_empty_sql_or_unknown(
    mocker: Any,
) -> None:
    """Ensures empty sql or unknown modes fall back to safe dicts."""
    relay = OutboxRelay(mocker.Mock(), SqliteDialect())
    cursor = mocker.Mock()

    assert relay._unwrap_payload_arguments(cursor, {"mode": "sql"}) == [{}]
    assert relay._unwrap_payload_arguments(cursor, {"mode": "invalid"}) == [{}]


def test_sync_jobs_to_faktory_unit_level_error_handling(
    mocker: Any,
) -> None:
    """Ensures single task drops increment attempts and log errors."""
    mock_conn = mocker.Mock()
    mock_client = mocker.Mock()
    mock_client.queue.side_effect = Exception("Network Reset")

    mock_context = mocker.MagicMock()
    mock_context.__enter__.return_value = mock_client
    mocker.patch("faktory.connection", return_value=mock_context)

    relay = OutboxRelay(mock_conn, SqliteDialect(), max_delivery_retries=2)
    cursor = mocker.Mock()

    success_count = relay._sync_jobs_to_faktory(cursor, [(99, "Task", "{}")])

    assert success_count == 0
    assert cursor.execute.called


def test_main_cli_fails_when_database_url_missing(mocker: Any) -> None:
    """Ensures CLI bootstrap aborts if required env strings are vacant."""
    mocker.patch("os.getenv", return_value="")
    mock_crit = mocker.patch("faktory_outbox.relay.logger.critical")

    mocker.patch("sys.exit", side_effect=SystemExit(1))

    from faktory_outbox.relay import main

    with pytest.raises(SystemExit) as exit_context:
        main()

    assert exit_context.value.code == 1
    mock_crit.assert_called_with("DATABASE_URL is missing. Relay cannot start.")


def test_main_cli_bootstrap_retry_loop_on_database_connection(
    mocker: Any,
) -> None:
    """Validates connection retry windows and loop escape paths."""
    mocker.patch(
        "os.getenv",
        side_effect=lambda key, default=None: {
            "DATABASE_URL": "postgres://user:pass@localhost/db",
            "FAKTORY_URL": "tcp://localhost:7419",
            "RELAY_DEBUG": "false",
            "RELAY_BATCH_SIZE": "50",
        }.get(key, default),
    )

    mocker.patch("time.sleep", return_value=None)
    mocker.patch("sys.exit", side_effect=SystemExit(0))

    mock_psycopg = mocker.MagicMock()
    mock_psycopg.connect.side_effect = [
        Exception("DB Starting up..."),
        Exception("DB Starting up..."),
        mocker.Mock(),
    ]
    sys.modules["psycopg2"] = mock_psycopg
    sys.modules["psycopg2.extensions"] = mocker.MagicMock()

    mocker.patch.object(OutboxRelay, "run_loop", side_effect=KeyboardInterrupt())

    from faktory_outbox.relay import main

    with pytest.raises(SystemExit) as exit_context:
        main()

    assert exit_context.value.code == 0
    assert mock_psycopg.connect.call_count == 3


def test_main_cli_aborts_if_retry_limit_exceeded(mocker: Any) -> None:
    """Ensures CLI drops process code if connections never stabilize."""
    mocker.patch(
        "os.getenv",
        side_effect=lambda key, default=None: {
            "DATABASE_URL": "sqlite:///test.db",
            "FAKTORY_URL": "tcp://localhost:7419",
        }.get(key, default),
    )

    mocker.patch("time.sleep", return_value=None)
    mocker.patch("sys.exit", side_effect=SystemExit(1))

    import sqlite3

    mocker.patch(
        "sqlite3.connect",
        side_effect=sqlite3.OperationalError("Disk Failure"),
    )

    from faktory_outbox.relay import main

    with pytest.raises(SystemExit) as exit_context:
        main()

    assert exit_context.value.code == 1


def test_sync_jobs_to_faktory_should_log_error_traces_on_failure(
    mocker: Any,
) -> None:
    """Ensures delivery failures trigger formatted error traceback logs."""
    mock_conn = mocker.Mock()
    mock_client = mocker.Mock()
    mock_client.queue.side_effect = Exception("TCP Socket Timeout")

    mock_context = mocker.MagicMock()
    mock_context.__enter__.return_value = mock_client
    mocker.patch("faktory.connection", return_value=mock_context)

    mock_logger_error = mocker.patch("faktory_outbox.relay.logger.error")

    relay = OutboxRelay(mock_conn, SqliteDialect())
    cursor = mocker.Mock()

    relay._sync_jobs_to_faktory(cursor, [(1, "TaskName", "{}")])

    assert mock_logger_error.called

    assert mock_logger_error.call_args[0][0] == "Failed to relay job ID %d: %s"
    assert mock_logger_error.call_args[0][1] == 1
    assert "TCP Socket Timeout" in mock_logger_error.call_args[0][2]


def test_main_cli_graceful_cleanup_and_connection_close(
    mocker: Any,
) -> None:
    """Ensures final database connection handles are cleanly dismantled."""
    mocker.patch(
        "os.getenv",
        side_effect=lambda key, default=None: {
            "DATABASE_URL": "sqlite:///test.db",
            "FAKTORY_URL": "tcp://localhost:7419",
        }.get(key, default),
    )
    mocker.patch("time.sleep", return_value=None)
    mocker.patch("sys.exit", side_effect=SystemExit(0))

    mock_sqlite_conn = mocker.Mock()
    mocker.patch("sqlite3.connect", return_value=mock_sqlite_conn)

    mock_logger_info = mocker.patch("faktory_outbox.relay.logger.info")

    mocker.patch.object(OutboxRelay, "run_loop", side_effect=KeyboardInterrupt())

    from faktory_outbox.relay import main

    with pytest.raises(SystemExit):
        main()

    mock_sqlite_conn.close.assert_called_once()
    assert any(
        "Relay stopped gracefully" in str(call)
        for call in mock_logger_info.call_args_list
    )
