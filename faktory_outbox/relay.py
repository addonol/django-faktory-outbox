"""Automated Transactional Outbox Relay Engine with Bulk Processing.

This daemon monitors the shared database outbox tables using low-overhead
SKIP LOCKED queries and compresses active rows into single network frames via
the native Faktory PUSHB protocol to eliminate network loops bottlenecks.
"""

import json
import logging
import os
import sys
import time
import traceback
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
    """Abstract interface for database-specific SQL syntax."""

    @staticmethod
    def get_pending_query(batch_size: int) -> str:
        """Generates the SQL query to fetch pending jobs.

        Args:
            batch_size (int): Maximum number of records to retrieve.

        Returns:
            str: A database-specific SELECT SQL string.

        Raises:
            NotImplementedError: If the method is not overridden.
        """
        raise NotImplementedError()

    @staticmethod
    def get_bool_value(value: bool) -> Union[bool, int]:
        """Converts Python boolean to database-specific format.

        Args:
            value (bool): The boolean value to convert.

        Returns:
            Union[bool, int]: The equivalent value for the database.
        """
        return value


class SqliteDialect(DBDialect):
    """SQLite implementation of the outbox dialect for local testing.

    Note: SQLite does not support 'FOR UPDATE SKIP LOCKED'. This
    dialect is intended for single-relay development environments.
    """

    @staticmethod
    def get_pending_query(batch_size: int) -> str:
        """Returns SQLite compatible query matching the partial index."""
        return (
            "SELECT id, task_name, payload FROM faktory_outbox "
            "WHERE processed = 0 AND is_failed = 0 "
            "ORDER BY created_at ASC LIMIT ?"
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
            "WHERE processed = FALSE AND is_failed = FALSE "
            "ORDER BY created_at ASC LIMIT %s FOR UPDATE SKIP LOCKED"
        )


class OracleDialect(DBDialect):
    """Oracle implementation of the outbox dialect."""

    @staticmethod
    def get_pending_query(batch_size: int) -> str:
        """Returns Oracle query using FETCH FIRST and SKIP LOCKED."""
        return (
            "SELECT id, task_name, payload FROM faktory_outbox "
            "WHERE processed = 0 AND is_failed = 0 "
            "ORDER BY created_at ASC FETCH FIRST %s ROWS ONLY "
            "FOR UPDATE SKIP LOCKED"
        )

    @staticmethod
    def get_bool_value(value: bool) -> int:
        """Converts boolean to Oracle numeric boolean (0/1)."""
        return 1 if value else 0


