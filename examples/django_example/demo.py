"""Demonstration script simulating an operational invoicing outbox workflow.

This standalone utility boots an isolated Django environment, ensures
database schemas are initialized, and triggers atomic registration
examples simulating transactional invoicing operations.
"""

import logging
import os
import sys
import time
from urllib.parse import urlparse

import django
from django.conf import settings
from django.core.management import call_command
from django.db import DEFAULT_DB_ALIAS, transaction
from django.utils import timezone

DATABASE_CONNECTION_URL = os.getenv(
    "DATABASE_URL", "postgres://user:demo_password_123@database:5432/outbox_db"
)

parsed_url = urlparse(DATABASE_CONNECTION_URL)
database_port = parsed_url.port if parsed_url.port else 5432
database_name = parsed_url.path.lstrip("/")

settings.configure(
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "django.contrib.admin",
        "django.contrib.auth",
        "faktory_outbox",
    ],
    DATABASES={
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": database_name,
            "USER": parsed_url.username,
            "PASSWORD": parsed_url.password,
            "HOST": parsed_url.hostname,
            "PORT": str(database_port),
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

logging.Formatter.converter = time.localtime
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("faktory_outbox.demo")


def run_production_demo_pipeline() -> None:
    """Executes atomic outbox invoice job injection simulation patterns."""
    if "--only-migrate" in sys.argv:
        logger.info("Initializing package database schemas...")
        call_command("migrate", verbosity=0)
        logger.info("Schema migrations applied successfully.")
        return

    logger.info("Starting continuous invoice creation factory simulation...")

    system_user, _ = User.objects.get_or_create(
        username="system_invoice", defaults={"email": "system@example.com"}
    )

    try:
        while True:
            try:
                with transaction.atomic(using=DEFAULT_DB_ALIAS):
                    unique_timestamp = int(time.time() * 1000)
                    dummy_content_type = ContentType.objects.get_for_model(ContentType)

                    invoice_amount = unique_timestamp % 5000
                    message_template = (
                        f"Invoice generated for Amount: ${invoice_amount}.00"
                    )

                    mock_invoice: LogEntry = LogEntry.objects.create(
                        action_time=timezone.now(),
                        object_id=str(unique_timestamp),
                        object_repr=f"INV-{unique_timestamp}",
                        action_flag=1,
                        change_message=message_template,
                        content_type=dummy_content_type,
                        user=system_user,
                    )

                    invoice_queryset = LogEntry.objects.filter(pk=mock_invoice.pk)
                    OutboxService.push_atomic(
                        task_name="ProcessGeneratedInvoice",
                        queryset=invoice_queryset,
                        database_alias=DEFAULT_DB_ALIAS,
                    )

                    customer_notification_parameters = {
                        "invoice_reference": f"INV-{unique_timestamp}",
                        "customer_email": f"client_{unique_timestamp}@env.com",
                        "trigger_pdf_generation": True,
                    }
                    OutboxService.push_atomic(
                        task_name="SendInvoiceEmailNotification",
                        custom_payload=customer_notification_parameters,
                        database_alias=DEFAULT_DB_ALIAS,
                    )

                    logger.info(
                        "Buffered transactional invoice tasks for reference: %s",
                        mock_invoice.object_repr,
                    )

                time.sleep(5.0)

            except Exception as operational_error:
                logger.error(
                    "Invoicing simulation cycle failed: %s", str(operational_error)
                )
                time.sleep(5.0)

    except KeyboardInterrupt:
        logger.info("")
        logger.info("🛑 Shutdown requested by user...")
    finally:
        from django.db import connections

        if "default" in connections:
            connections["default"].close()
            logger.info("🔌 Database connection closed.")

        logger.info("👋 Application stopped gracefully. Goodbye!")


if __name__ == "__main__":
    from django.contrib.admin.models import LogEntry
    from django.contrib.auth.models import User
    from django.contrib.contenttypes.models import ContentType

    from faktory_outbox.service import OutboxService

    run_production_demo_pipeline()
