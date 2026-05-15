"""Integration example and multi-DB smoke test for the Faktory Outbox.

This script parses a target DATABASE_URL from the runtime environment,
configures the isolated Django engine routing, triggers continuous atomic
outbox invoice registrations, and relies on the standalone daemon.
"""

import logging
import os
import secrets
import socket
import sys
import time
import urllib.parse as urlparse

import django
from django.conf import settings
from django.db import transaction

logger = logging.getLogger("faktory_outbox.example")

database_url = os.getenv("DATABASE_URL", "sqlite:///:memory:")
db_url_lower = database_url.lower()

if "postgres" in db_url_lower:
    target_engine = "django.db.backends.postgresql"
elif "mariadb" in db_url_lower or "mysql" in db_url_lower:
    target_engine = "django.db.backends.mysql"
else:
    target_engine = "django.db.backends.sqlite3"

parsed_url = urlparse.urlparse(database_url)
db_name = parsed_url.path.lstrip("/") if "sqlite" not in db_url_lower else ""

if target_engine == "django.db.backends.sqlite3" and not db_name:
    db_name = ":memory:"

if "sqlite" not in db_url_lower:
    target_host = parsed_url.hostname or "localhost"
    default_port = 3306 if "postgres" not in db_url_lower else 5432
    target_port = parsed_url.port or default_port

    print(
        f"⏳ Awaiting remote backend engine on {target_host}:{target_port}..."
    )
    for attempt in range(1, 31):
        try:
            with socket.create_connection(
                (target_host, target_port), timeout=1
            ):
                print("🔌 Connection path available! Resuming setup.")
                break
        except (OSError, ConnectionRefusedError):
            time.sleep(1)
    else:
        print("❌ Database engine network allocation timeout. Aborting.")
        sys.exit(1)

settings.configure(
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "faktory_outbox",
    ],
    DATABASES={
        "default": {
            "ENGINE": target_engine,
            "NAME": db_name,
            "USER": urlparse.unquote(parsed_url.username or ""),
            "PASSWORD": urlparse.unquote(parsed_url.password or ""),
            "HOST": parsed_url.hostname or "localhost",
            "PORT": str(parsed_url.port or ""),
        }
    },
    LOGGING={
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {"console": {"class": "logging.StreamHandler"}},
        "root": {"handlers": ["console"], "level": "INFO"},
    },
)
django.setup()


def execute_integration_smoke_test() -> None:
    """Executes a dynamic lifecycle simulation based on parameters.

    Creates database schemas via migrations and enters an infinite loop
    staging unique invoice payloads every 3 seconds to feed the relay.
    """
    from django.core.management import call_command

    from faktory_outbox.service import OutboxService

    logger.info("🔧 Constructing database schema architecture...")
    call_command("migrate", "faktory_outbox", verbosity=0)

    logger.info("🚀 Starting continuous invoice background generation...")

    invoice_counter = 1000

    while True:
        try:
            invoice_counter += 1
            secure_roll = secrets.randbelow(43450) + 1550
            random_amount = round(secure_roll / 100.0, 2)

            with transaction.atomic():
                OutboxService.push_atomic(
                    task_name="ProcessInvoicePayment",
                    custom_payload={
                        "invoice_id": invoice_counter,
                        "customer_email": (
                            f"client_{invoice_counter}@example.com"
                        ),
                        "amount": random_amount,
                        "currency": "EUR",
                        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )
                logger.info(
                    "✅ Invoice #%d [Amount: %s EUR] securely staged.",
                    invoice_counter,
                    str(random_amount),
                )
            time.sleep(3)

        except KeyboardInterrupt:
            logger.info("🛑 Stopping background generator execution.")
            break


if __name__ == "__main__":
    execute_integration_smoke_test()
