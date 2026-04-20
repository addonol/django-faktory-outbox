"""Relay engine to synchronize the database outbox with a Faktory server.

This module provides the infrastructure to fetch pending jobs from various
database dialects (PostgreSQL, Oracle) and push them reliably to Faktory
using an exponential backoff strategy in case of service downtime.
"""

import json
import logging
import os
import sys
import time
import urllib.parse as urlparse
from typing import Any, List, Protocol, Union

import faktory

logger = logging.getLogger("faktory_outbox.relay")


class ConnectionProtocol(Protocol):
    """Structural typing for PEP 249 compliant database connections."""

    def cursor(self) -> Any:
        """Returns a new cursor object using the connection."""
        ...

    def commit(self) -> None:
        """Commits any pending transaction to the database."""
        ...

    def rollback(self) -> None:
        """Rolls back to the start of any pending transaction."""
        ...


class DBDialect:
    """Abstract interface for database-specific SQL syntax and behavior."""

    @staticmethod
    def get_pending_query(batch_size: int) -> str:
        """Generates the SQL query to fetch pending jobs.

        Args:
            batch_size: Maximum number of records to retrieve.

        Returns:
            A database-specific SELECT SQL string.

        Raises:
            NotImplementedError: If the method is not overridden.
        """
        raise NotImplementedError()

    @staticmethod
    def get_bool_value(value: bool) -> Union[bool, int]:
        """Converts Python boolean to database-specific format.

        Args:
            value: The boolean value to convert.

        Returns:
            The equivalent value for the database engine.
        """
        return value


class SqliteDialect(DBDialect):
    """SQLite implementation of the outbox dialect for local testing.

    Note: SQLite does not support 'FOR UPDATE SKIP LOCKED'. This dialect
    is intended for single-relay development environments.
    """

    @staticmethod
    def get_pending_query(batch_size: int) -> str:
        """Returns SQLite compatible query without locking clauses."""
        return (
            "SELECT id, task_name, payload FROM faktory_outbox "
            "WHERE processed = 0 ORDER BY created_at ASC "
            "LIMIT %s"
        )

    @staticmethod
    def get_bool_value(value: bool) -> int:
        """Converts boolean to SQLite numeric boolean (0/1)."""
        return 1 if value else 0


class PostgresDialect(DBDialect):
    """PostgreSQL implementation of the outbox dialect."""

    @staticmethod
    def get_pending_query(batch_size: int) -> str:
        """Returns PostgreSQL query with SKIP LOCKED support."""
        return (
            "SELECT id, task_name, payload FROM faktory_outbox "
            "WHERE processed = FALSE ORDER BY created_at ASC "
            "LIMIT %s FOR UPDATE SKIP LOCKED"
        )


class OracleDialect(DBDialect):
    """Oracle implementation of the outbox dialect."""

    @staticmethod
    def get_pending_query(batch_size: int) -> str:
        """Returns Oracle specific query using FETCH FIRST and SKIP LOCKED."""
        return (
            "SELECT id, task_name, payload FROM faktory_outbox "
            "WHERE processed = 0 ORDER BY created_at ASC "
            "FETCH FIRST %s ROWS ONLY FOR UPDATE SKIP LOCKED"
        )

    @staticmethod
    def get_bool_value(value: bool) -> int:
        """Converts boolean to Oracle numeric boolean (0/1)."""
        return 1 if value else 0


