"""Stress test script to inject multiple jobs into the outbox."""

import logging
import os

import django
from django.db import transaction

logging.basicConfig(level=logging.INFO, format="%(asctime)s │ %(message)s")
logger = logging.getLogger("stress_test")


def run_stress_test(job: int) -> None:
    """Injects jobs into the outbox.

    The number of jobs is controlled by the STRESS_COUNT environment variable.
    """
    from demo_app.models import LegacyRecord

    from faktory_outbox.service import OutboxService

    logger.info("🚀 Injecting %d jobs into the database...", job)

    with transaction.atomic():
        for i in range(job):
            external_id = 1000 + i
            LegacyRecord.objects.create(
                external_id=external_id, data_payload=f"Stress test data batch {i}"
            )
            OutboxService.push_atomic(
                task_name="stress_task", data={"id": external_id, "index": i}
            )

    logger.info("✅ Done! %d jobs are now waiting in the outbox.", job)


if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")
    django.setup()
    run_stress_test(int(os.environ.get("STRESS_COUNT", 100)))
