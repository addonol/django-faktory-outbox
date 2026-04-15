include .env
export

# Dynamic URL Construction
export DATABASE_URL=postgres://$(DB_USER):$(DB_PASSWORD)@$(DB_HOST):5432/$(DB_NAME)
export FAKTORY_URL=tcp://:$(FAKTORY_PASSWORD)@$(FAKTORY_HOST):7419

.PHONY: clean infra-up infra-down relay-restart logs dev-reset demo relay

# Remove build artifacts and cache files
clean:
	uv run python scripts/cleanup.py

# Start the demonstration infrastructure
infra-up:
	podman-compose up -d

# Stop and remove infrastructure containers
infra-down:
	podman-compose down

# Rebuild and restart the relay worker container
relay-restart:
	podman-compose up -d --build relay

# Follow infrastructure logs
logs:
	podman-compose logs -f

# Perform a full cleanup and restart the relay service
dev-reset: clean infra-down relay-restart

# Run the Django demonstration
demo:
	uv run python examples/django_example/demo.py

# Run the standalone relay engine
relay:
	@echo "🚀 Launching relay engine..."
	uv run python -m faktory_outbox.relay

stress:
	uv run python examples/django_example/stress_test.py