class OutboxRelay:
    """Independent engine to move jobs from DB outbox to Faktory."""

    def __init__(
        self,
        connection: ConnectionProtocol,
        dialect: DBDialect,
        faktory_url: str = "tcp://localhost:7419",
        max_delivery_retries: int = 5,
    ):
        """Initializes the relay engine components.

        Args:
            connection (ConnectionProtocol): A PEP 249 compliant
                database connection instance.
            dialect (DBDialect): The database dialect strategy.
            faktory_url (str): Connection URL for the Faktory server.
            max_delivery_retries (int): Maximum delivery attempts
                before flagging a job as failed.
        """
        self.db_connection = connection
        self.dialect = dialect
        self.faktory_url = faktory_url
        self.max_delivery_retries = max_delivery_retries

    def _unwrap_payload_arguments(self, cursor: Any, payload_data: dict) -> List[Any]:
        """Extracts and formats runtime arguments for the worker.

        Args:
            cursor (Any): An active database cursor.
            payload_data (dict): The unpacked JSON payload dictionary.

        Returns:
            List[Any]: A list containing a single element representing
                the arguments array for the Faktory job.
        """
        extraction_mode = payload_data.get("mode", "custom")

        if extraction_mode in ("custom", "orm"):
            return [payload_data.get("content", {})]

        if extraction_mode == "sql":
            query_string = payload_data.get("query_string")
            parameters = payload_data.get("parameters", [])

            if not query_string:
                return [{}]

            cursor.execute(query_string, parameters)

            columns = [col_desc[0] for col_desc in cursor.description]

            query_results = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return [query_results]

        return [{}]

    def _sync_jobs_to_faktory(self, cursor: Any, jobs: List[Any]) -> int:
        """Pushes a batch of jobs to Faktory using the fork's push_bulk API.

        Args:
            cursor (Any): An active database cursor.
            jobs (List[Any]): A collection of rows from the outbox.

        Returns:
            int: Total number of records successfully pushed.
        """
        bulk_jobs: List[dict] = []
        successful_ids: List[Any] = []

        with faktory.connection(self.faktory_url) as faktory_client:
            for job_id, task_name, raw_payload in jobs:
                try:
                    payload_data = (
                        json.loads(raw_payload)
                        if isinstance(raw_payload, str)
                        else raw_payload
                    )
                    task_arguments = self._unwrap_payload_arguments(cursor, payload_data)

                    faktory_job = faktory_client._build_job_payload(
                        task=task_name,
                        args=task_arguments,
                        queue="default",
                        retry=2,
                        priority=5,
                        backtrace=0,
                        custom={"outbox_id": job_id},
                    )

                    bulk_jobs.append(faktory_job)
                    successful_ids.append(job_id)

                except Exception as execution_error:
                    logger.error(
                        "Failed to process job ID %d before bulk sync: %s",
                        job_id,
                        str(execution_error),
                    )
                    error_traceback: str = "".join(
                        traceback.format_exception(
                            None,
                            execution_error,
                            execution_error.__traceback__,
                        )
                    )
                    cursor.execute(
                        "UPDATE faktory_outbox SET delivery_attempts "
                        "= delivery_attempts + 1, "
                        "last_execution_error = %s WHERE id = %s",
                        [error_traceback, job_id],
                    )
                    true_value = self.dialect.get_bool_value(True)
                    cursor.execute(
                        "UPDATE faktory_outbox SET is_failed = %s "
                        "WHERE id = %s AND delivery_attempts >= %s",
                        [true_value, job_id, self.max_delivery_retries],
                    )

            if not bulk_jobs:
                return 0

            success = faktory_client.push_bulk(bulk_jobs)
            if not success:
                raise Exception("Faktory server rejected the PUSHB payload.")

        processed_value = self.dialect.get_bool_value(True)
        for job_id in successful_ids:
            cursor.execute(
                "UPDATE faktory_outbox SET processed = %s WHERE id = %s",
                [processed_value, job_id],
            )

        return len(successful_ids)

    def process_batch(self, batch_size: int = 50) -> int:
        """Fetches, pushes, and commits a chunk of outbox records.

        Args:
            batch_size (int): Max number of jobs to fetch.

        Returns:
            int: The number of jobs successfully processed.
        """
        cursor = self.db_connection.cursor()

        try:
            pending_query = self.dialect.get_pending_query(batch_size)
            cursor.execute(pending_query, (batch_size,))
            jobs_chunk = cursor.fetchall()

            if not jobs_chunk:
                return 0

            job_ids = [row[0] for row in jobs_chunk]
            logger.info(
                "Processing batch of %d jobs (IDs: %s)",
                len(jobs_chunk),
                job_ids,
            )

            processed_count = self._sync_jobs_to_faktory(cursor, jobs_chunk)

            self.db_connection.commit()
            return processed_count

        except Exception:
            self.db_connection.rollback()
            raise
        finally:
            cursor.close()

    def mask_url_password(self, connection_url: str) -> str:
        """Removes the password from a connection URL for safe logging.

        Args:
            connection_url (str): The full connection string containing
                credentials to be masked.

        Returns:
            str: The masked URL string with the password replaced by
                asterisks, or '***' if parsing fails.
        """
        try:
            if not isinstance(connection_url, str):
                raise ValueError("URL must be a string sequence.")

            parsed_url = urlparse.urlparse(connection_url)
            if not parsed_url.password:
                return connection_url

            masked_netloc = f"{parsed_url.username}:****@{parsed_url.hostname}"
            if parsed_url.port:
                masked_netloc += f":{parsed_url.port}"

            return parsed_url._replace(netloc=masked_netloc).geturl()
        except Exception:
            return "***"

    def run_loop(
        self,
        min_sleep_seconds: float = 2.0,
        max_sleep_seconds: float = 60.0,
        batch_size: int = 50,
    ) -> None:
        """Runs the relay loop with exponential backoff and alerting.

        This loop continuously polls the database for new pending jobs.
        If jobs are found, they are processed in batches. If the
        database or Faktory is unavailable, the relay increases its
        wait time exponentially until it reaches max_sleep_seconds.

        Args:
            min_sleep_seconds (float): Minimum seconds to wait when no
                jobs are found or after an execution error.
            max_sleep_seconds (float): Maximum seconds to wait during
                exponential backoff phases.
            batch_size (int): Maximum number of jobs to fetch and
                process in each individual iteration.
        """
        current_backoff_delay = min_sleep_seconds

        while True:
            try:
                processed_count = self.process_batch(batch_size=batch_size)

                # Reset the backoff delay immediately upon successful
                # database transaction recovery.
                current_backoff_delay = min_sleep_seconds

                if processed_count > 0:
                    # Give a micro-yield to the OS scheduler to avoid
                    # 100% CPU thread starvation during heavy loads.
                    time.sleep(0.01)
                    continue

                time.sleep(min_sleep_seconds)

            except Exception as system_exception:
                if current_backoff_delay >= max_sleep_seconds:
                    logger.critical(
                        "Relay is stuck. Max backoff reached. Error: %s",
                        str(system_exception),
                    )
                else:
                    logger.error(
                        "Relay error: %s. Retrying in %ds...",
                        str(system_exception),
                        int(current_backoff_delay),
                    )

                time.sleep(current_backoff_delay)
                current_backoff_delay = min(current_backoff_delay * 2, max_sleep_seconds)


def main() -> None:
    """Main entry point for the Outbox Relay CLI.

    Initializes logging, establishes a connection to the target
    database engine based on configuration environment variables,
    and starts the processing loop to synchronize rows.
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
        logger.critical("DATABASE_URL is missing. Relay cannot start.")
        sys.exit(1)

    db_url_lower = database_url.lower()

    # Selection logic supporting all three declared dialects
    if "postgres" in db_url_lower:
        dialect = PostgresDialect()
        connection_type = "postgres"
    elif "sqlite" in db_url_lower or database_url.startswith("file:"):
        dialect = SqliteDialect()
        connection_type = "sqlite"
    else:
        dialect = OracleDialect()
        connection_type = "oracle"

    db_connection: Any = None

    logger.info(
        "📡 Relay starting (Mode: %s, Engine: %s)",
        "DEBUG" if debug_mode else "PROD",
        connection_type.upper(),
    )

    for attempt in range(1, 11):
        try:
            if connection_type == "postgres":
                import psycopg2
                from psycopg2.extensions import (
                    ISOLATION_LEVEL_READ_COMMITTED,
                )

                db_connection = psycopg2.connect(database_url)
                db_connection.set_isolation_level(ISOLATION_LEVEL_READ_COMMITTED)
            elif connection_type == "sqlite":
                import sqlite3

                clean_path = database_url.replace("sqlite:///", "")
                db_connection = sqlite3.connect(clean_path)
            else:
                import oracledb

                db_connection = oracledb.connect(dsn=database_url)

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