class OutboxRelay:
    """Independent engine to move jobs from DB outbox to Faktory server."""

    def __init__(
        self,
        connection: ConnectionProtocol,
        dialect: DBDialect,
        faktory_url: str = "tcp://localhost:7419",
    ):
        """Initializes the relay with a raw DB connection and a dialect.

        Args:
            connection: A PEP 249 compliant database connection object.
            dialect (DBDialect): The dialect strategy for SQL generation.
            faktory_url: The connection URL for the Faktory server.
        """
        self.conn = connection
        self.dialect = dialect
        self.faktory_url = faktory_url

    def _sync_jobs_to_faktory(self, cursor: Any, jobs: List[Any]) -> None:
        """Helper to push a list of jobs to Faktory and update their DB status.

        Args:
            cursor: The current database cursor.
            jobs: The list of job records fetched from the outbox.
        """
        with faktory.connection(self.faktory_url) as client:
            for jid, task, payload in jobs:
                data = json.loads(payload) if isinstance(payload, str) else payload

                client.queue(task, args=[data])

                processed_val = self.dialect.get_bool_value(True)
                cursor.execute(
                    "UPDATE faktory_outbox SET processed = %s WHERE id = %s",
                    [processed_val, jid],
                )

    def process_batch(self, batch_size: int = 50) -> int:
        """Fetches, pushes to Faktory, and marks jobs as processed.

        This method handles its own transactions. In case of failure during
        the Faktory push or SQL update, it performs a rollback.

        Args:
            batch_size (int): Number of jobs to process in a single batch.

        Returns:
            int: The number of jobs successfully processed.

        Raises:
            Exception: Re-raises critical database or network exceptions
                after rolling back the transaction.
        """
        cursor = self.conn.cursor()

        try:
            logger.debug("Scanning database for pending jobs ...")
            query = self.dialect.get_pending_query(batch_size)
            cursor.execute(query, (batch_size,))
            jobs = cursor.fetchall()

            if not jobs:
                return 0

            job_ids = [j[0] for j in jobs]
            min_id, max_id = min(job_ids), max(job_ids)

            logger.info(
                "📦 Forwarding chunk: IDs %d to %d (%d jobs)", min_id, max_id, len(jobs)
            )

            self._sync_jobs_to_faktory(cursor, jobs)

            self.conn.commit()
            return len(jobs)

        except Exception:
            self.conn.rollback()
            raise
        finally:
            cursor.close()

    def run_loop(
        self, min_sleep: float = 2.0, max_sleep: float = 60.0, batch_size: int = 50
    ) -> None:
        """Runs the relay loop with exponential backoff and critical alerting.

        This loop continuously polls the database for new jobs. If jobs are found,
        they are processed in chunks. If the database or Faktory is unavailable,
        the relay increases its wait time exponentially until it reaches max_sleep.

        Args:
            min_sleep: Minimum seconds to wait when no jobs are found or after an error.
            max_sleep: Maximum seconds to wait during exponential backoff.
            batch_size: Maximum number of jobs to fetch and process in each iteration.
        """
        backoff_delay = min_sleep

        while True:
            try:
                processed_count = self.process_batch(batch_size=batch_size)

                if processed_count > 0:
                    backoff_delay = min_sleep
                    continue

                time.sleep(min_sleep)

            except Exception as exc:
                if backoff_delay >= max_sleep:
                    logger.critical("Relay is stuck. Max backoff reached. Error: %s", exc)
                else:
                    logger.error(
                        "Relay error: %s. Retrying in %ds...", exc, backoff_delay
                    )

                time.sleep(backoff_delay)
                backoff_delay = min(backoff_delay * 2, max_sleep)

    def mask_url_password(self, url: str) -> str:
        """Removes the password from a connection URL for safe logging.

        Args:
            url: The full connection string.

        Returns:
            The masked URL string or '***' on failure.
        """
        try:
            if not isinstance(url, str):
                raise ValueError("URL must be a string")

            parsed = urlparse.urlparse(url)
            if not parsed.password:
                return url

            netloc = f"{parsed.username}:****@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"

            return parsed._replace(netloc=netloc).geturl()
        except Exception:
            return "***"


def main():
    """Main entry point for the Outbox Relay CLI.

    Initializes logging, establishes a connection to the database (PostgreSQL or Oracle)
    based on environment variables, and starts the relay loop to synchronize
    the database outbox with the Faktory server.

    Environment Variables:
        DATABASE_URL (str): The connection string for the database (Required).
        FAKTORY_URL (str): The connection string for Faktory (Default: tcp://localhost:7419).
        RELAY_DEBUG (bool): Enables debug logging if set to 'true'.
        RELAY_BATCH_SIZE (int): Number of jobs to process per batch (Default: 50).

    Raises:
        SystemExit: If DATABASE_URL is missing, DB connection fails, or a critical
            error occurs during execution.
    """
    DEBUG_MODE = os.getenv("RELAY_DEBUG", "false").lower() == "true"
    LOG_LEVEL = logging.DEBUG if DEBUG_MODE else logging.INFO

    logging.Formatter.converter = time.localtime
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s │ %(levelname)-8s │ %(message)s",
        datefmt="%H:%M:%S",
    )

    db_url = os.getenv("DATABASE_URL", "")
    faktory_url = os.getenv("FAKTORY_URL", "tcp://localhost:7419")

    if not db_url:
        logger.critical("DATABASE_URL is missing. Relay cannot start.")
        sys.exit(1)

    is_postgres = "postgres" in db_url.lower()
    dialect = PostgresDialect() if is_postgres else OracleDialect()
    conn = None

    logger.info("📡 Relay starting (Mode: %s)", "DEBUG" if DEBUG_MODE else "PROD")

    for attempt in range(1, 11):
        try:
            if is_postgres:
                import psycopg2
                from psycopg2.extensions import ISOLATION_LEVEL_READ_COMMITTED

                conn = psycopg2.connect(db_url)
                conn.set_isolation_level(ISOLATION_LEVEL_READ_COMMITTED)
            else:
                import oracledb

                conn = oracledb.connect(dsn=db_url)

            logger.info("🔌 Database connection established.")
            break
        except Exception:
            logger.warning("Database not ready (attempt %d/10). Retrying...", attempt)
            time.sleep(3)

    if not conn:
        logger.critical("Could not connect to the database. Exiting.")
        sys.exit(1)

    try:
        env_batch_size = int(os.getenv("RELAY_BATCH_SIZE", 50))
    except ValueError:
        env_batch_size = 50

    try:
        relay = OutboxRelay(connection=conn, dialect=dialect, faktory_url=faktory_url)
        safe_faktory_url = relay.mask_url_password(faktory_url)
        logger.info(
            "🚀 Relay loop active (Batch size: %d, Server: %s)",
            env_batch_size,
            safe_faktory_url,
        )

        relay.run_loop(min_sleep=2.0, max_sleep=60.0, batch_size=env_batch_size)

    except KeyboardInterrupt:
        logger.info("")
        logger.info("🛑 Shutdown requested by user...")
    except SystemExit:
        raise
    except Exception as exc:
        logger.critical("❌ Relay engine crashed: %s", exc)
        sys.exit(1)
        return
    finally:
        if conn is not None:
            conn.close()
            logger.info("🔌 Database connection closed.")
        logger.info("👋 Relay stopped gracefully. Goodbye!")

    sys.exit(0)


if __name__ == "__main__":
    main()
