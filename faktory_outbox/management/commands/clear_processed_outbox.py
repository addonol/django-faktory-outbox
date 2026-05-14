"""Django management command to prune historical outbox records.

This module provides operational maintenance by removing safely processed
or quarantined failed records older than a retention threshold.
"""

import logging
import time
from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.utils import timezone

from faktory_outbox.models import FaktoryOutbox

logging.Formatter.converter = time.localtime
logger = logging.getLogger("faktory_outbox.prune")


class Command(BaseCommand):
    """Deletes historical logs from the outbox table to reclaim space."""

    help = "Safely prunes processed or failed outbox records older than X days."

    def add_arguments(self, parser: CommandParser) -> None:
        """Defines runtime configuration flags for execution control."""
        parser.add_argument(
            "--days",
            type=int,
            default=14,
            help="Retention threshold window in days (Default: 14).",
        )
        parser.add_argument(
            "--include-failed",
            action="store_true",
            help="If set, also removes dead-lettered quarantine records.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Executes database deletion queries based on parameter maps."""
        retention_days: int = options["days"]
        include_failed: bool = options["include_failed"]

        limit_timestamp = timezone.now() - timedelta(days=retention_days)

        prune_queryset = FaktoryOutbox.objects.filter(
            processed=True,
            created_at__lt=limit_timestamp,
        )

        if include_failed:
            failed_queryset = FaktoryOutbox.objects.filter(
                is_failed=True,
                created_at__lt=limit_timestamp,
            )
            prune_queryset = prune_queryset | failed_queryset

        total_records_found = prune_queryset.count()

        if total_records_found == 0:
            self.stdout.write("Outbox table is already clean. No records to prune.")
            return

        try:
            with transaction.atomic():
                deleted_count, _ = prune_queryset.delete()

            self.stdout.write(
                f"Successfully pruned {deleted_count} historical records "
                f"older than {retention_days} days."
            )

        except Exception as deletion_error:
            logger.error(
                "Failed to execute outbox pruning transaction: %s",
                str(deletion_error),
            )
            raise
