"""Unit tests for checking the core Outbox Relay engine components."""

from typing import Any

import pytest

from faktory_outbox.dialects import PostgresDialect, SqliteDialect
from faktory_outbox.engine import OutboxRelay


def test_process_batch_empty_outbox(mock_db_conn: Any) -> None:
    """Ensures process_batch returns zero when no pending rows exist."""
    cursor = mock_db_conn.cursor.return_value
    cursor.fetchall.return_value = []

    postgres_dialect = PostgresDialect()
    relay = OutboxRelay(
        connection=mock_db_conn,
        dialect=postgres_dialect,
    )
    processed = relay.process_batch(batch_size=10)

    assert processed == 0

    mock_db_conn.commit.assert_called_once()


def test_process_batch_success_pipeline(
    mock_db_conn: Any, mock_faktory: Any, mocker: Any
) -> None:
    """Validates a successful job chunk lifecycle sync operation."""
    cursor = mock_db_conn.cursor.return_value
    cursor.fetchall.return_value = [
        (1, "SendEmail", '{"mode": "custom", "content": {"id": 1}}')
    ]

    mocker.patch("faktory.connection", return_value=mock_faktory)
    client = mock_faktory.__enter__.return_value
    client.push_bulk.return_value = True

    relay = OutboxRelay(connection=mock_db_conn, dialect=PostgresDialect())
    processed = relay.process_batch(batch_size=5)

    assert processed == 1
    client.push_bulk.assert_called_once()
    mock_db_conn.commit.assert_called_once()


def test_process_batch_faktory_rejection_triggers_rollback(
    mock_db_conn: Any, mock_faktory: Any, mocker: Any
) -> None:
    """Ensures transaction rollbacks when Faktory rejects a payload."""
    cursor = mock_db_conn.cursor.return_value
    cursor.fetchall.return_value = [
        (2, "SendSms", '{"mode": "custom", "content": {}}')
    ]

    mocker.patch("faktory.connection", return_value=mock_faktory)
    client = mock_faktory.__enter__.return_value
    client.push_bulk.return_value = False

    postgres_dialect = PostgresDialect()
    relay = OutboxRelay(connection=mock_db_conn, dialect=postgres_dialect)

    with pytest.raises(RuntimeError, match="Faktory bulk pipeline rejected"):
        relay.process_batch(batch_size=5)

    mock_db_conn.rollback.assert_called_once()


def test_process_batch_payload_parse_error_logs_failure(
    mock_db_conn: Any, mock_faktory: Any, mocker: Any
) -> None:
    """Verifies that individual broken job tasks increment error tries."""
    cursor = mock_db_conn.cursor.return_value
    cursor.fetchall.return_value = [(3, "BadJob", "{invalid-json")]

    mocker.patch("faktory.connection", return_value=mock_faktory)
    client = mock_faktory.__enter__.return_value

    relay = OutboxRelay(connection=mock_db_conn, dialect=PostgresDialect())
    processed = relay.process_batch(batch_size=5)

    assert processed == 0
    client.push_bulk.assert_not_called()
    assert cursor.execute.call_count >= 2
    mock_db_conn.commit.assert_called_once()


def test_mask_url_password_protection() -> None:
    """Validates credential safety scrubbing logs parsing mechanics."""
    assert OutboxRelay.mask_url_password("tcp://localhost:7419") == (
        "tcp://localhost:7419"
    )
    assert OutboxRelay.mask_url_password("tcp://user:pass@host:7419") == (
        "tcp://user:****@host:7419"
    )
    assert OutboxRelay.mask_url_password(None) == "***"  # type: ignore


def test_unwrap_payload_arguments_with_valid_sql_mode(
    mock_db_conn: Any,
) -> None:
    """Ensures dynamic runtime sql mode data is unpacked into arguments."""
    cursor = mock_db_conn.cursor.return_value
    cursor.description = ["id", "username"]
    cursor.fetchall.return_value = [(42, "extracted_user")]

    relay = OutboxRelay(connection=mock_db_conn, dialect=SqliteDialect())

    payload_data = {
        "mode": "sql",
        "query_string": "SELECT id, username FROM users WHERE id = ?",
        "parameters": [42],
    }

    results = relay._unwrap_payload_arguments(cursor, payload_data)

    assert results == [[{"id": 42, "username": "extracted_user"}]]
    cursor.execute.assert_called_once_with(
        "SELECT id, username FROM users WHERE id = ?",
        [42],
    )


