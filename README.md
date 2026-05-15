# Django Faktory Outbox

A transactional outbox package for Django and Faktory.

This package ensures that background jobs are only delivered to Faktory if your primary database transaction succeeds. If your business logic crashes or your database triggers a rollback, the background task is automatically discarded.

## How it works

When a user buys a product or signs up on your website:

1. **The Fast Write (Local Database)**
   * Your Django view opens a standard SQL transaction, saves your core business models (e.g., Invoices, Users), and simultaneously inserts a raw row into the `faktory_outbox` table via `OutboxService.push_atomic()`.
   * Because this operation writes exclusively to your local database, the query finishes in a couple of milliseconds. Your user gets a success response instantly, keeping the UI snappy.

2. **The Safe Holding Buffer**
   * The task sits safely in the outbox table flagged with `processed = False` and `is_failed = False`.
   * Your relational database acts as a durable vault. Even if your web servers or container nodes restart right at this moment, no tasks are lost.

3. **The Bulk Dispatch**
   * Completely separate from Django, the standalone `OutboxRelay` daemon sweeps the database table for pending records in the background.
   * Instead of looping over rows and spamming Faktory with sequential 1-by-1 network requests, the relay bundles the entire batch in memory and fires it over a recycled TCP socket in a single network round-trip using the native `PUSHB` (Push Bulk) protocol command.
   * If the network splits, the Relay triggers a database `rollback()` to keep records locked safely, then enters an Exponential Backoff loop (waiting 2s, 4s, 8s... up to 60s) so it doesn't burn your CPU or saturate network interfaces.

## One Package, Two Roles

The package is installed all at once but splits into two distinct operational layers:

*   **The Ingress Layer (`OutboxService`)**: The Python API you import directly into your Django application views or tasks to stage background jobs right alongside your models.
*   **The Egress Layer (`OutboxRelay`)**: An independent background daemon (run via a CLI command or as an isolated, non-privileged container node). It continuously pulls the table queue and streams the batches over to Faktory.

## Key Features

*   **Absolute Consistency**: Eliminates the classic edge case where a user receives a success confirmation email while your database failed to actually save their order records.
*   **High-Throughput Bulk Batching**: Leverages native protocol `PUSHB` frames to ship entire arrays of jobs simultaneously, crushing network overhead and maximizing synchronization velocity.
*   **Strict Network Isolation**: Web-worker threads never talk to the message broker during HTTP loops. Your website stays fast even if Faktory goes down completely.
*   **Horizontal Relay Scaling**: Built from the ground up to utilize database `FOR UPDATE SKIP LOCKED` clauses (PostgreSQL and Oracle). Run multiple parallel relay instances concurrently without any overlapping or duplicate task risks.
*   **Memory-Safe Processing**: Database query extractions stream data using low-level chunked cursors. Buffer thousands of lines without triggering Out-Of-Memory (OOM) crashes.
*   **Granular Failure Isolation (DLQ)**: Try-except blocks catch failures line-by-line. Corrupted or un-serializable payloads automatically increment retry trackers and move to quarantine without blocking valid companion tasks inside the same bulk batch.



## Package Integration Guide

### 1. Enforcing Atomic Task Registration
Wrap your operations inside a Django transaction.atomic() block. If any error occurs before the block finishes, nothing is permanently written to either your business tables or your outbox buffer.

```python
from django.db import transaction
from faktory_outbox.service import OutboxService

with transaction.atomic():
    # 1. Execute your standard core database logic queries
    order = Order.objects.create(amount=100)

    # 2. Register the associated task to the database buffer table
    OutboxService.push_atomic(
        task_name="ProcessPayment",
        custom_payload={"order_id": order.id}
    )

    # If the system crashes here, both database mutations roll back completely.

```

### 2. Supported Extraction Modes
The Python service provides three extraction modes built for varied computing scales:

```python
from django.contrib.auth.models import User
from faktory_outbox.service import OutboxService

# --- Mode A: Custom Static Data ---
# Best for pre-computed, small dictionaries or flat IDs.
OutboxService.push_atomic(
    task_name="SendNotification",
    custom_payload={"user_id": 42, "message": "Hello World"}
)

# --- Mode B: Django QuerySet ---
# Automatically extracts fields line-by-line using low-overhead cursors.
# Natively converts complex primitives like UUID, Decimal, and DateTime.
active_users = User.objects.filter(is_active=True)
OutboxService.push_atomic(
    task_name="SyncUsers",
    queryset=active_users
)

# --- Mode C: Just-In-Time Raw SQL Execution ---
# Bypasses expensive data evaluation during the active HTTP request lifecycle.
# The query structure is recorded, and evaluation is deferred to the Relay.
raw_query = "SELECT id, email FROM auth_user WHERE date_joined > %s"
query_params = ["2026-01-01"]
OutboxService.push_atomic(
    task_name="ExportAuditLog",
    raw_sql=raw_query,
    sql_parameters=query_params
)
```

### 3. Automated Database Maintenance (Pruning)

