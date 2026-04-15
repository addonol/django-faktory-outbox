"""Migration file for the demo_app models.

This module defines the initial database schema for LegacyRecord,
including its fields and metadata options.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Initial migration for the LegacyRecord model.

    This migration creates the 'LegacyRecord' table with its
    external ID and data payload fields.
    """

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="LegacyRecord",
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
                ("external_id", models.IntegerField()),
                ("data_payload", models.TextField()),
            ],
            options={
                "verbose_name": "Legacy Record",
                "verbose_name_plural": "Legacy Records",
            },
        ),
    ]
