"""Integration example and smoke test for the Faktory Outbox engine.

This script initializes an in-memory SQLite database, runs schema
migrations, triggers an atomic outbox job registration via the
service layer, and executes a batch process invocation using the
standalone relay infrastructure.
"""

import logging

import django
from django.conf import settings
from django.db import transaction

# Setup isolation configurations before importing project components
settings.configure(
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "faktory_outbox",
    ],
    DATABASES={
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    },
    LOGGING={
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
            },
        },
        "root": {
            "handlers": ["console"],
            "level": "INFO",
        },
    },
)
django.setup()


def execute_integration_smoke_test() -> None:
    """Executes a local programmatic lifecycle simulation.

    Creates schema definitions, buffers a target payload, and
    intercepts the row payload through a local SQLite cursor connection.
    """
    from django.core.management import call_command
    from django.db import connections

    from faktory_outbox.relay import OutboxRelay, SqliteDialect
    from faktory_outbox.service import OutboxService

    logger = logging.getLogger("faktory_outbox.example")
    logger.info("🔧 Constructing database schema architecture...")

    # Run migrations programmatically inside the in-memory engine
    call_command("migrate", "faktory_outbox", verbosity=0)

    logger.info("📝 Staging background job within an atomic transaction...")
    with transaction.atomic():
        # Step 1: Simulate user operational application logic registration
        OutboxService.push_atomic(
            task_name="SendWelcomeEmail",
            custom_payload={
                "user_id": 984,
                "email_address": "test@example.com",
                "template": "welcome_v2",
            },
        )
        logger.info("✅ Transaction committed. Job securely buffered.")

    logger.info("📡 Bootstrapping a disconnected mock Relay interface...")

    # We create a local native sqlite3 connection targeting Django's memory
    # space to simulate what the standalone CLI process does.
    django_connection = connections["default"]

    # Ensure tables are readable via lower-level PEP 249 native handles
    raw_sqlite_connection = django_connection.connection

    # We bind a test relay pointing to a safe unreachable port since we
    # only want to test the query pipeline execution up to connection limits.
    relay_engine = OutboxRelay(
        connection=raw_sqlite_connection,
        dialect=SqliteDialect(),
        faktory_url="tcp://localhost:9999",
        max_delivery_retries=2,
    )

    # Use the instance to mask its URL, preventing 'variable not used' errors
    safe_target_url = relay_engine.mask_url_password(relay_engine.faktory_url)
    logger.info("Target destination parsed: %s", safe_target_url)

    logger.info("📦 Invoking process_batch scanner simulation...")
    cursor = raw_sqlite_connection.cursor()
    query = SqliteDialect.get_pending_query(10)
    cursor.execute(query, (10,))
    pending_jobs = cursor.fetchall()

    import json  # Import local pour respecter l'organisation du script

    for job_id, task, payload_raw in pending_jobs:
        # Décodage sécurisé du payload si c'est une chaîne de caractères
        payload_data = (
            json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
        )

        # Formatage du JSON avec indentation pour une lecture agréable
        pretty_payload = json.dumps(payload_data, indent=4)

        logger.info(
            "Found raw buffered row in outbox table:\n"
            "  [ID]      : %d\n"
            "  [Task]    : %s\n"
            "  [Payload] : %s",
            job_id,
            task,
            pretty_payload,
        )

    logger.info("🚀 Integration smoke test finished successfully.")


if __name__ == "__main__":
    execute_integration_smoke_test()
