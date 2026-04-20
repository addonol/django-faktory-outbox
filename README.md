# Django Faktory Outbox

A high-performance, transactional outbox implementation for Django and Faktory. This module ensures **Zero-Risk** background job processing: jobs are only delivered if your database transaction succeeds.

## Features

- **Transactional Integrity**: Jobs are staged in your database and committed atomically with your business data.
- **Resilient Relay**: A standalone engine pushes jobs to Faktory with exponential backoff and automatic retries.
- **High Concurrency**: Built-in support for `SKIP LOCKED` (PostgreSQL & Oracle) allowing multiple relay instances to run in parallel.
- **Batch Processing**: Configurable chunk sizes for high-throughput environments.
- **Developer Friendly**: Styled console output with emojis and clear status banners for easy monitoring.

---

## Technical Deep Dive: Batch Processing & Performance

The Relay engine is designed for high-throughput environments. Understanding how it handles large volumes of jobs is key to optimizing your pipeline.

### 1. Database Chunking (The Fetch Phase)
To maintain a low memory footprint and prevent database contention, the Relay does not load the entire outbox into memory. Instead, it operates in **chunks** defined by the `RELAY_BATCH_SIZE` environment variable.
*   **Query efficiency**: It uses `FOR UPDATE SKIP LOCKED` (on PostgreSQL and Oracle) to allow multiple Relay instances to work on the same table simultaneously without overlapping.
*   **Atomic Updates**: Each chunk is processed within its own database transaction. If the push to Faktory fails, the database remains unchanged.

### 2. Connection Lifecycle Management
You may notice "Connecting" and "Disconnected" logs for each processed batch. This is an intentional design choice for **reliability**:
*   The Relay opens a single TCP socket per batch.
*   By closing the connection after each batch, we ensure that we don't hold "zombie" connections on the Faktory server during idle periods.
*   This approach significantly reduces the TCP handshake overhead compared to a 1-by-1 connection strategy.

### 3. Sequential Pushing vs. Network Pipelining
While the jobs are fetched in bulk from the database, the current Python Faktory SDK (by `cdrx`) sends jobs to the server sequentially over the open socket.
*   **Why not 1-by-1?** By keeping the socket open for the entire chunk (e.g., 1,000 jobs), we eliminate the network latency of re-establishing a connection for every single job.
*   **Performance**: In local benchmarks, this strategy allows processing thousands of jobs per second, as the overhead shifts from network negotiation to raw data transmission.

### 4. The `PUSHB` (Bulk Push) Limitation
The Faktory protocol supports a `PUSHB` command for true atomic bulk delivery of multiple jobs in a single command. However, **this is not yet supported by the standard Python Faktory worker library**.
*   **Current state**: We simulate bulk behavior by reusing the same connection for all jobs in a batch.
*   **Future-proofing**: The Relay architecture is decoupled; once the underlying SDK supports `PUSHB`, the `_sync_jobs_to_faktory` method can be updated to use true bulk pushing without changing the outbox logic.

---

## Environment Variables


| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | - | DB Connection string (Postgres/Oracle/SQLite) |
| `FAKTORY_URL` | `tcp://localhost:7419` | Faktory server connection string |
| `RELAY_BATCH_SIZE` | `50` | Number of jobs per database transaction |
| `RELAY_DEBUG` | `False` | Enable verbose heartbeat and connection logs |
| `STRESS_COUNT` | `100` | Number of jobs to inject during stress tests |



## Quick Start

Ensure you have your `.env` file configured before running the commands.

```bash
# Spin up the PostgreSQL and Faktory containers
make infra-up

# Standard Demo: Validates atomic transactions and rollbacks with stylized logs.
make demo

# Stress Test: Injects a massive batch of jobs (controlled by STRESS_COUNT) to test throughput.
make stress

# Bulk Push PoC: Demonstrates the high-performance PUSHB command from my custom Faktory fork.
make bulk-demo

# Run the standalone relay to move jobs from the database to Fakto
make relay

# Follow container logs
make logs

# Full reset (Clean, Down, and Rebuild)
make dev-reset

# Remove build artifacts and cache
make clean
```


## Integration

### 1. Atomic Job Registration (Django)
Use `OutboxService` within a Django atomic transaction to ensure that background jobs are only registered if your database changes are successfully committed.

```python
from django.db import transaction
from faktory_outbox.service import OutboxService

with transaction.atomic():
    # Your business logic (e.g., creating an order)
    order = Order.objects.create(amount=100)

    # Register the associated background job
    OutboxService.push_atomic(
        task_name="ProcessPayment",
        data={"order_id": order.id}
    )
    # If the code crashes here, both the order and the job are rolled back.
```

### 2. Flexible Payload Modes
The service supports three extraction modes to fit any architectural requirement:

```python
from faktory_outbox.service import OutboxService
from django.contrib.auth.models import User

# --- 1. Custom Data Mode ---
# Best for simple, manual payloads.
OutboxService.push_atomic(
    task_name="SendNotification",
    data={"user_id": 42, "message": "Hello World"}
)

# --- 2. Django QuerySet Mode ---
# Automatically extracts and serializes records into a list of dictionaries.
# Handles Django-specific types like Datetime and UUID.
active_users = User.objects.filter(is_active=True)
OutboxService.push_atomic(
    task_name="SyncUsers",
    queryset=active_users
)

# --- 3. Raw SQL Mode ---
# Best for high-performance extraction of complex data.
# Stores the query and params to be executed later by the worker.
raw_query = "SELECT id, email FROM auth_user WHERE date_joined > %s"
query_params = ["2026-01-01"]
OutboxService.push_atomic(
    task_name="ExportAuditLog",
    raw_sql=raw_query,
    params=query_params
)
```

### 3. Reliable Synchronization via Relay
The Relay is a standalone engine (CLI) that moves jobs from your database to the Faktory server. It is designed for production resilience and natively handles:

*   **High Concurrency**: Uses `FOR UPDATE SKIP LOCKED` (Postgres/Oracle) to allow multiple relay instances to run in parallel without job duplication or locking issues.
*   **Resilience**: Features an automatic exponential backoff strategy if either the Faktory server or the database becomes unavailable.
*   **Security**: Automatically masks connection passwords in system logs to prevent accidental credential leakage.

To start the relay, configure your environment variables and run the module:

```bash
# Configuration
export DATABASE_URL="postgres://user:pass@localhost:5432/db"
export FAKTORY_URL="tcp://:password@localhost:7419"

# Execution
python -m faktory_outbox.relay
