"""Database models for the Faktory Outbox engine.

This module defines the persistent database schema required to buffer
background tasks securely before they are relayed to the Faktory
server.
"""

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class FaktoryOutbox(models.Model):
    """Stores job metadata within transactional database boundaries.

    This model acts as a reliable FIFO queue buffer. Records are
    written within the same transaction as operational data,
    ensuring that if a database rollback occurs, the background job is
    also discarded.
    """

    task_name = models.CharField(max_length=255)

    # DjangoJSONEncoder is mandatory to support UUID, Decimal and
    # DateTime types stored from the OutboxService.
    payload = models.JSONField(encoder=DjangoJSONEncoder)

    created_at = models.DateTimeField(auto_now_add=True)
    processed = models.BooleanField(default=False)

    delivery_attempts = models.PositiveIntegerField(
        default=0,
        help_text="The total number of delivery attempts to Faktory.",
    )
    last_execution_error = models.TextField(
        blank=True,
        null=True,
        help_text="The system exception trace log of the last failure.",
    )
    is_failed = models.BooleanField(
        default=False,
        help_text="Flagged as true if delivery attempts breach limits.",
    )

    class Meta:
        """Metadata options for the FaktoryOutbox model."""

        db_table = "faktory_outbox"
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["created_at"],
                name="idx_outbox_pending_relay",
                condition=models.Q(processed=False, is_failed=False),
            ),
        ]

    def __str__(self) -> str:
        """Returns a string representation of the job status."""
        if self.processed:
            status_label = "Processed"
        elif self.is_failed:
            status_label = "Failed (DLQ)"
        else:
            status_label = f"Pending (Attempt {self.delivery_attempts})"
        return f"{self.task_name} - {status_label}"
