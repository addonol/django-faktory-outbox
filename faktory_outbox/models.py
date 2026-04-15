"""Database models for the Faktory Outbox library.

This module defines the FaktoryOutbox model, which serves as a persistent
buffer to ensure atomic job queuing in distributed systems.
"""

from django.db import models


class FaktoryOutbox(models.Model):
    """Stores jobs persistently to guarantee atomicity during database operations.

    This model acts as a buffer. Jobs are committed here within the same
    transaction as business data, ensuring that if a database rollback occurs,
    the job is also rolled back.

    Attributes:
        task_name (str): The name of the worker task to be executed.
        payload (dict): JSON data containing job arguments or query details.
        created_at (datetime): Automated timestamp of creation.
        processed (bool): Status flag indicating if the job was sent to Faktory.
    """

    task_name = models.CharField(max_length=255)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    processed = models.BooleanField(default=False, db_index=True)

    class Meta:
        """Metadata options for the FaktoryOutbox model.

        Defines the database table name, default ordering, and optimized
        indexes for the relay engine performance.
        """

        db_table = "faktory_outbox"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["processed", "created_at"]),
        ]

    def __str__(self) -> str:
        """Returns a string representation of the job status."""
        return f"{self.task_name} ({'Processed' if self.processed else 'Pending'})"
