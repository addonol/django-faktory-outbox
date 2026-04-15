#!/bin/bash

set -e

export PYTHONPATH=$PYTHONPATH:/app

echo "Waiting for database...".

echo "Running migrations..."

python -u examples/django_example/demo.py --only-migrate

echo "Starting Relay engine..."
exec "$@"
