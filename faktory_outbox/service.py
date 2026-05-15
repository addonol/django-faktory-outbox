"""Service layer for the Faktory Outbox engine.

This module exposes the operational service API required to stage
background tasks atomically alongside core application database
changes.
"""

from typing import Any, Optional

from django.db import DEFAULT_DB_ALIAS, transaction
from django.db.models import QuerySet

from .models import FaktoryOutbox


class OutboxTransactionError(Exception):
    """Raised when outbox registration fails.

    The registration was attempted outside an active database
    transaction context block.
    """

    pass


class OutboxService:
    """Service layer providing transactional job isolation mechanics."""

    @staticmethod
    def push_atomic(
        task_name: str,
        queryset: Optional[QuerySet[Any]] = None,
        raw_sql: Optional[str] = None,
        sql_parameters: Optional[list[Any]] = None,
        custom_payload: Optional[dict[str, Any]] = None,
        database_alias: str = DEFAULT_DB_ALIAS,
    ) -> FaktoryOutbox:
        """Registers a background task inside the active transaction.

        Guarantees that the background job metadata is written to the
        outbox database buffer only if the outer application
        transaction succeeds. If a database rollback occurs, the
        background job submission is undone.

        Args:
            task_name (str): The identifier of the destination task
                configured on the Faktory worker instances.
            queryset (QuerySet, optional): A lazy Django QuerySet.
                Records are extracted using database cursors to
                preserve a low application memory footprint.
            raw_sql (str, optional): A raw SQL command string used
                for high-performance complex database extractions.
            sql_parameters (list[Any], optional): Parameters matching
                positional placeholders within the `raw_sql` string.
            custom_payload (dict[str, Any], optional): A standard
                dictionary containing pre-computed variables.
            database_alias (str): The configuration routing alias
                targeting a specific database engine.

        Returns:
            FaktoryOutbox: The newly written persistent outbox record.

        Raises:
            OutboxTransactionError: If invoked while auto-commit is
                active or outside a valid transaction context.
        """
        db_connection = transaction.get_connection(database_alias)

        if not db_connection.in_atomic_block:
            raise OutboxTransactionError(
                f"The method 'push_atomic' must be executed within "
                f"an active transaction.atomic() context block for "
                f"database: '{database_alias}'."
            )

        serialized_payload: dict[str, Any] = {
            "mode": "custom",
            "content": custom_payload or {},
        }

        if queryset is not None:
            queryset_iterator = queryset.values().iterator(chunk_size=1000)
            serialized_payload.update(
                {
                    "mode": "orm",
                    "model_identifier": str(queryset.model._meta),
                    "content": list(queryset_iterator),
                }
            )
        elif raw_sql:
            serialized_payload.update(
                {
                    "mode": "sql",
                    "query_string": raw_sql,
                    "parameters": sql_parameters or [],
                }
            )

        return FaktoryOutbox.objects.using(database_alias).create(
            task_name=task_name, payload=serialized_payload
        )
