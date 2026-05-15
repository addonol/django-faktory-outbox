"""Integration tests for the Outbox Relay CLI entry point.

Validates environment variables, driver loading, retry mechanisms,
and exit codes for the command-line interface.
"""

import os
import sys
from typing import Any

import pytest

from faktory_outbox.engine import OutboxRelay
from faktory_outbox.main import main

POSTGRES_URL = "postgres://localhost"
ORACLE_URL = "oracle://localhost"
MARIADB_URL = "mariadb://localhost"


@pytest.fixture
def mock_cli_env(mocker: Any) -> Any:
    """Provides a safe execution environment for CLI tests.

    Bypasses time delays and forces sys.exit to raise a SystemExit
    exception that can be captured by pytest.
    """
    mocker.patch("time.sleep", return_value=None)
    return mocker.patch(
        "sys.exit",
        side_effect=lambda code: exec(f"raise SystemExit({code})"),
    )


@pytest.fixture
def mock_psycopg2(mocker: Any) -> None:
    """Commonly used mock for PostgreSQL driver stack."""
    mocker.patch.dict(
        sys.modules,
        {
            "psycopg2": mocker.Mock(),
            "psycopg2.extensions": mocker.Mock(),
        },
    )


def test_should_exit_with_error_when_config_is_missing(
    mocker: Any, mock_cli_env: Any
) -> None:
    """Verifies that the relay refuses to start without a DATABASE_URL."""
    mocker.patch.dict(os.environ, {"DATABASE_URL": ""}, clear=True)

    with pytest.raises(SystemExit) as exception_context:
        main()
    assert exception_context.value.code == 1


def test_should_start_successfully_on_postgres_path(
    mocker: Any, mock_cli_env: Any, mock_psycopg2: Any
) -> None:
    """Validates the standard PostgreSQL bootstrap and graceful shutdown."""
    mocker.patch.dict(os.environ, {"DATABASE_URL": POSTGRES_URL})
    mocker.patch(
        "faktory_outbox.engine.OutboxRelay.run_loop",
        side_effect=KeyboardInterrupt,
    )

    with pytest.raises(SystemExit) as exception_context:
        main()
    assert exception_context.value.code == 0


def test_should_retry_connection_before_succeeding(
    mocker: Any, mock_cli_env: Any, mock_psycopg2: Any
) -> None:
    """Ensures the connection retry loop works before active sessions."""
    mocker.patch.dict(os.environ, {"DATABASE_URL": POSTGRES_URL})

    mock_connection = mocker.Mock()

    mocker.patch(
        "psycopg2.connect",
        side_effect=[Exception("Connection Pending"), mock_connection],
    )
    mocker.patch(
        "faktory_outbox.engine.OutboxRelay.run_loop",
        side_effect=KeyboardInterrupt,
    )

    with pytest.raises(SystemExit) as exception_context:
        main()
    assert exception_context.value.code == 0


def test_should_close_connection_on_critical_crash(
    mocker: Any, mock_cli_env: Any, mock_psycopg2: Any
) -> None:
    """Guarantees that DB connections close if the relay engine crashes."""
    mock_connection = mocker.Mock()
    mocker.patch("psycopg2.connect", return_value=mock_connection)
    mocker.patch.dict(os.environ, {"DATABASE_URL": POSTGRES_URL})

    mocker.patch(
        "faktory_outbox.main.OutboxRelay",
        side_effect=Exception("Engine Failure"),
    )

    with pytest.raises(SystemExit) as exception_context:
        main()

    assert exception_context.value.code == 1
    mock_connection.close.assert_called_once()


def test_should_handle_oracle_path_and_batch_fallback(
    mocker: Any, mock_cli_env: Any
) -> None:
    """Verifies Oracle driver loading and invalid batch size fallback."""
    mocker.patch.dict(sys.modules, {"oracledb": mocker.Mock()})
    mocker.patch.dict(
        os.environ,
        {
            "DATABASE_URL": ORACLE_URL,
            "RELAY_BATCH_SIZE": "invalid_value",
        },
    )
    mocker.patch(
        "faktory_outbox.engine.OutboxRelay.run_loop",
        side_effect=KeyboardInterrupt,
    )

    with pytest.raises(SystemExit) as exception_context:
        main()
    assert exception_context.value.code == 0


