"""High-performance batch producer demonstration for Faktory PUSHB.

This module demonstrates the custom PUSHB (batch push) implementation from
our Faktory fork. It bypasses the database outbox to showcase the raw
network performance of dispatching multiple jobs in a single round-trip.
"""

import logging
import os
import time

from faktory import Client

logging.Formatter.converter = time.localtime
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("batch_producer")


def run_batch_producer(
    faktory_url: str = "tcp://localhost:7419",
    task_name: str = "batch-demo",
    batch_size: int = 1000,
    interval: int = 2,
) -> None:
    """Queues Faktory jobs in batches at regular intervals using PUSHB.

    This producer connects directly to the Faktory server and dispatches
    a collection of jobs using the high-performance batch protocol.

    Args:
        faktory_url: The connection URL for the Faktory server.
            Defaults to "tcp://localhost:7419".
        task_name: The name of the task to be enqueued. Defaults to "add".
        batch_size: Number of jobs to include in each bulk push.
            Defaults to 1000.
        interval: Seconds to wait between batch dispatches. Defaults to 2.

    Raises:
        OSError: If a network-level connection error occurs.
        ConnectionRefusedError: If the Faktory server is unreachable.
    """
    logger.info("🚀 Starting Batch Producer")
    logger.info(
        "Target: %s | Task: %s | Batch Size: %d", faktory_url, task_name, batch_size
    )

    try:
        with Client(faktory=faktory_url) as client:
            while True:
                jobs = [
                    {"jid": os.urandom(8).hex(), "jobtype": task_name, "args": (i, i + 1)}
                    for i in range(batch_size)
                ]

                logger.info("📦 Dispatching bulk push (%d jobs)...", len(jobs))
                start_time = time.time()

                if client.push_bulk(jobs):
                    duration = time.time() - start_time
                    logger.info("✅ Batch accepted in %.4fs", duration)
                else:
                    logger.error("❌ Batch rejected by Faktory server.")

                logger.info("😴 Sleeping %ds...", interval)
                time.sleep(interval)

    except (ConnectionRefusedError, OSError) as e:
        logger.error("❌ Connection failed: %s", e)
    except KeyboardInterrupt:
        logger.info("\n🛑 Producer stopped by user. Goodbye!")


if __name__ == "__main__":
    f_url = os.getenv("FAKTORY_URL", "tcp://localhost:7419")
    b_size = int(os.getenv("STRESS_COUNT", 1000))

    run_batch_producer(faktory_url=f_url, batch_size=b_size)
