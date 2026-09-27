"""
LLM client abstraction for TestPilot AI.

Provides a clean provider-agnostic interface so agents never depend on a
specific API.  Concrete provider implementations are added in later phases
without changing agent code.

Registered providers (Phase 1B):
  - stub    — no-op client for unit tests (no network)
  - openai  — OpenAI Chat Completions API (requires OPENAI_API_KEY)
  - ollama  — Local Ollama instance (no key required)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class LLMMessage:
    """A single message in a chat completion request."""

    role: Literal["system", "user", "assistant"]
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class LLMResponse:
    """
    The result of a single LLM completion call.

    Attributes
    ----------
    content:
        The model's text response.
    model:
        The model name reported by the provider.
    prompt_tokens:
        Number of tokens in the input.
    completion_tokens:
        Number of tokens in the output.
    total_tokens:
        Sum of prompt + completion tokens.
    """

    content: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    raw: dict = field(default_factory=dict)
    """Raw provider response for debugging (never logged to session files)."""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class BaseLLMClient(ABC):
    """
    Abstract interface that every LLM provider must implement.

    Agents call only this interface.  Provider details (HTTP, auth, retry
    logic) live entirely inside concrete subclasses.
    """

    @abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """
        Send a list of messages to the LLM and return a single response.

        Parameters
        ----------
        messages:
            Ordered list of messages forming the conversation context.
        temperature:
            Sampling temperature (0.0 = deterministic, 2.0 = very random).
        max_tokens:
            Maximum number of tokens to generate.

        Returns
        -------
        LLMResponse
            The model's reply with token usage information.
        """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name (e.g. 'openai', 'ollama')."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The model identifier being used (e.g. 'gpt-4o', 'codellama')."""

    def count_tokens_approx(self, text: str) -> int:
        """
        Return a rough token count estimate (1 token ≈ 4 characters).

        Concrete providers may override with a more accurate implementation
        (e.g. tiktoken for OpenAI).
        """
        return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Stub implementations (for testing and Phase 0 validation)
# ---------------------------------------------------------------------------

class _StubLLMClient(BaseLLMClient):
    """
    A no-op LLM client used for unit tests and pipeline smoke-tests.

    Returns a clearly-labelled stub message so it is obvious when a real
    model has NOT been called.  Never makes external network requests.
    """

    @property
    def provider_name(self) -> str:
        return "stub"

    @property
    def model_name(self) -> str:
        return "stub-model"

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        return LLMResponse(
            content=(
                "[STUB] This is a placeholder response from the StubLLMClient.\n"
                "No real LLM was called.  Implement OpenAIClient or OllamaClient "
                "in Phase 1 to get actual model output."
            ),
            model=self.model_name,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class LLMClientFactory:
    """
    Creates and returns the appropriate BaseLLMClient for a given provider name.

    Registered providers: stub, openai, ollama.
    Providers are registered lazily on first use to avoid import-time
    side-effects and to keep the stub usable without any optional dependencies.
    """

    _registry: dict[str, type[BaseLLMClient]] = {
        "stub": _StubLLMClient,
    }

    @classmethod
    def _ensure_providers_registered(cls) -> None:
        """Lazily register concrete providers the first time the factory is used."""
        if "openai" not in cls._registry:
            try:
                from testpilot.llm.openai_provider import OpenAIClient
                cls._registry["openai"] = OpenAIClient
            except ImportError:
                pass
        if "ollama" not in cls._registry:
            try:
                from testpilot.llm.ollama_provider import OllamaClient
                cls._registry["ollama"] = OllamaClient
            except ImportError:
                pass

    @classmethod
    def register(cls, provider: str, client_class: type[BaseLLMClient]) -> None:
        """Register a new provider implementation at runtime."""
        cls._registry[provider.lower()] = client_class

    @classmethod
    def create(cls, provider: str, **kwargs: object) -> BaseLLMClient:
        """
        Instantiate the client for *provider*.

        Parameters
        ----------
        provider:
            One of the registered provider names ('openai', 'ollama', 'stub').
        **kwargs:
            Provider-specific constructor arguments.

        Raises
        ------
        ValueError
            If *provider* is not registered.
        """
        cls._ensure_providers_registered()
        provider = provider.lower()
        if provider not in cls._registry:
            available = ", ".join(sorted(cls._registry))
            raise ValueError(
                f"Unknown LLM provider '{provider}'. "
                f"Available: {available}. "
                f"Check TESTPILOT_LLM_PROVIDER in your .env file."
            )
        return cls._registry[provider](**kwargs)

    @classmethod
    def from_settings(cls, settings: object | None = None) -> BaseLLMClient:
        """
        Create a correctly-configured client from the application Settings.

        Routes to the concrete provider (openai/ollama/stub) based on
        settings.llm_provider.  Builds provider kwargs from settings fields.
        """
        cls._ensure_providers_registered()

        if settings is None:
            return _StubLLMClient()

        from testpilot.config import Settings, LLMProvider

        if not isinstance(settings, Settings):
            return _StubLLMClient()

        provider = settings.llm_provider.value

        if provider == LLMProvider.OPENAI.value:
            if not settings.openai_api_key:
                raise ValueError(
                    "OPENAI_API_KEY is not set.  "
                    "Add it to your .env file or set the environment variable."
                )
            from testpilot.llm.openai_provider import create_from_settings as _openai_create
            return _openai_create(settings)

        if provider == LLMProvider.OLLAMA.value:
            from testpilot.llm.ollama_provider import create_from_settings as _ollama_create
            return _ollama_create(settings)

        # Fallback: stub (should not normally be reached after registration)
        return _StubLLMClient()
