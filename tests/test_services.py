"""Unit tests for the Faktory Outbox service layer.

Validates atomic job registration via Django ORM and raw SQL modes, ensuring
data integrity and correct JSON serialization of payloads.
"""

import pytest
from django.contrib.auth.models import User

from faktory_outbox.models import FaktoryOutbox
from faktory_outbox.service import OutboxService


@pytest.mark.django_db
class TestOutboxService:
    """Business logic tests for the OutboxService and FaktoryOutbox model."""

    def test_should_persist_custom_dict_payload(self) -> None:
        """Verifies that a manual dictionary is stored correctly in 'custom' mode."""
        data = {"event": "signup", "user_id": 123}

        record = OutboxService.push_atomic(task_name="notify_user", data=data)

        assert FaktoryOutbox.objects.count() == 1
        assert record.task_name == "notify_user"
        assert record.payload["mode"] == "custom"
        assert record.payload["content"] == data

    def test_should_serialize_queryset_to_json(self) -> None:
        """Ensures Django QuerySets are extracted and serialized into 'orm' mode."""
        User.objects.create(username="test_ref_user")
        queryset = User.objects.all()

        record = OutboxService.push_atomic(task_name="sync_users", queryset=queryset)

        assert record.payload["mode"] == "orm"
        assert record.payload["model"] == "auth.user"
        # content is a list of dictionaries after JSON round-trip
        assert len(record.payload["content"]) == 1
        assert record.payload["content"][0]["username"] == "test_ref_user"

    def test_should_store_raw_sql_queries(self) -> None:
        """Verifies that raw SQL and parameters are correctly persisted."""
        sql = "SELECT * FROM auth_user WHERE is_active = %s"
        params = [True]

        record = OutboxService.push_atomic(
            task_name="sql_sync", raw_sql=sql, params=params
        )

        assert record.payload["mode"] == "sql"
        assert record.payload["query"] == sql
        assert record.payload["params"] == params

    def test_model_should_return_human_readable_status(self) -> None:
        """Ensures the model's string representation reflects its processing state."""
        job = FaktoryOutbox(task_name="batch_job", processed=False)
        assert str(job) == "batch_job (Pending)"

        job.processed = True
        assert str(job) == "batch_job (Processed)"
