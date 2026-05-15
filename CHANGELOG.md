# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com),
and this project adheres to [Semantic Versioning](https://semver.org).

## [0.2.0] - 2026-05-15


### Added
- **MariaDB & MySQL Support:** Added a dedicated dialect class handling their
  native concurrent locking syntax (`FOR UPDATE SKIP LOCKED`).
- **Native Drivers:** Integrated the official compiled `mysqlclient` binary
  driver inside the Containerfile to ensure stable production execution paths.
- **Dependency Extras:** Exposed standard installation options for `mariadb`
  and `mysql` packages within `pyproject.toml`.
- **Dynamic Demonstration:** Upgraded `demo.py` to automatically detect the database
  flavor from the `DATABASE_URL` with an active TCP port handshake check.
- **Continuous Traffic Loop:** Enveloped the demo script in a continuous loop,
  staging unique mock invoices every 3 seconds to act as a proper producer.
- **Makefile Automation:** Introduced target CLI shortcuts (`make infra-up-postgres`,
  `make infra-up-mariadb`, `make infra-up-mysql`) built around Podman capabilities.

### Changed
- **SOLID Refactoring:** Split the oversized monolithic `relay.py` script into
  a clean package directory layout (`dialects.py`, `engine.py`, `main.py`, `services.py`).
- **Lazy Initialization:** Leveraged a lazy loading proxy pattern inside
  `__init__.py` to bypass early Django app registry startup circular deadlocks.
- **Strict Linting Rules:** Configured Ruff and reformatted the codebase to
  strictly enforce a maximum line length of 79 characters across the project.
- **Makefile Cleanup:** Reorganized the `.PHONY` array directive block to reference
  only valid and active orchestration commands.

### Fixed
- **Placeholder Syntax Bugs:** Fixed query execution crashes on SQLite and Oracle
  by abstracting parameter formatting tokens into the dialect layout.
- **Database Interlocks (Deadlocks):** Swapped query sorting logic to order by
  primary key `id` instead of `created_at` to prevent InnoDB table-wide Gap Locks.
- **Hanging Transaction Locks:** Relocated the connection `commit()` to trigger
  immediately after fetching rows, dropping database locks before talking to Faktory.
- **Postgres Payload Mapping:** Added seamless handling for situations where the
  PostgreSQL driver natively returns a pre-parsed dictionary instead of raw text.
- **Log Formatting Crash:** Fixed a critical python string formatting crash when
  persisting daemon transaction error traces back into the database.
- **Unit Testing Coverage:** Resolved context mock leaks and hidden connection
  pools, securing a validated 100% codebase coverage threshold.



## [0.1.0] - 2026-05-14

### Added
- **Core Architecture:** Implemented the dual-nature Transactional Outbox pattern engine for Django and Faktory.
- **Ingress API:** Added `OutboxService.push_atomic` to securely stage background jobs within active SQL boundaries.
- **Egress Daemon:** Built the standalone `OutboxRelay` command-line synchronization daemon supporting Postgres, SQLite, and Oracle database dialects.
- **Maintenance:** Implemented the `clear_processed_outbox` Django administrative command for automated historical record pruning (Issue #5).
- **Orchestration:** Added a generic, multi-container development topology using Podman Compose (`message_broker`, `database`, `django_app`, `relay`).
- **Security:** Fully isolated the container compilation layers execution context under a non-privileged `appuser`.
- **Testing:** Established a comprehensive test suite (`test_services.py`, `test_relay_cli.py`, `test_relay_units.py`, `test_pruning.py`) enforcing 100% code coverage.
- **CI/CD:** Configured a native GitHub Actions validation quality pipeline (`.github/workflows/ci.yml`).

### Changed
- Upgraded the minimum software environment framework requirements to **Django >= 5.2** and **Python >= 3.10** to adhere to modern community support cycles.
- Packaged distribution builds under the unified Astral `uv` package manager layout using the Hatchling compiler backend.
