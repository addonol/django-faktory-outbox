"""Cleanup script for the Faktory Outbox project.

Removes build artifacts, cache files, and temporary databases.
"""

import shutil
from pathlib import Path


def cleanup():
    """Removes temporary files and build artifacts."""
    root = Path(__file__).parent.parent
    patterns = [
        "**/__pycache__",
        "**/*.pyc",
        "**/*.pyo",
        "**/*.pyd",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        "*.egg-info",
        "examples/django_example/db.sqlite3",
        "examples/example_outbox.sqlite3",
    ]

    for pattern in patterns:
        for path in root.glob(pattern):
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                print(f"Removed: {path}")
            except Exception as e:
                print(f"Error removing {path}: {e}")


if __name__ == "__main__":
    cleanup()
