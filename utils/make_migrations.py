"""Standalone script to generate Django migrations without a project."""

import django
from django.conf import settings

settings.configure(
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "faktory_outbox",
    ],
    DATABASES={
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    },
)

django.setup()


if __name__ == "__main__":
    from django.core.management import call_command

    call_command("makemigrations", "faktory_outbox")
