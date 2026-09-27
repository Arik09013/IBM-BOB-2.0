"""
Ollama LLM provider for TestPilot AI.

Implements BaseLLMClient against a locally running Ollama instance.

Ollama exposes an OpenAI-compatible /api/chat endpoint (and also a
/api/generate endpoint).  We use /api/chat for consistency with the
OpenAI provider interface.

Configuration (environment variables / .env):
  OLLAMA_BASE_URL  — default http://localhost:11434
  OLLAMA_MODEL     — model name, e.g. codellama (default: codellama)

No API key is required for a local Ollama instance.

Security notes:
  - No credentials to protect.
  - Base URL is logged at DEBUG level only (not sensitive).
"""

from __future__ import annotations

from typing import Any

from testpilot.llm.client import BaseLLMClient, LLMMessage, LLMResponse
from testpilot.llm.openai_provider import LLMProviderError
from testpilot.utils.logging import get_logger

_log = get_logger("testpilot.llm.ollama")

_DEFAULT_BASE_URL = "http://localhost:11434"
_DEFAULT_MODEL = "codellama"


class OllamaClient(BaseLLMClient):
    """
    LLM client for a locally running Ollama instance.

    Uses the Ollama /api/chat endpoint which accepts the same message
    structure as the OpenAI Chat Completions API.

    Parameters
    ----------
    model:
        Ollama model name (must be pulled locally).
    base_url:
        Ollama server base URL.
    timeout:
        Per-request timeout in seconds.
    """

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 120.0,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    # ------------------------------------------------------------------
    # BaseLLMClient interface
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """
        Call the Ollama /api/chat endpoint.

        Raises
        ------
        LLMProviderError
            On connection failure, timeout, or unexpected response format.
        """
        import httpx

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [m.to_dict() for m in messages],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    f"{self._base_url}/api/chat",
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise LLMProviderError(
                f"Ollama request timed out after {self._timeout}s.  "
                "Is Ollama running?"
            ) from exc
        except httpx.ConnectError as exc:
            raise LLMProviderError(
                f"Could not connect to Ollama at {self._base_url}.  "
                "Start Ollama with: ollama serve"
            ) from exc
        except httpx.RequestError as exc:
            raise LLMProviderError(
                f"Ollama network error: {type(exc).__name__}"
            ) from exc

        if resp.status_code != 200:
            raise LLMProviderError(
                f"Ollama returned HTTP {resp.status_code}.  "
                f"Model '{self._model}' may not be pulled.  "
                f"Run: ollama pull {self._model}"
            )

        try:
            data = resp.json()
        except Exception as exc:
            raise LLMProviderError("Ollama response was not valid JSON.") from exc

        return self._parse_response(data)

    def is_available(self) -> bool:
        """
        Quick connectivity check — returns True if Ollama responds to a
        health-check request.  Does not raise; logs at DEBUG level.
        """
        import httpx

        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self._base_url}/api/tags")
            return resp.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        try:
            message = data["message"]
            content = message.get("content", "")
        except KeyError as exc:
            raise LLMProviderError(
                f"Unexpected Ollama response structure: {exc}"
            ) from exc

        # Ollama does not always return token counts
        return LLMResponse(
            content=content,
            model=data.get("model", self._model),
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
        )


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------

def create_from_settings(settings: Any) -> OllamaClient:
    """Construct an OllamaClient from the application Settings object."""
    return OllamaClient(
        model=settings.effective_llm_model,
        base_url=settings.ollama_base_url,
        timeout=settings.llm_request_timeout,
    )
