"""Minimal Django settings for the example project."""

import os
import secrets
import string
import urllib.parse as urlparse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "".join(
        secrets.choice(string.ascii_letters + string.digits + string.punctuation)
        for _ in range(50)
    ),
)
DEBUG = True

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "faktory_outbox",
    "demo_app",
]

db_url = os.environ.get("DATABASE_URL")

if db_url and db_url.startswith("postgres"):
    url = urlparse.urlparse(db_url)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": url.path[1:],
            "USER": url.username,
            "PASSWORD": url.password,
            "HOST": url.hostname,
            "PORT": url.port or 5432,
            "ATOMIC_REQUESTS": True,
            "OPTIONS": {
                "isolation_level": 1,
            },
        }
    }
else:
    raise ImportError("🚨 DATABASE_URL is missing or not pointing to Postgres!")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TIME_ZONE = "Europe/Brussels"
USE_TZ = True
