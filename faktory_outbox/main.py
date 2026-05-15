"""Main entry point for the Outbox Relay CLI daemon application."""

import logging
import os
import sys
import time
import urllib.parse as urlparse
from typing import Any

from .dialects import (
    MariaDbDialect,
    OracleDialect,
    PostgresDialect,
    SqliteDialect,
)
from .engine import OutboxRelay


def main() -> None:
    """Initializes logging, connects to the database, and starts relay.

    This function reads environmental configurations, automatically detects
    the target database flavor from the connection URI, instantiates the
    corresponding engine components, and runs the continuous sync engine.
    """
    debug_mode = os.getenv("RELAY_DEBUG", "false").lower() == "true"
    log_level = logging.DEBUG if debug_mode else logging.INFO

    logging.Formatter.converter = time.localtime
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s │ %(levelname)-8s │ %(message)s",
        datefmt="%H:%M:%S",
    )

    database_url = os.getenv("DATABASE_URL", "")
    faktory_url = os.getenv("FAKTORY_URL", "tcp://localhost:7419")

    if not database_url:
        logger = logging.getLogger("faktory_outbox.relay")
        logger.critical("DATABASE_URL is missing. Relay cannot start.")
        sys.exit(1)

    db_url_lower = database_url.lower()

    if "postgres" in db_url_lower:
        dialect = PostgresDialect()
        connection_type = "postgres"
    elif "mariadb" in db_url_lower or "mysql" in db_url_lower:
        dialect = MariaDbDialect()
        connection_type = "mariadb"
    elif "sqlite" in db_url_lower or database_url.startswith("file:"):
        dialect = SqliteDialect()
        connection_type = "sqlite"
    else:
        dialect = OracleDialect()
        connection_type = "oracle"

    logger = logging.getLogger("faktory_outbox.relay")
    logger.info(
        "📡 Relay starting (Mode: %s, Engine: %s)",
        "DEBUG" if debug_mode else "PROD",
        connection_type.upper(),
    )

    db_connection: Any = None

    for attempt in range(1, 11):
        try:
            match connection_type:
                case "postgres":
                    import psycopg2
                    from psycopg2.extensions import (
                        ISOLATION_LEVEL_READ_COMMITTED,
                    )

                    db_connection = psycopg2.connect(database_url)
                    db_connection.set_isolation_level(
                        ISOLATION_LEVEL_READ_COMMITTED
                    )
                case "mariadb":
                    import mariadb

                    parsed_url = urlparse.urlparse(database_url)
                    db_host: str = parsed_url.hostname or "localhost"
                    db_user: str = urlparse.unquote(parsed_url.username or "")
                    db_pass: str = urlparse.unquote(parsed_url.password or "")
                    db_name: str = parsed_url.path.lstrip("/")
                    db_port: int = int(parsed_url.port or 3306)

                    db_connection = mariadb.connect(
                        host=db_host,
                        user=db_user,
                        password=db_pass,
                        database=db_name,
                        port=db_port,
                    )
                case "sqlite":
                    import sqlite3

                    clean_path = database_url.replace("sqlite:///", "")
                    db_connection = sqlite3.connect(clean_path)
                case "oracle":
                    import oracledb

                    db_connection = oracledb.connect(dsn=database_url)

                case _:
                    raise ValueError(
                        f"Unsupported connection type: {connection_type}"
                    )

            logger.info("🔌 Database connection established.")
            break
        except Exception as conn_error:
            logger.warning(
                "Database not ready (attempt %d/10): %s. Retrying...",
                attempt,
                str(conn_error),
            )
            time.sleep(3)

    if not db_connection:
        logger.critical("Could not connect to the database. Exiting.")
        sys.exit(1)

    try:
        env_batch_size = int(os.getenv("RELAY_BATCH_SIZE", "50"))
    except ValueError:
        env_batch_size = 50

    try:
        relay = OutboxRelay(
            connection=db_connection,
            dialect=dialect,
            faktory_url=faktory_url,
        )
        safe_faktory_url = relay.mask_url_password(faktory_url)
        logger.info(
            "🚀 Relay loop active (Batch size: %d, Server: %s)",
            env_batch_size,
            safe_faktory_url,
        )

        relay.run_loop(
            min_sleep_seconds=2.0,
            max_sleep_seconds=60.0,
            batch_size=env_batch_size,
        )

    except KeyboardInterrupt:
        logger.info("")
        logger.info("🛑 Shutdown requested by user...")
    except SystemExit:
        raise
    except Exception as runtime_error:
        logger.critical("❌ Relay engine crashed: %s", runtime_error)
        sys.exit(1)
    finally:
        if db_connection is not None:
            db_connection.close()
            logger.info("🔌 Database connection closed.")
        logger.info("👋 Relay stopped gracefully. Goodbye!")

    sys.exit(0)


if __name__ == "__main__":
    main()
