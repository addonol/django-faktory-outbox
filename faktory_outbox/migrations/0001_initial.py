"""Database migration file for the Faktory Outbox schema definitions.

This module initializes or modifies the persistent structural layout
required by the FaktoryOutbox model, including metrics fields and
optimized indexing.
"""

import django.core.serializers.json
from django.db import migrations, models


class Migration(migrations.Migration):
    """Structural operation registry for the outbox table schema."""

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="FaktoryOutbox",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("task_name", models.CharField(max_length=255)),
                (
                    "payload",
                    models.JSONField(
                        encoder=django.core.serializers.json.DjangoJSONEncoder
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "processed",
                    models.BooleanField(db_index=True, default=False),
                ),
                (
                    "delivery_attempts",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="The total number of delivery attempts to "
                        "Faktory.",
                    ),
                ),
                (
                    "last_execution_error",
                    models.TextField(
                        blank=True,
                        help_text="The system exception trace log of the last "
                        "failure.",
                        null=True,
                    ),
                ),
                (
                    "is_failed",
                    models.BooleanField(
                        default=False,
                        help_text="Flagged as true if delivery attempts "
                        "breach limits.",
                    ),
                ),
            ],
            options={
                "db_table": "faktory_outbox",
                "ordering": ["created_at"],
                "indexes": [
                    models.Index(
                        condition=models.Q(
                            ("is_failed", False), ("processed", False)
                        ),
                        fields=["created_at"],
                        name="idx_outbox_pending_relay",
                    )
                ],
            },
        ),
    ]
