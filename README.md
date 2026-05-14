# Django Faktory Outbox

A transactional outbox package for Django and Faktory.

This package ensures that background jobs are only delivered to Faktory if your primary database transaction succeeds. If your business logic crashes or your database triggers a rollback, the background task is automatically discarded.

## How it works

When a user executes an action on your website (e.g., purchasing an item or signing up):

*   Your Django view opens a standard SQL transaction, writes to the business models, and inserts the task metadata into the faktory_outbox table using OutboxService.push_atomic().
*   Because this operation writes exclusively to your local database, the query completes in milliseconds.
*   The user receives their HTTP success response immediately. From the user's perspective, the application works perfectly.

*   The task records are stored securely in the outbox table, flagged with processed = False and is_failed = False.
*   The relational database acts as a durable, persistent buffer. Staged jobs accumulate safely in the table. They cannot be lost or cleared, even if your web servers or container nodes restart unexpectedly.

*   The standalone OutboxRelay engine successfully queries the database for the next available chunk of jobs (since the DB is operational).
*   It attempts to establish a connection over the network to the Faktory server, which fails (e.g., throwing a ConnectionRefusedError).
*   The Relay instantly triggers a database rollback(): The fetched tasks remain locked inside the database and their states are preserved as unprocessed (processed = False). No data is corrupted, and no records are skipped.
*   The loop catches the network exception and initiates the Exponential Backoff Strategy:
    * It sleeps for a baseline period (e.g., 2 seconds) before retrying.
    * If Faktory remains offline, the sleep interval doubles on each subsequent failure cycle (4s, 8s, 16s...) up to a hard ceiling (max_sleep_seconds = 60.0).
    * This mechanism protects your system by preventing a dead connection loop from starving your CPU or flooding network interfaces.


## Core Components

The repository delivers two separate sub-systems:

*   **The Capture Layer (OutboxService)**: The Python package you import directly into your Django application code. It provides an API to save task definitions alongside your standard models.

*   **The Synchronization Layer (OutboxRelay)**: An independent background engine (run via a CLI command or as a non-root Docker/Podman container). It continuously sweeps the table using SKIP LOCKED queries, flushes messages to Faktory, and commits statuses atomically.


## Key Features

*   **Absolute Consistency**: Eliminates edge cases where a user receives a success confirmation while your database failed to save their order records.
*   **Strict Network Isolation**: Protects your application threads from web-worker latency, broker connection drops, or broker downtime. Your HTTP views respond at full speed.
*   **Horizontal Relay Scaling**: Native integration with database FOR UPDATE SKIP LOCKED clauses (PostgreSQL and Oracle). Multiple parallel relay instances run concurrently without ever overlapping or duplication risks.
*   **Memory-Safe Extractions**: QuerySet extraction streams data chunks using database-level cursors (chunk_size=1000). You can buffer thousands of rows without triggering Out-Of-Memory (OOM) crashes.
*   **Built-in Fault Isolation (DLQ)**: Granular try-except blocks isolate delivery failures line-by-line. Corrupted or un-serializable payloads automatically increment retry trackers and move to quarantine without blocking valid companion tasks.




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
    | DB_USER / DB_PASSWORD | Base Database | Credentials used to initialize the PostgreSQL service container. |
    | DB_NAME | Base Database | The target schema name allocated on the PostgreSQL service. |
    | FAKTORY_PASSWORD | Message Broker | BrokerPassword used to secure access to the Faktory broker network. |
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
make infra-up

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

When you run the demonstration environment (make dev-reset), the 4-container stack choreographs the entire lifecycle automatically:

1. **Infrastructure Initialization:** The database (PostgreSQL) and faktory server containers bootstrap and open their respective network ports.
2. **Database Schema Preparation:** The django_application container starts, halts temporarily to await database readiness, and triggers the entrypoint.sh wrapper script. This script automatically runs the necessary Django SQL migrations to create the package tables.
3. **Continuous Traffic Simulation:** Once initialized, the django_application enters an active loop, automatically creating a new test user and a companion outbox job every 5 seconds.
4. **Asynchronous Relay Processing:** The relay_worker container boots independently, establishes a persistent handle against the same PostgreSQL database, locks incoming unprocessed rows, and flushes them down the pipeline to the faktory server broker.


### 4. Monitoring the Pipeline in Real Time

*   **Watch the Relay Sync Stream:** Open a new terminal tab and run make relay. This tracks the relay_worker system logs, showing your job chunks being picked up and synchronized over the network continuously.
*   **Check the Broker UI:** Open your preferred web browser and navigate to http://localhost:7420. This opens the official Faktory web dashboard, where you can watch the queues fill up and monitor the tasks arriving in real time.
