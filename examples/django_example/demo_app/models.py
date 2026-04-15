"""Data models for the demonstration application.

This module defines models that simulate legacy data structures,
such as records typically extracted from an external data source.
"""

from django.db import models


class LegacyRecord(models.Model):
    """Simulates a record extracted from an external data source.

    This model is used to verify that business data and outbox jobs
    are committed or rolled back together, regardless of the source database.

    Attributes:
        external_id (int): The original ID from the source system.
        data_payload (str): The raw data content of the record.
    """

    external_id = models.IntegerField()
    data_payload = models.TextField()

    class Meta:
        """Metadata options for the LegacyRecord model.

        Defines the human-readable names for the demonstration records.
        """

        verbose_name = "Legacy Record"
        verbose_name_plural = "Legacy Records"

    def __str__(self) -> str:
        """Returns a string representation of the record.

        Returns:
            str: The record identifier including its external ID.
        """
        return f"LegacyRecord {self.external_id}"
