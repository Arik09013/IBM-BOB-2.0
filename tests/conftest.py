"""
Shared test fixtures and configuration for TestPilot AI test suite.

All fixtures use only synthetic/in-memory data — no real API calls,
no real repositories, and no fabricated AI outputs.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal temporary directory that looks like a repository."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Fake Repo\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def default_settings():
    """Return a Settings instance with all defaults (no .env required)."""
    import os

    # Unset any API key that might be set in CI/dev environment
    # so tests do not depend on external credentials.
    env_backup = os.environ.pop("OPENAI_API_KEY", None)
    try:
        from testpilot.config import Settings
        return Settings()
    finally:
        if env_backup is not None:
            os.environ["OPENAI_API_KEY"] = env_backup
