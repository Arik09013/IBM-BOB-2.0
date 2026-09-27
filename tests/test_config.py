"""
Tests for the configuration system (testpilot.config).

Verifies:
- Settings can be instantiated with defaults.
- Environment variable overrides work.
- Field validators behave correctly.
- Helper methods return correct values.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from testpilot.config import LLMProvider, LogLevel, Settings


class TestSettingsDefaults:
    """Settings constructed with no environment variables."""

    def test_instantiates(self):
        """Settings must be constructable with no arguments."""
        s = Settings()
        assert s is not None

    def test_default_provider(self):
        s = Settings()
        assert s.llm_provider == LLMProvider.OLLAMA

    def test_default_model(self):
        s = Settings()
        # Default Ollama model is codellama
        assert s.effective_llm_model == "codellama"

    def test_default_max_iterations(self):
        s = Settings()
        assert s.max_repair_iterations == 2

    def test_default_log_level(self):
        s = Settings()
        assert s.log_level == LogLevel.INFO

    def test_default_output_dir_is_path(self):
        s = Settings()
        assert isinstance(s.output_dir, Path)

    def test_no_openai_key_by_default(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        s = Settings()
        assert not s.is_openai_configured()

    def test_approach_default(self):
        s = Settings()
        assert s.approach == "multi"


class TestSettingsEnvOverrides:
    """Settings overridden via environment variables."""

    def test_log_level_env_override(self, monkeypatch):
        monkeypatch.setenv("TESTPILOT_LOG_LEVEL", "DEBUG")
        s = Settings()
        assert s.log_level == LogLevel.DEBUG

    def test_max_iterations_env_override(self, monkeypatch):
        monkeypatch.setenv("TESTPILOT_MAX_REPAIR_ITERATIONS", "5")
        s = Settings()
        assert s.max_repair_iterations == 5

    def test_provider_env_override(self, monkeypatch):
        monkeypatch.setenv("TESTPILOT_LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        s = Settings()
        assert s.llm_provider == LLMProvider.OPENAI
        assert s.is_openai_configured()

    def test_approach_env_override(self, monkeypatch):
        monkeypatch.setenv("TESTPILOT_APPROACH", "single")
        s = Settings()
        assert s.approach == "single"


class TestSettingsValidation:
    """Pydantic field validators."""

    def test_output_dir_is_always_path(self, monkeypatch):
        monkeypatch.setenv("TESTPILOT_OUTPUT_DIR", "/tmp/testpilot_out")
        s = Settings()
        assert isinstance(s.output_dir, Path)

    def test_temperature_bounds(self):
        with pytest.raises(Exception):
            Settings(llm_temperature=-0.1)
        with pytest.raises(Exception):
            Settings(llm_temperature=2.1)

    def test_max_tokens_minimum(self):
        with pytest.raises(Exception):
            Settings(llm_max_tokens=10)


class TestEnsureOutputDir:
    def test_creates_directory(self, tmp_path):
        s = Settings(output_dir=tmp_path / "new_out_dir")
        result = s.ensure_output_dir()
        assert result.exists()
        assert result.is_dir()
