"""Service layer for the Faktory Outbox library.

This module provides the OutboxService class, which handles the creation of
outbox entries within Django database transactions to ensure atomic delivery.
"""

import json
from typing import Any, Dict, List, Optional

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import QuerySet

from .models import FaktoryOutbox


class OutboxService:
    """Service layer for atomic job registration."""

    @staticmethod
    def push_atomic(
        task_name: str,
        queryset: Optional[QuerySet] = None,
        raw_sql: Optional[str] = None,
        params: Optional[List[Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> FaktoryOutbox:
        """Registers a job within the current Django database transaction.

        Args:
            task_name (str): The target task name in the Faktory worker.
            queryset (QuerySet, optional): Django QuerySet to extract data from.
            raw_sql (str, optional): Raw SQL query string for complex extractions.
            params (list, optional): Parameters for the raw SQL query.
            data (dict, optional): Custom dictionary for manual payloads.

        Returns:
            FaktoryOutbox: The created outbox record instance.

        Raises:
            Exception: If data extraction or database insertion fails.
        """
        payload = {"mode": "custom", "content": data or {}}

        if queryset is not None:
            data_list = list(queryset.values())
            serialized_data = json.loads(json.dumps(data_list, cls=DjangoJSONEncoder))
            payload.update(
                {
                    "mode": "orm",
                    "model": str(queryset.model._meta),
                    "content": serialized_data,
                }
            )
        elif raw_sql:
            payload.update({"mode": "sql", "query": raw_sql, "params": params or []})

        with transaction.atomic():
            return FaktoryOutbox.objects.create(task_name=task_name, payload=payload)
