# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com),
and this project adheres to [Semantic Versioning](https://semver.org).

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
