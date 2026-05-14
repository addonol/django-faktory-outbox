"""Unit tests for the Faktory Outbox service layer.

Validates atomic job registration via Django ORM and raw SQL modes, ensuring
data integrity and correct JSON serialization of payloads.
"""

import pytest
from django.contrib.auth.models import User
from django.db import transaction

from faktory_outbox.models import FaktoryOutbox
from faktory_outbox.service import OutboxService, OutboxTransactionError


@pytest.mark.django_db
class TestOutboxService:
    """Business logic tests for the OutboxService and FaktoryOutbox model."""

    @pytest.mark.django_db(transaction=True)
    def test_should_raise_exception_outside_transaction(self) -> None:
        """Ensures push_atomic blocks execution if no transaction is active."""
        with pytest.raises(OutboxTransactionError) as exception_info:
            OutboxService.push_atomic(
                task_name="unsecured_task", custom_payload={"status": "forbidden"}
            )

        assert "must be executed within an active transaction" in str(
            exception_info.value
        )
        assert FaktoryOutbox.objects.count() == 0

    def test_should_persist_custom_dict_payload(self) -> None:
        """Verifies that a manual dictionary is stored correctly in 'custom' mode."""
        data = {"event": "signup", "user_id": 123}

        with transaction.atomic():
            record = OutboxService.push_atomic(
                task_name="notify_user", custom_payload=data
            )

        assert FaktoryOutbox.objects.count() == 1
        assert record.task_name == "notify_user"
        assert record.payload["mode"] == "custom"
        assert record.payload["content"] == data

    def test_should_serialize_queryset_to_json(self) -> None:
        """Ensures Django QuerySets are extracted and serialized into 'orm' mode."""
        User.objects.create(username="test_ref_user")
        queryset = User.objects.all()

        with transaction.atomic():
            record = OutboxService.push_atomic(task_name="sync_users", queryset=queryset)

        assert record.payload["mode"] == "orm"
        assert record.payload["model_identifier"] == "auth.user"
        assert len(record.payload["content"]) == 1
        assert record.payload["content"][0]["username"] == "test_ref_user"

    def test_should_store_raw_sql_queries(self) -> None:
        """Verifies that raw SQL and parameters are correctly persisted."""
        sql = "SELECT * FROM auth_user WHERE is_active = %s"
        params = [True]

        with transaction.atomic():
            record = OutboxService.push_atomic(
                task_name="sql_sync", raw_sql=sql, sql_parameters=params
            )

        assert record.payload["mode"] == "sql"
        assert record.payload["query_string"] == sql
        assert record.payload["parameters"] == params

    def test_model_should_return_human_readable_status_processed(self) -> None:
        """Ensures __str__ returns the correct label for processed records."""
        job = FaktoryOutbox(task_name="batch_job", processed=True)
        assert str(job) == "batch_job - Processed"

    def test_model_should_return_human_readable_status_failed(self) -> None:
        """Ensures __str__ returns the correct label for quarantine failures."""
        job = FaktoryOutbox(task_name="batch_job", processed=False, is_failed=True)
        assert str(job) == "batch_job - Failed (DLQ)"

    def test_model_should_return_human_readable_status_pending(self) -> None:
        """Ensures __str__ returns the correct label for standard pending queues."""
        job = FaktoryOutbox(
            task_name="batch_job", processed=False, is_failed=False, delivery_attempts=3
        )
        assert str(job) == "batch_job - Pending (Attempt 3)"