def test_unwrap_payload_arguments_with_empty_sql_string_guard(
    mock_db_conn: Any,
) -> None:
    """Ensures empty sql statements return fallback empty object brackets."""
    cursor = mock_db_conn.cursor.return_value
    relay = OutboxRelay(connection=mock_db_conn, dialect=SqliteDialect())

    payload_data = {
        "mode": "sql",
        "query_string": "",
    }

    results = relay._unwrap_payload_arguments(cursor, payload_data)

    assert results == [{}]
    cursor.execute.assert_not_called()


def test_unwrap_payload_arguments_with_invalid_mode_fallback(
    mock_db_conn: Any,
) -> None:
    """Ensures unrecognized extraction modes safely return empty brackets."""
    cursor = mock_db_conn.cursor.return_value
    relay = OutboxRelay(connection=mock_db_conn, dialect=SqliteDialect())

    payload_data = {
        "mode": "unsupported_legacy_format",
        "content": {"data": "ignored"},
    }

    results = relay._unwrap_payload_arguments(cursor, payload_data)

    assert results == [{}]
    cursor.execute.assert_not_called()


def test_run_loop_nominal_processing_yields_scheduler(
    mock_db_conn: Any, mocker: Any
) -> None:
    """Ensures run_loop executes micro-yields when processed_count > 0."""
    relay = OutboxRelay(connection=mock_db_conn, dialect=SqliteDialect())

    mocker.patch.object(
        relay,
        "process_batch",
        side_effect=[1, KeyboardInterrupt("Stop Loop")],
    )
    mock_sleep = mocker.patch("time.sleep", return_value=None)

    with pytest.raises(KeyboardInterrupt, match="Stop Loop"):
        relay.run_loop(min_sleep_seconds=2.0, max_sleep_seconds=10.0)

    mock_sleep.assert_any_call(0.01)


def test_run_loop_exponential_backoff_increment_on_error(
    mock_db_conn: Any, mocker: Any
) -> None:
    """Verifies that failures double backoff delays and log error level."""
    relay = OutboxRelay(connection=mock_db_conn, dialect=SqliteDialect())

    mocker.patch.object(
        relay,
        "process_batch",
        side_effect=[
            RuntimeError("DB Offline"),
            RuntimeError("DB Offline"),
            KeyboardInterrupt("Stop Loop"),
        ],
    )
    mock_sleep = mocker.patch("time.sleep", return_value=None)
    mock_logger_error = mocker.patch("faktory_outbox.engine.logger.error")

    with pytest.raises(KeyboardInterrupt, match="Stop Loop"):
        relay.run_loop(min_sleep_seconds=2.0, max_sleep_seconds=60.0)

    mock_sleep.assert_any_call(2.0)
    mock_sleep.assert_any_call(4.0)
    assert mock_logger_error.call_count == 2


def test_run_loop_reaches_maximum_backoff_and_logs_critical(
    mock_db_conn: Any, mocker: Any
) -> None:
    """Ensures critical alerts trigger when backoff hits max limit."""
    relay = OutboxRelay(connection=mock_db_conn, dialect=SqliteDialect())

    mocker.patch.object(
        relay,
        "process_batch",
        side_effect=[
            RuntimeError("Fatal Crash"),
            RuntimeError("Fatal Crash"),
            KeyboardInterrupt("Stop Loop"),
        ],
    )
    mock_sleep = mocker.patch("time.sleep", return_value=None)
    mock_logger_critical = mocker.patch(
        "faktory_outbox.engine.logger.critical"
    )

    with pytest.raises(KeyboardInterrupt, match="Stop Loop"):
        relay.run_loop(min_sleep_seconds=5.0, max_sleep_seconds=5.0)

    mock_sleep.assert_any_call(5.0)
    assert mock_logger_critical.call_count == 2

    first_critical_call = mock_logger_critical.call_args_list
    assert "Max backoff reached" in str(first_critical_call)


