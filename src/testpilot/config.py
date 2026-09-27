"""
Configuration system for TestPilot AI.

Settings are loaded from (in priority order):
1. Environment variables  (highest)
2. .env file              (via python-dotenv)
3. Declared defaults      (lowest)

Secrets (API keys) must be provided via environment variables only.
They are never stored in config.yaml or committed to the repository.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    """Supported LLM backend providers."""

    OPENAI = "openai"
    OLLAMA = "ollama"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Settings(BaseSettings):
    """
    Central, typed configuration object for TestPilot AI.

    All fields can be overridden via environment variables prefixed with
    ``TESTPILOT_`` (e.g. ``TESTPILOT_LOG_LEVEL=DEBUG``).

    Secrets (OPENAI_API_KEY etc.) are read from their own unprefixed
    environment variables to stay compatible with standard tooling.
    """

    model_config = SettingsConfigDict(
        env_prefix="TESTPILOT_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    app_name: str = "TestPilot AI"
    version: str = "0.1.0"

    # ------------------------------------------------------------------
    # LLM provider
    # ------------------------------------------------------------------
    llm_provider: LLMProvider = LLMProvider.OLLAMA
    """Which LLM backend to use.  Default: ollama (free, local)."""

    llm_model: str = "codellama"
    """Model name passed to the provider."""

    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    """Sampling temperature for generation tasks."""

    llm_max_tokens: int = Field(default=4096, ge=64)
    """Maximum completion tokens per LLM call."""

    llm_request_timeout: float = Field(default=120.0, ge=5.0)
    """Per-request timeout in seconds."""

    # ------------------------------------------------------------------
    # Secrets — read directly from env, NOT prefixed with TESTPILOT_
    # ------------------------------------------------------------------
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    """OpenAI API key.  Required only when llm_provider=openai."""

    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    """OpenAI-compatible base URL.  Override for Azure or local proxies."""

    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    """Base URL for a locally running Ollama instance."""

    ollama_model: str = Field(default="codellama", alias="OLLAMA_MODEL")
    """Ollama model name (overrides llm_model when provider=ollama)."""

    # ------------------------------------------------------------------
    # Pipeline control
    # ------------------------------------------------------------------
    max_repair_iterations: int = Field(default=2, ge=1, le=10)
    """Maximum repair→re-validation loop iterations before forced exit."""

    test_execution_timeout: float = Field(default=30.0, ge=5.0)
    """Per-test subprocess timeout in seconds."""

    no_improvement_exit: bool = True
    """Exit the repair loop early if failure count does not decrease."""

    # ------------------------------------------------------------------
    # Output & storage
    # ------------------------------------------------------------------
    output_dir: Path = Field(default=Path("./output"))
    """Root directory for all run artefacts (logs, reports, patches)."""

    log_level: LogLevel = LogLevel.INFO

    # ------------------------------------------------------------------
    # Research / evaluation
    # ------------------------------------------------------------------
    approach: Literal["single", "multi"] = "multi"
    """
    Experiment condition.
    - 'single': one LLM call per target, no iterative repair loop.
    - 'multi':  full multi-agent pipeline (default).
    """

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    @field_validator("output_dir", mode="before")
    @classmethod
    def _resolve_output_dir(cls, v: str | Path) -> Path:
        return Path(v)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @property
    def effective_llm_model(self) -> str:
        """Return the model name appropriate for the active provider."""
        if self.llm_provider == LLMProvider.OLLAMA:
            return self.ollama_model or self.llm_model
        return self.llm_model

    def ensure_output_dir(self) -> Path:
        """Create the output directory if it does not yet exist."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir

    def is_openai_configured(self) -> bool:
        """Return True if an OpenAI API key is available."""
        return bool(self.openai_api_key)


def load_settings() -> Settings:
    """
    Load and return the global Settings instance.

    Reads from the .env file (if present) and environment variables.
    Call this once at startup and pass the object through the application.
    """
    from dotenv import load_dotenv

    load_dotenv(override=False)  # .env values do NOT override already-set env vars
    return Settings()
