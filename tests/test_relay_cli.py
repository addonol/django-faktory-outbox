"""Integration tests for the Outbox Relay CLI entry point.

Validates environment variables, driver loading, retry mechanisms,
and exit codes for the command-line interface.
"""

import os
import sys
from typing import Any

import pytest

from faktory_outbox.relay import main

POSTGRES_URL = "postgres://localhost"
ORACLE_URL = "oracle://localhost"


@pytest.fixture
def mock_cli_env(mocker: Any) -> Any:
    """Provides a safe execution environment for CLI tests.

    Bypasses time delays and forces sys.exit to raise a SystemExit
    exception that can be captured by pytest.
    """
    mocker.patch("time.sleep", return_value=None)
    return mocker.patch("sys.exit", side_effect=lambda c: exec(f"raise SystemExit({c})"))


@pytest.fixture
def mock_psycopg2(mocker: Any) -> None:
    """Commonly used mock for PostgreSQL driver stack."""
    mocker.patch.dict(
        sys.modules, {"psycopg2": mocker.Mock(), "psycopg2.extensions": mocker.Mock()}
    )


def test_should_exit_with_error_when_config_is_missing(
    mocker: Any, mock_cli_env: Any
) -> None:
    """Verifies that the relay refuses to start without a DATABASE_URL."""
    mocker.patch.dict(os.environ, {"DATABASE_URL": ""}, clear=True)

    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_should_start_successfully_on_postgres_path(
    mocker: Any, mock_cli_env: Any, mock_psycopg2: Any
) -> None:
    """Validates the standard PostgreSQL bootstrap and graceful shutdown."""
    mocker.patch.dict(os.environ, {"DATABASE_URL": POSTGRES_URL})
    mocker.patch(
        "faktory_outbox.relay.OutboxRelay.run_loop", side_effect=KeyboardInterrupt
    )

    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_should_retry_connection_before_succeeding(
    mocker: Any, mock_cli_env: Any, mock_psycopg2: Any
) -> None:
    """Ensures the connection retry loop works before establishing a session."""
    mocker.patch.dict(os.environ, {"DATABASE_URL": POSTGRES_URL})

    mock_conn = mocker.Mock()
    # Fails once, succeeds on second attempt
    mocker.patch(
        "psycopg2.connect", side_effect=[Exception("Connection Pending"), mock_conn]
    )
    mocker.patch(
        "faktory_outbox.relay.OutboxRelay.run_loop", side_effect=KeyboardInterrupt
    )

    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_should_close_connection_on_critical_crash(
    mocker: Any, mock_cli_env: Any, mock_psycopg2: Any
) -> None:
    """Guarantees that DB connections are closed even if the relay engine crashes."""
    mock_conn = mocker.Mock()
    mocker.patch("psycopg2.connect", return_value=mock_conn)
    mocker.patch.dict(os.environ, {"DATABASE_URL": POSTGRES_URL})

    # Simulate a crash right after the relay starts
    mocker.patch(
        "faktory_outbox.relay.OutboxRelay", side_effect=Exception("Engine Failure")
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    mock_conn.close.assert_called_once()


def test_should_handle_oracle_path_and_batch_fallback(
    mocker: Any, mock_cli_env: Any
) -> None:
    """Verifies Oracle driver loading and invalid batch size gracefull fallback."""
    mocker.patch.dict(sys.modules, {"oracledb": mocker.Mock()})
    mocker.patch.dict(
        os.environ, {"DATABASE_URL": ORACLE_URL, "RELAY_BATCH_SIZE": "invalid_value"}
    )
    mocker.patch(
        "faktory_outbox.relay.OutboxRelay.run_loop", side_effect=KeyboardInterrupt
    )

    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
