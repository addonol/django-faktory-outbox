include .env.example
export

# Dynamic URL Construction
export DATABASE_URL=postgres://$(DB_USER):$(DB_PASSWORD)@$(DB_HOST):5432/$(DB_NAME)
export FAKTORY_URL=tcp://:$(FAKTORY_PASSWORD)@$(FAKTORY_HOST):7419

.PHONY: help clean infra-up infra-down relay-restart logs dev-reset demo relay stress bulk-demo make-migrations run-example

# ==============================================================================
# HELP MENU (DEFAULT TARGET)
# ==============================================================================

help:
	@echo "========================================================================"
	@echo "                    DJANGO FAKTORY OUTBOX - CLI TOOLBOARD               "
	@echo "========================================================================"
	@echo "Usage: make [target]"
	@echo ""
	@echo "Development & Local Testing:"
	@echo "  make make-migrations  Generate Django outbox package migrations isolated"
	@echo "  make run-example      Execute the local memory-safe integration test"
	@echo "  make clean            Remove build artifacts, caches, and pyc files"
	@echo ""
	@echo "Infrastructure Management (Podman):"
	@echo "  make infra-up         Start the 4-container demonstration infrastructure"
	@echo "  make infra-down       Stop and remove infrastructure containers & networks"
	@echo "  make relay-restart    Rebuild the relay image and restart its container"
	@echo "  make logs             Follow infrastructure containers logs stream"
	@echo "  make dev-reset        Full reset (Clean cache, Stop stack, Rebuild & Start)"
	@echo ""
	@echo "Container Stream Monitoring:"
	@echo "  make demo             Follow the live Django invoice generation loop logs"
	@echo "  make relay            Follow the active outbox relay sync daemon logs"
	@echo "========================================================================"


# ==============================================================================
# DEVELOPMENT & MIGRATIONS TARGETS
# ==============================================================================

make-migrations:
	@echo "Generating isolated Django schema migrations..."
	uv run python utils/make_migrations.py

run-example:
	@echo "Executing local programmatic integration test sequence..."
	uv run python examples/run_example.py

clean:
	@echo "Cleaning up compilation cache artifacts..."
	uv run python utils/clean_cached_files.py

# ==============================================================================
# INFRASTRUCTURE MANAGEMENT TARGETS
# ==============================================================================

infra-up:
	podman-compose up -d

infra-down:
	podman-compose down

relay-restart:
	@echo "Rebuilding the local relay image..."
	podman build -t localhost/faktory-outbox-relay:latest .
	@echo "Restarting the relay service container..."
	podman-compose up -d --build relay

logs:
	podman-compose logs -f

dev-reset: clean infra-down
	@echo "Performing explicit local image build for Podman compliance..."
	podman build -t localhost/faktory-outbox-relay:latest .
	@echo "Launching full infrastructure stack..."
	podman-compose up -d

# ==============================================================================
# EXECUTION & BENCHMARKING TARGETS
# ==============================================================================

demo:
	uv run python examples/django_example/demo.py

relay:
	@echo "Launching outbox relay synchronization daemon..."
	uv run python -m faktory_outbox.relay
