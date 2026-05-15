"""Application configuration for the Faktory Outbox library."""

from django.apps import AppConfig


class FaktoryOutboxConfig(AppConfig):
    """Default configuration for the Faktory Outbox application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "faktory_outbox"
    verbose_name = "Faktory Outbox"

    def ready(self) -> None:
        """Executed when Django finishes application registry loading."""
        pass
