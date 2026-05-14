"""Global configuration for the Faktory Outbox test suite.

Initializes the Django environment and defines pure pytest fixtures
using the mocker plugin to avoid direct unittest imports.
"""

import os
import secrets
from typing import Any

import django
import pytest
from django.conf import settings


def pytest_configure() -> None:
    """Configures a headless Django environment dynamically.

    Sets up in-memory SQLite and essential contrib apps with a
    randomly generated SECRET_KEY.
    """
    if "DATABASE_URL" in os.environ:
        del os.environ["DATABASE_URL"]

    if not settings.configured:
        settings.configure(
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": ":memory:",
                }
            },
            INSTALLED_APPS=[
                "django.contrib.contenttypes",
                "django.contrib.auth",
                "faktory_outbox",
            ],
            SECRET_KEY=secrets.token_urlsafe(32),
            USE_TZ=True,
        )
    django.setup()


@pytest.fixture
def mock_db_conn(mocker: Any) -> Any:
    """Provides a mocked database connection using mocker.

    Uses mocker.Mock() to stay within the pytest ecosystem.
    """
    conn = mocker.Mock(spec=["cursor", "commit", "rollback", "close"])
    cursor = conn.cursor.return_value
    cursor.__enter__.return_value = cursor
    return conn


@pytest.fixture
def mock_faktory(mocker: Any) -> Any:
    """Provides a mocked Faktory client instance for network isolation."""
    return mocker.MagicMock()
