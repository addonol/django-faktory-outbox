"""Demonstration script for the Faktory Outbox pattern.

This script executes a visual walkthrough of atomic transactions,
demonstrating how the library guarantees data consistency even during crashes.
"""

import logging
import os
import sys
import time

import django
from django.core.management import call_command
from django.db import transaction

logging.Formatter.converter = time.localtime
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("outbox_demo")


def log_separator() -> None:
    """Prints a subtle horizontal separator line."""
    logger.info("─" * 70)


def log_header(title: str) -> None:
    """Prints a section header for the demonstration steps.

    Args:
        title: The text to display as the section title.
    """
    logger.info("")
    logger.info("◈ %s", title.upper())
    log_separator()


def run_demo() -> None:
    """Executes the outbox demonstration scenarios with visual feedback.

    Scenario 1: Verifies atomic rollback when an exception occurs.
    Scenario 2: Verifies successful commitment when logic finishes correctly.
    """
    from demo_app.models import LegacyRecord

    from faktory_outbox.models import FaktoryOutbox
    from faktory_outbox.service import OutboxService

    log_header("🚀 Starting Django Faktory Outbox Demo")
    time.sleep(0.5)

    log_header("1. Scenario: Atomic Rollback on Crash")
    logger.info("Target:  Guarantee that no job is queued if processing fails.")

    with transaction.atomic():
        try:
            LegacyRecord.objects.create(external_id=101, data_payload="Ghost Data")
            OutboxService.push_atomic("process_data", data={"id": 101})
            logger.info("Action:  Data staged in transaction. Triggering crash...")

            raise ValueError("Simulated Processing Exception")

        except ValueError as exc:
            transaction.set_rollback(True)
            logger.warning("Status:  %s caught. Rolling back...", exc)

    record_exists = LegacyRecord.objects.filter(external_id=101).exists()
    job_exists = FaktoryOutbox.objects.filter(task_name="process_data").exists()

    if not record_exists and not job_exists:
        logger.info("Result:  🛡️  Success. Database remains clean.")
    else:
        logger.error("Result:  ❌ Failure. Atomicity was breached.")

    time.sleep(0.8)

    log_header("2. Scenario: Successful Transaction")
    logger.info("Target:  Confirm that jobs are persisted when logic succeeds.")

    with transaction.atomic():
        LegacyRecord.objects.create(external_id=202, data_payload="Valid Data")
        OutboxService.push_atomic("process_data", data={"id": 202})
        logger.info("Action:  Committing business data and job simultaneously...")

    final_count = FaktoryOutbox.objects.count()
    logger.info("Result:  💎 Success. Total jobs in outbox: %d", final_count)

    logger.info("")
    log_separator()
    logger.info("🏁 DEMO COMPLETE - Check Relay logs for transmission status")
    logger.info("Faktory UI: http://localhost:7420")
    log_separator()
    logger.info("")


if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")
    django.setup()

    from django.db import connection

    print(f"DEBUG: Django is using database: {connection.settings_dict['NAME']}")
    print(f"DEBUG: Engine: {connection.settings_dict['ENGINE']}")
    print(f"DEBUG: Host: {connection.settings_dict.get('HOST', 'N/A')}")

    if "--only-migrate" in sys.argv:
        from django.db import connections

        logger.info("🔧 Preparing database: Running migrations...")
        call_command("migrate", verbosity=0)

        for conn in connections.all():
            conn.close()
        sys.exit(0)

    run_demo()