def test_run_loop_sleeps_when_no_jobs_are_found(
    mock_db_conn: Any, mocker: Any
) -> None:
    """Ensures run_loop goes to sleep for min_sleep_seconds when idle."""
    relay = OutboxRelay(connection=mock_db_conn, dialect=SqliteDialect())

    mocker.patch.object(
        relay,
        "process_batch",
        side_effect=[0, KeyboardInterrupt("Stop Loop")],
    )
    mock_sleep = mocker.patch("time.sleep", return_value=None)

    with pytest.raises(KeyboardInterrupt, match="Stop Loop"):
        relay.run_loop(min_sleep_seconds=15.0, max_sleep_seconds=60.0)

    mock_sleep.assert_any_call(15.0)


def test_sync_jobs_to_faktory_should_log_error_traces_on_failure(
    mocker: Any,
) -> None:
    """Ensures delivery failures trigger formatted error traceback logs."""
    mock_conn = mocker.Mock()
    mock_client = mocker.Mock()
    mock_client.push_bulk.return_value = True

    mocker.patch(
        "faktory.connection",
        return_value=mocker.MagicMock(
            __enter__=mocker.Mock(return_value=mock_client)
        ),
    )

    mock_logger_error = mocker.patch("faktory_outbox.engine.logger.error")

    relay = OutboxRelay(mock_conn, SqliteDialect())
    cursor = mocker.Mock()

    relay._sync_jobs_to_faktory(cursor, [(1, "TaskName", "{")])

    assert mock_logger_error.called

    logged_message = mock_logger_error.call_args[0][0]
    assert logged_message == (
        "Failed to process job ID %s before bulk sync: %s"
    )


def test_sync_jobs_to_faktory_handles_postgres_dict_payload(
    mocker: Any,
) -> None:
    """Ensures pre-parsed dictionaries from Postgres bypass json.loads."""
    mock_conn = mocker.Mock()
    mock_client = mocker.Mock()
    mock_client.push_bulk.return_value = True

    mocker.patch(
        "faktory.connection",
        return_value=mocker.MagicMock(
            __enter__=mocker.Mock(return_value=mock_client)
        ),
    )

    relay = OutboxRelay(mock_conn, SqliteDialect())
    cursor = mocker.Mock()

    native_dict = {"mode": "custom", "content": {"status": "ok"}}
    processed = relay._sync_jobs_to_faktory(
        cursor, [(1, "TaskName", native_dict)]
    )

    assert processed == 1
    assert mock_client.push_bulk.called


def test_sync_jobs_to_faktory_decodes_mysqlclient_bytes_payload(
    mocker: Any,
) -> None:
    """Ensures raw bytes from mysqlclient are safely decoded into dicts."""
    mock_conn = mocker.Mock()
    mock_client = mocker.Mock()
    mock_client.push_bulk.return_value = True

    mocker.patch(
        "faktory.connection",
        return_value=mocker.MagicMock(
            __enter__=mocker.Mock(return_value=mock_client)
        ),
    )

    relay = OutboxRelay(mock_conn, SqliteDialect())
    cursor = mocker.Mock()

    bytes_payload = b'{"mode": "custom", "content": {"status": "ok"}}'
    processed = relay._sync_jobs_to_faktory(
        cursor, [(2, "TaskName", bytes_payload)]
    )

    assert processed == 1
    assert mock_client.push_bulk.called


def test_sync_jobs_to_faktory_unwraps_double_serialized_json(
    mocker: Any,
) -> None:
    """Ensures double-serialized string payloads run a second parse pass."""
    mock_conn = mocker.Mock()
    mock_client = mocker.Mock()
    mock_client.push_bulk.return_value = True

    mocker.patch(
        "faktory.connection",
        return_value=mocker.MagicMock(
            __enter__=mocker.Mock(return_value=mock_client)
        ),
    )

    relay = OutboxRelay(mock_conn, SqliteDialect())
    cursor = mocker.Mock()

    double_serialized = '"{\\"mode\\": \\"custom\\", \\"content\\": {}}"'
    processed = relay._sync_jobs_to_faktory(
        cursor, [(3, "TaskName", double_serialized)]
    )

    assert processed == 1
    assert mock_client.push_bulk.called
