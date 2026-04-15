"""Application configuration for the demo app.

This module defines the Django AppConfig for the demo_app used in examples.
"""

from django.apps import AppConfig


class DemoAppConfig(AppConfig):
    """Configuration class for the demo demonstration application.

    Attributes:
        default_auto_field (str): The default primary key field type.
        name (str): The formal name of the demo application.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "demo_app"
