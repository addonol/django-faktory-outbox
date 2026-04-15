"""Initial migration for the Faktory Outbox application.

This module contains the database schema definition for the FaktoryOutbox model,
including optimized indexes for job processing.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Initial migration for FaktoryOutbox model."""

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
                ("payload", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("processed", models.BooleanField(db_index=True, default=False)),
            ],
            options={
                "db_table": "faktory_outbox",
                "ordering": ["created_at"],
                "indexes": [
                    models.Index(
                        fields=["processed", "created_at"],
                        name="faktory_out_process_d936a5_idx",
                    )
                ],
            },
        ),
    ]
