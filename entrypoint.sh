#!/bin/bash

set -e

export PYTHONPATH="${PYTHONPATH}:/app"

echo "🚀 Bootstrapping container runtime environment layer..."

exec "$@"
