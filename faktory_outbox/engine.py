"""Core Transactional Outbox Relay Engine with Bulk Processing capability."""

import json
import logging
import time
import urllib.parse as urlparse
from typing import Any, Protocol

import faktory

from .dialects import DBDialect

logger = logging.getLogger("faktory_outbox.relay")


class ConnectionProtocol(Protocol):
    """Structural typing protocol representing a PEP 249 database connection.

    This protocol allows any database connection instance adhering to the
    Python Database API Specification v2.0 (PEP 249) to be used with the
    engine without requiring explicit subclassing.
    """

    def cursor(self) -> Any:
        """Creates and returns a new database cursor object."""
        ...

    def commit(self) -> None:
        """Commits the current transaction to the database."""
        ...

    def rollback(self) -> None:
        """Rolls back the current transaction to the start point."""
        ...


class OutboxRelay:
    """Independent engine to move jobs from DB outbox table to Faktory."""

    def __init__(
        self,
        connection: ConnectionProtocol,
        dialect: DBDialect,
        faktory_url: str = "tcp://localhost:7419",
        max_delivery_retries: int = 5,
    ) -> None:
        """Initializes the relay engine components.

        Args:
            connection (ConnectionProtocol): PEP 249 database connection.
            dialect (DBDialect): The database dialect strategy.
            faktory_url (str): Connection URL for the Faktory server.
            max_delivery_retries (int): Max attempts before failure flag.
        """
        self.db_connection = connection
        self.dialect = dialect
        self.faktory_url = faktory_url
        self.max_delivery_retries = max_delivery_retries

    def _unwrap_payload_arguments(
        self, cursor: Any, payload_data: dict[str, Any]
    ) -> list[Any]:
        """Extracts and formats runtime arguments for the worker.

        Args:
            cursor (Any): An active database cursor.
            payload_data (dict): The unpacked JSON payload dictionary.

        Returns:
            list[Any]: Formatted arguments array for the Faktory job.
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
            columns = [col_desc for col_desc in cursor.description]
            query_results = [
                dict(zip(columns, row)) for row in cursor.fetchall()
            ]
            return [query_results]

        return [{}]

    def _sync_jobs_to_faktory(self, cursor: Any, jobs_chunk: list[Any]) -> int:
        """Unwraps and pushes a chunk of safely parsed payloads to Faktory.

        Args:
            cursor (Any): An active database cursor execution handle.
            jobs_chunk (list): The raw sequence batch rows array tuple matrix.

        Returns:
            int: Total count of successfully transmitted background tasks.
        """
        import secrets

        faktory_payloads = []
        valid_count = 0

        for job_id, task_name, raw_payload in jobs_chunk:
            try:
                if isinstance(raw_payload, dict):
                    payload_data = raw_payload
                else:
                    if isinstance(raw_payload, bytes):
                        raw_payload = raw_payload.decode("utf-8")
                    payload_data = json.loads(raw_payload)

                if isinstance(payload_data, str):
                    payload_data = json.loads(payload_data)

                args = self._unwrap_payload_arguments(cursor, payload_data)

                unique_jid = f"job_{job_id}_{secrets.token_hex(4)}"
                faktory_payloads.append(
                    {
                        "jid": unique_jid,
                        "queue": "default",
                        "jobtype": task_name,
                        "args": args,
                    }
                )
                valid_count += 1

            except Exception as parse_err:
                logger.error(
                    "Failed to process job ID %s before bulk sync: %s",
                    str(job_id),
                    str(parse_err),
                )
                cursor.execute(
                    self.dialect.last_error_update_query,
                    (str(parse_err), job_id),
                )
                cursor.execute(
                    self.dialect.fail_status_update_query,
                    (
                        self.dialect.get_bool_value(True),
                        job_id,
                        self.max_delivery_retries,
                    ),
                )

        if faktory_payloads:
            logger.info("Connecting to %s", self.faktory_url)
            with faktory.connection(self.faktory_url) as client:
                success = client.push_bulk(faktory_payloads)
                if success is False:
                    raise RuntimeError(
                        "Faktory bulk pipeline rejected the buffered payloads"
                    )

        return valid_count

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
                self.db_connection.commit()
                return 0

            job_ids = [row[0] for row in jobs_chunk]
            logger.info(
                "Processing batch of %d jobs (IDs: %s)",
                len(jobs_chunk),
                job_ids,
            )

            processed_count = self._sync_jobs_to_faktory(cursor, jobs_chunk)

            for job_id in job_ids:
                cursor.execute(
                    self.dialect.success_update_query,
                    (self.dialect.get_bool_value(True), job_id),
                )

            self.db_connection.commit()
            return processed_count

        except Exception:
            self.db_connection.rollback()
            raise
        finally:
            cursor.close()

    def run_loop(
        self,
        min_sleep_seconds: float = 2.0,
        max_sleep_seconds: float = 60.0,
        batch_size: int = 50,
    ) -> None:
        """Runs the relay loop with exponential backoff.

        Args:
            min_sleep_seconds (float): Minimum seconds to wait when idle.
            max_sleep_seconds (float): Maximum seconds to wait during backoff.
            batch_size (int): Maximum number of jobs per iteration.
        """
        current_backoff_delay = min_sleep_seconds

        while True:
            try:
                processed_count = self.process_batch(batch_size=batch_size)
                current_backoff_delay = min_sleep_seconds

                if processed_count > 0:
                    # Micro-yield to let the OS scheduler switch threads and
                    # prevent CPU starvation.
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
                current_backoff_delay = min(
                    current_backoff_delay * 2, max_sleep_seconds
                )

    @staticmethod
    def mask_url_password(connection_url: str) -> str:
        """Removes the password from a connection URL for safe logging.

        Args:
            connection_url (str): Connection string containing credentials.

        Returns:
            str: The masked URL string with the password hidden.
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
