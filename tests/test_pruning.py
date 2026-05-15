"""Unit tests for the clear_processed_outbox management command."""

from datetime import timedelta
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.utils import timezone

from faktory_outbox.models import FaktoryOutbox


@pytest.mark.django_db
def test_prune_command_should_remove_processed_records_only() -> None:
    """Verifies that only historical processed records are pruned."""
    now = timezone.now()
    outdated_timestamp = now - timedelta(days=20)

    old_processed = FaktoryOutbox.objects.create(
        task_name="OldProcessed",
        payload={"mode": "custom", "content": {}},
        processed=True,
    )
    FaktoryOutbox.objects.filter(pk=old_processed.pk).update(
        created_at=outdated_timestamp
    )

    FaktoryOutbox.objects.create(
        task_name="RecentProcessed",
        payload={"mode": "custom", "content": {}},
        processed=True,
    )

    old_failed = FaktoryOutbox.objects.create(
        task_name="OldFailed",
        payload={"mode": "custom", "content": {}},
        processed=False,
        is_failed=True,
    )
    FaktoryOutbox.objects.filter(pk=old_failed.pk).update(
        created_at=outdated_timestamp
    )

    output_buffer = StringIO()
    call_command("clear_processed_outbox", days=15, stdout=output_buffer)

    assert "Successfully pruned 1" in output_buffer.getvalue()
    assert FaktoryOutbox.objects.filter(task_name="OldProcessed").count() == 0
    assert (
        FaktoryOutbox.objects.filter(task_name="RecentProcessed").count() == 1
    )
    assert FaktoryOutbox.objects.filter(task_name="OldFailed").count() == 1


@pytest.mark.django_db
def test_prune_command_should_include_failed_when_flagged() -> None:
    """Ensures old quarantined rows are removed when include-failed is set."""
    now = timezone.now()
    outdated_timestamp = now - timedelta(days=20)

    target_failed = FaktoryOutbox.objects.create(
        task_name="TargetFailed",
        payload={"mode": "custom", "content": {}},
        processed=False,
        is_failed=True,
    )
    FaktoryOutbox.objects.filter(pk=target_failed.pk).update(
        created_at=outdated_timestamp
    )

    output_buffer = StringIO()
    call_command(
        "clear_processed_outbox",
        days=15,
        include_failed=True,
        stdout=output_buffer,
    )

    assert "Successfully pruned 1" in output_buffer.getvalue()
    assert FaktoryOutbox.objects.filter(task_name="TargetFailed").count() == 0


@pytest.mark.django_db
def test_prune_command_output_when_no_records_match() -> None:
    """Ensures success message is returned if the outbox table is empty."""
    output_buffer = StringIO()
    call_command("clear_processed_outbox", days=999, stdout=output_buffer)
    assert "Outbox table is already clean" in output_buffer.getvalue()


@pytest.mark.django_db
def test_prune_command_should_handle_and_raise_database_exceptions(
    mocker: Any,
) -> None:
    """Ensures database transaction crashes are logged and re-raised."""
    mock_buffer = StringIO()

    target_path = (
        "faktory_outbox.management.commands."
        "clear_processed_outbox.logger.error"
    )
    mock_logger_error = mocker.patch(target_path)

    now = timezone.now()
    old_job = FaktoryOutbox.objects.create(
        task_name="StaleJob",
        payload={"mode": "custom", "content": {}},
        processed=True,
    )
    FaktoryOutbox.objects.filter(pk=old_job.pk).update(
        created_at=now - timedelta(days=20)
    )

    mocker.patch(
        "django.db.models.sql.compiler.SQLDeleteCompiler.execute_sql",
        side_effect=Exception("Database cluster is read-only"),
    )

    with pytest.raises(Exception, match="Database cluster is read-only"):
        call_command("clear_processed_outbox", days=5, stdout=mock_buffer)

    assert mock_logger_error.called

    assert mock_logger_error.call_args[0][0] == (
        "Failed to execute outbox pruning transaction: %s"
    )
    assert mock_logger_error.call_args[0][1] == (
        "Database cluster is read-only"
    )
