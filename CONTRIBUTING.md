# Contributing to Django Faktory Outbox

This project follows SOLID principles, PEP 8 standards, and Google-style documentation.

## Development Setup

The project uses [uv](https://docs.astral.sh/uv/) for dependency management.

1. Clone the repository:
   ```bash
   git clone https://github.com/addonol/django-faktory-outbox.git
   cd django-faktory-outbox

    ```

2.  **Create a virtual environment and install dependencies**:
    ```bash
    # Install with all database drivers and dev tools
    uv venv
    uv pip install -e ".[postgres,oracle,dev]"
    ```

## Coding Standards

To maintain high code quality, we enforce the following:

-   **Linting & Formatting**: We use **Ruff**. Please run it before committing.
    ```bash
    uv run ruff check . --fix
    uv run ruff format .
    ```
-   **Docstrings**: Follow the **Google Python Style Guide**. Every module, class, and method must be documented.
-   **Type Hints**: Use type annotations for all function signatures.

## Testing

### Running Library Tests
We use a lightweight SQLite-based test suite to verify the Outbox logic.
```bash
uv run python -m unittest tests/test_relay.py
```

## Integration Demo
Verify the integration within a minimal Django environment:
```bash
uv run python examples/django_example/demo.py
```

## Pull Request Process

    1. Create a dedicated branch for your changes.
    2. Ensure the test suite passes and Ruff validation is clean.
    3. Update documentation or examples if functional changes are introduced.
    4. Submit the PR with a concise description of the modifications.