def test_should_handle_mariadb_path_via_pymysql(
    mocker: Any, mock_cli_env: Any
) -> None:
    """Verifies MariaDB/MySQL url parsing and driver bootstrap logic."""
    mock_mariadb_module = mocker.Mock()
    mocker.patch.dict(sys.modules, {"mariadb": mock_mariadb_module})
    mocker.patch.dict(os.environ, {"DATABASE_URL": MARIADB_URL})

    mocker.patch(
        "faktory_outbox.engine.OutboxRelay.run_loop",
        side_effect=KeyboardInterrupt,
    )

    with pytest.raises(SystemExit) as exception_context:
        main()

    assert exception_context.value.code == 0
    assert mock_mariadb_module.connect.called


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
    mocker.patch("faktory_outbox.main.sys.exit", side_effect=SystemExit(0))

    mock_psycopg = mocker.MagicMock()
    mock_psycopg.connect.side_effect = [
        Exception("DB Starting up..."),
        Exception("DB Starting up..."),
        mocker.Mock(),
    ]
    sys.modules["psycopg2"] = mock_psycopg
    sys.modules["psycopg2.extensions"] = mocker.MagicMock()

    mocker.patch.object(
        OutboxRelay, "run_loop", side_effect=KeyboardInterrupt()
    )

    from faktory_outbox.main import main

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
    mocker.patch("faktory_outbox.main.sys.exit", side_effect=SystemExit(1))

    import sqlite3

    mocker.patch(
        "sqlite3.connect",
        side_effect=sqlite3.OperationalError("Disk Failure"),
    )

    from faktory_outbox.main import main

    with pytest.raises(SystemExit) as exit_context:
        main()

    assert exit_context.value.code == 1


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
    mocker.patch("faktory_outbox.main.sys.exit", side_effect=SystemExit(0))

    mock_sqlite_conn = mocker.Mock()
    mocker.patch("sqlite3.connect", return_value=mock_sqlite_conn)

    mock_logger = mocker.MagicMock()
    mocker.patch("logging.getLogger", return_value=mock_logger)

    mocker.patch.object(
        OutboxRelay, "run_loop", side_effect=KeyboardInterrupt()
    )

    from faktory_outbox.main import main

    with pytest.raises(SystemExit):
        main()

    mock_sqlite_conn.close.assert_called_once()
    assert any(
        "Relay stopped gracefully" in str(call)
        for call in mock_logger.info.call_args_list
    )


def test_main_cli_unsupported_connection_type_case_guard(
    mocker: Any, mock_cli_env: Any
) -> None:
    """Ensures fallback error conditions trigger if connection type leaks."""
    mocker.patch(
        "faktory_outbox.main.os.getenv",
        side_effect=lambda key, default=None: {
            "DATABASE_URL": "oracle://localhost",
        }.get(key, default),
    )

    mock_oracledb = mocker.MagicMock()

    def simulate_match_case_fallback(*args: Any, **kwargs: Any) -> None:
        raise ValueError("Unsupported connection type: oracle")

    mock_oracledb.connect.side_effect = simulate_match_case_fallback
    sys.modules["oracledb"] = mock_oracledb

    with pytest.raises(SystemExit) as exception_context:
        main()

    assert exception_context.value.code == 1


def test_main_cli_system_exit_exception_re_raised(
    mocker: Any,
) -> None:
    """Ensures SystemExit exceptions bypass general blocks and re-raise."""
    mocker.patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:"})
    mocker.patch("time.sleep", return_value=None)

    mocker.patch(
        "faktory_outbox.main.OutboxRelay",
        side_effect=SystemExit(42),
    )

    with pytest.raises(SystemExit) as exception_context:
        main()

    assert exception_context.value.code == 42


@pytest.mark.filterwarnings(
    "ignore:'faktory_outbox.main' found in sys.modules:RuntimeWarning"
)
def test_main_module_execution_entrypoint(mocker: Any) -> None:
    """Validates the standard direct module execution entrypoint shell."""
    import runpy

    mocker.patch.dict(
        os.environ,
        {
            "DATABASE_URL": "sqlite:///:memory:",
            "FAKTORY_URL": "tcp://localhost:7419",
        },
    )

    from faktory_outbox.engine import OutboxRelay

    mocker.patch.object(OutboxRelay, "run_loop", side_effect=SystemExit(0))
    mocker.patch("time.sleep", return_value=None)

    with pytest.raises(SystemExit) as exception_context:
        runpy.run_module("faktory_outbox.main", run_name="__main__")

    assert exception_context.value.code == 0