As tasks are successfully processed by the relay daemon, historical logs accumulate in the faktory_outbox table. To prevent unlimited database storage growth and maintain optimal index execution speeds, the package provides a native Django administrative management command.

You can run this command manually or hook it to a periodic orchestrator (e.g., Unix Cron, Kubernetes CronJob, or Django Celery Beat):

```bash
# Safely deletes processed entries older than 14 days (Default configuration)
python manage.py clear_processed_outbox

# Customize the retention window threshold to 7 days
python manage.py clear_processed_outbox --days=7

# Force removal of both safely processed records AND old quarantined DLQ failures
python manage.py clear_processed_outbox --days=30 --include-failed
```

Operational safety is built-in:
*   The execution strictly targets records where `processed=True`. Active or pending job queues are completely untouched.
*   Quarantined dead-lettered failures (`is_failed=True`) are highly valuable for debugging and are never removed unless you explicitly pass the `--include-failed` flag.


## Local Development & Demonstration Toolkit

For development, testing, and evaluation purposes, this repository includes a complete multi-container orchestration stack. The environment is assembled using a locally built non-root image and a pre-configured docker-compose.yml file to spin up 4 operational containers, each serving a precise architectural role:

*   **database (postgres:16-alpine):** Acts as the primary database cluster. It stores your application profiles alongside the persistent faktory_outbox task staging table.
*   **message_broker (contribsys/faktory:latest):** The centralized background job broker. It receives incoming task messages via TCP, hosts the task queues, and exposes the web management dashboard.
*   **django_application (Local Build):** Simulates active customer-facing web traffic. It runs a continuous loop that executes business logic and calls OutboxService to buffer background tasks into PostgreSQL.
*   **relay_worker (Local Build):** Executes the standalone OutboxRelay synchronization daemon. It runs independently from the web app, continuously sweeping the PostgreSQL table via lock-free SKIP LOCKED queries to flush pending rows to the faktory broker.



### 1. Environment Configuration

1. Copy the environment configuration template file:

    ```bash
    cp .env.example .env
    ```

2. Open the newly created .env file and customize your variables as needed.


    | Variable | Target Scope | Description |
    |----------|---------|-------------|
    | DB_USER / DB_PASSWORD | Base Database | Credentials used to initialize target database containers. |
    | DB_NAME | Base Database | The target schema name allocated on the active database service. |
    | DATABASE_URL | Core Application | Connection URI defining the dialect and target connection configurations. |
    | FAKTORY_PASSWORD | Message Broker | BrokerPassword used to secure access to the Faktory network. |
    | RELAY_BATCH_SIZE | Relay Engine | Total row chunk limits parsed per database fetch operation (Default: 50). |
    | RELAY_DEBUG | Relay Engine | Toggles verbosity for daemon lifecycle, heartbeats, and connection logs. |


### 2. Development Command Hub

Use the provided Makefile to control the local infrastructure and track execution:

```bash
# Display the interactive help panel dashboard listing all targets
make help

# Full clean, container tear-down, and secure image build sequence
make dev-reset

# Spin up PostgreSQL and Faktory containers in the background
make infra-up-postgres

# Spin up MariaDB and Faktory containers in the background
make infra-up-mariadb

# Spin up MySQL and Faktory containers in the background
make infra-up-mysql

# Stop infrastructure containers and clear active volumes
make infra-down

# Follow the live Django Application traffic and task generation loop
make demo

# Follow the standalone outbox relay synchronization stream logs
make relay

# Monitor running infrastructure log outputs for all containers
make logs
```


### 3. What Happens Under the Hood (Step-by-Step Execution)

When you run a demonstration environment (e.g., make infra-up-postgres), the
stack choreographs the entire lifecycle automatically:

1. **Infrastructure Initialization:** The active database engine (Postgres,
   MariaDB, or MySQL) and Faktory server containers bootstrap and open their
   respective network ports.
2. **Database Schema Preparation:** The django_application container starts,
   halts temporarily to await database readiness via healthchecks, and triggers
   the execution loop. This script automatically runs the necessary Django SQL
   migrations to create the package tables dynamically on the target backend.
3. **Continuous Traffic Simulation:** Once initialized, the django_application
   enters an active loop, automatically creating a new test outbox job entries
   with variable payload models every few seconds.
4. **Asynchronous Relay Processing:** The relay_worker container boots
   independently, establishes a persistent handle against the configured
   database, locks incoming unprocessed rows using the dialect parameter styles
   and native SKIP LOCKED clauses, and flushes them down the pipeline to the
   Faktory broker.


### 4. Monitoring the Pipeline in Real Time

*   **Watch the Relay Sync Stream:** Open a new terminal tab and run make
    relay. This tracks the relay_worker system logs, showing your job chunks
    being picked up and synchronized over the network continuously.
*   **Check the Broker UI:** Open your preferred web browser and navigate to
    http://localhost:7420. This opens the official Faktory web dashboard, where
    you can watch the queues fill up and monitor the tasks arriving in real
    time.
