"""Database dialect layer for the Outbox Relay Engine.

Handles parameter styles, status updates queries, and specific SELECT
locking mechanisms across multiple relational database backends.
"""

from typing import Protocol


class DBDialect(Protocol):
    """Protocol defining the contract for database SQL generation."""

    @property
    def param_style(self) -> str:
        """Returns the placeholder style for queries (e.g., '%s', '?')."""
        ...

    @property
    def last_error_update_query(self) -> str:
        """Returns the SQL query to increment attempts and log errors."""
        ...

    @property
    def fail_status_update_query(self) -> str:
        """Returns the SQL query to flag a job as permanently failed."""
        ...

    @property
    def success_update_query(self) -> str:
        """Returns the SQL query to mark a job as processed."""
        ...

    def get_pending_query(self, batch_size: int) -> str:
        """Generates the SQL query to fetch pending locked jobs.

        Args:
            batch_size (int): Maximum number of records to retrieve.

        Returns:
            str: A database-specific SELECT SQL string.
        """
        ...

    def get_bool_value(self, value: bool) -> bool | int:
        """Converts Python boolean to database-specific format.

        Args:
            value (bool): The boolean value to convert.

        Returns:
            bool | int: The equivalent database representation.
        """
        ...


class BaseDialect:
    """Base class providing common dynamic SQL queries based on style."""

    @property
    def param_style(self) -> str:
        """Must be overridden by subclasses to define the placeholder.

        Raises:
            NotImplementedError: If not implemented by a subclass.
        """
        raise NotImplementedError()

    @property
    def last_error_update_query(self) -> str:
        """Returns the SQL query to increment attempts and log errors.

        Returns:
            str: The parameterized UPDATE SQL string.
        """
        current_param_style = self.param_style
        return (
            f"UPDATE faktory_outbox SET delivery_attempts = "
            f"delivery_attempts + 1, last_execution_error = "
            f"{current_param_style} WHERE id = {current_param_style}"  # nosec B608
        )

    @property
    def fail_status_update_query(self) -> str:
        """Returns the SQL query to flag a job as permanently failed.

        Returns:
            str: The parameterized UPDATE SQL string with threshold limit.
        """
        current_param_style = self.param_style
        return (
            f"UPDATE faktory_outbox SET is_failed = {current_param_style} "
            f"WHERE id = {current_param_style} AND delivery_attempts >= "
            f"{current_param_style}"  # nosec B608
        )

    @property
    def success_update_query(self) -> str:
        """Returns the SQL query to mark a job as processed.

        Returns:
            str: The parameterized UPDATE SQL string for success tracking.
        """
        current_param_style = self.param_style
        return (
            f"UPDATE faktory_outbox SET processed = {current_param_style} "  # nosec B608
            f"WHERE id = {current_param_style}"
        )

    def get_bool_value(self, value: bool) -> bool | int:
        """Converts Python boolean to database-specific format.

        Args:
            value (bool): The boolean value to convert.

        Returns:
            bool | int: The unchanged boolean by default.
        """
        return value


class SqliteDialect(BaseDialect):
    """SQLite implementation of the outbox dialect for local testing."""

    @property
    def param_style(self) -> str:
        """Returns the SQLite positional parameter binding placeholder.

        Returns:
            str: The single question mark character.
        """
        return "?"

    def get_pending_query(self, batch_size: int) -> str:
        """Generates the SQL query to fetch pending jobs for SQLite.

        Note:
            SQLite does not natively support 'FOR UPDATE SKIP LOCKED'.
            This implementation is restricted to local development setups.

        Args:
            batch_size (int): Maximum number of records to retrieve.

        Returns:
            str: The basic SQLite SELECT statement matching indexes.
        """
        return (
            "SELECT id, task_name, payload FROM faktory_outbox "
            "WHERE processed = 0 AND is_failed = 0 "
            f"ORDER BY created_at ASC LIMIT {self.param_style}"  # nosec B608
        )

    def get_bool_value(self, value: bool) -> int:
        """Converts Python boolean to SQLite numeric representation.

        Args:
            value (bool): The boolean value to convert.

        Returns:
            int: 1 for True, 0 for False.
        """
        return 1 if value else 0


class PostgresDialect(BaseDialect):
    """PostgreSQL outbox dialect with native SKIP LOCKED support."""

    @property
    def param_style(self) -> str:
        """Returns the PostgreSQL named/positional parameter style.

        Returns:
            str: The percent s format placeholder token string.
        """
        return "%s"

    def get_pending_query(self, batch_size: int) -> str:
        """Generates the SQL query to fetch pending jobs for Postgres.

        Args:
            batch_size (int): Maximum number of records to retrieve.

        Returns:
            str: PostgreSQL query string containing the SKIP LOCKED clause.
        """
        return (
            "SELECT id, task_name, payload FROM faktory_outbox "
            "WHERE processed = FALSE AND is_failed = FALSE "
            f"ORDER BY created_at ASC LIMIT {self.param_style} "  # nosec B608
            "FOR UPDATE SKIP LOCKED"
        )


class MariaDbDialect(BaseDialect):
    """MariaDB (10.6+) and MySQL (8.0+) outbox dialect implementation."""

    @property
    def param_style(self) -> str:
        """Returns the MariaDB parameter placeholder format style token.

        Returns:
            str: The percent s format placeholder token string.
        """
        return "%s"

    def get_pending_query(self, batch_size: int) -> str:
        """Generates the SQL query to fetch pending jobs for MariaDB.

        Args:
            batch_size (int): Maximum number of records to retrieve.

        Returns:
            str: MariaDB query string containing the SKIP LOCKED clause.
        """
        return (
            "SELECT id, task_name, payload FROM faktory_outbox "
            "WHERE processed = FALSE AND is_failed = FALSE "
            f"ORDER BY id ASC LIMIT {self.param_style} "  # nosec B608
            "FOR UPDATE SKIP LOCKED"
        )


class OracleDialect(BaseDialect):
    """Oracle implementation using standard positional bindings."""

    @property
    def param_style(self) -> str:
        """Returns the Oracle positional binding syntax template style.

        Returns:
            str: Colon followed by positional number binding.
        """
        return ":1"

    def get_pending_query(self, batch_size: int) -> str:
        """Generates the SQL query to fetch pending locked jobs for Oracle.

        Args:
            batch_size (int): Maximum number of records to retrieve.

        Returns:
            str: Oracle FETCH FIRST syntax combined with SKIP LOCKED clause.
        """
        return (
            "SELECT id, task_name, payload FROM faktory_outbox "
            "WHERE processed = 0 AND is_failed = 0 "
            f"ORDER BY created_at ASC FETCH FIRST {self.param_style} "  # nosec B608
            "ROWS ONLY FOR UPDATE SKIP LOCKED"
        )

    def get_bool_value(self, value: bool) -> int:
        """Converts Python boolean to Oracle numeric integer format flag.

        Args:
            value (bool): The boolean value to convert.

        Returns:
            int: 1 for True, 0 for False.
        """
        return 1 if value else 0
