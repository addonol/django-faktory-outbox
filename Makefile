include .env.example
export

# Dynamic URL Construction
export FAKTORY_URL=tcp://:$(FAKTORY_PASSWORD)@$(FAKTORY_HOST):7419
COMPOSE_FILE = examples/docker-compose.yml

.PHONY: help clean \
        infra-up-postgres infra-up-mariadb infra-up-mysql \
        infra-down relay-restart logs dev-reset \
        demo relay make-migrations run-example

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
	@echo "  make make-migrations   Generate Django outbox migrations isolated"
	@echo "  make run-example       Execute the local programmatic integration test"
	@echo "  make clean             Remove build artifacts, caches, and pyc files"
	@echo ""
	@echo "Infrastructure Management (Podman/Docker Profiles):"
	@echo "  make infra-up-postgres Launch stack with PostgreSQL active backend"
	@echo "  make infra-up-mariadb  Launch stack with MariaDB active backend"
	@echo "  make infra-up-mysql    Launch stack with MySQL active backend"
	@echo "  make infra-down        Stop and remove all containers & networks"
	@echo "  make relay-restart     Rebuild the relay image and restart service"
	@echo "  make logs              Follow infrastructure containers logs stream"
	@echo "  make dev-reset         Full reset (Clean cache, Stop, Rebuild & Start)"
	@echo ""
	@echo "Container Stream Monitoring:"
	@echo "  make demo              Follow the live Django app container logs"
	@echo "  make relay             Follow the active outbox relay daemon logs"
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

infra-up-postgres:
	@echo "Launching infrastructure under PostgreSQL configuration..."
	export TARGET_DATABASE_URL="postgres://user:demo_password_123@database_postgres:5432/outbox_db" && \
	podman-compose -f $(COMPOSE_FILE) up -d \
	message_broker database_postgres django_app relay

infra-up-mariadb:
	@echo "Launching infrastructure under MariaDB configuration..."
	export TARGET_DATABASE_URL="mariadb://user:demo_password_123@database_mariadb:3306/outbox_db" && \
	podman-compose -f $(COMPOSE_FILE) up -d \
	message_broker database_mariadb django_app relay

infra-up-mysql:
	@echo "Launching infrastructure under MySQL configuration..."
	export TARGET_DATABASE_URL="mysql://user:demo_password_123@database_mysql:3306/outbox_db" && \
	podman-compose -f $(COMPOSE_FILE) up -d \
	message_broker database_mysql django_app relay

infra-down:
	@echo "Destroying full infrastructure environment stack..."
	podman-compose -f $(COMPOSE_FILE) down

relay-restart:
	@echo "Rebuilding the local relay engine target container image..."
	podman build -t localhost/faktory-outbox-relay:latest .
	@echo "Restarting the relay service container..."
	podman-compose -f $(COMPOSE_FILE) up -d --build relay

logs:
	podman-compose -f $(COMPOSE_FILE) logs -f

dev-reset: clean
	@echo "Stopping all existing stacks and clearing volumes..."
	podman-compose -f $(COMPOSE_FILE) down --volumes
	@echo "Performing explicit local image build for Podman compliance..."
	podman build --no-cache -t localhost/faktory-outbox-relay:latest .
	@echo "Launching default infrastructure stack (PostgreSQL)..."
	export TARGET_DATABASE_URL="postgres://user:demo_password_123@database_postgres:5432/outbox_db" && \
	podman-compose -f $(COMPOSE_FILE) up -d \
	message_broker database_postgres django_app relay


# ==============================================================================
# EXECUTION & MONITORING TARGETS
# ==============================================================================

demo:
	podman logs -f django_application

relay:
	podman logs -f relay_worker
