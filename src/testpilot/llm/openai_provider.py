"""
OpenAI-compatible LLM provider for TestPilot AI.

Implements BaseLLMClient against the OpenAI Chat Completions API.
Also works with any OpenAI-compatible endpoint (Azure OpenAI, LM Studio,
local proxies) by overriding OPENAI_BASE_URL.

Configuration (environment variables / .env):
  OPENAI_API_KEY   — required
  OPENAI_BASE_URL  — optional, default https://api.openai.com/v1
  TESTPILOT_LLM_MODEL — model name, e.g. gpt-4o (default: gpt-4o-mini)

Security rules:
  - API key is NEVER logged, printed, or included in error messages.
  - This module never commits credentials.
"""

from __future__ import annotations

import json
from typing import Any

from testpilot.llm.client import BaseLLMClient, LLMMessage, LLMResponse
from testpilot.utils.logging import get_logger

_log = get_logger("testpilot.llm.openai")

_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIClient(BaseLLMClient):
    """
    LLM client for the OpenAI Chat Completions API.

    Uses ``httpx`` (already a project dependency) for HTTP so no extra
    dependency is required.  The ``openai`` SDK optional extra can also be
    used if installed, but is NOT required.

    Parameters
    ----------
    api_key:
        OpenAI API key.  Never logged or exposed.
    model:
        Model name, e.g. ``gpt-4o-mini``.
    base_url:
        API base URL.  Override for Azure OpenAI or compatible proxies.
    timeout:
        Per-request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 120.0,
    ) -> None:
        if not api_key:
            raise ValueError(
                "OpenAI API key is required.  "
                "Set the OPENAI_API_KEY environment variable."
            )
        self._api_key = api_key   # stored privately; never exposed externally
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    # ------------------------------------------------------------------
    # BaseLLMClient interface
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "openai"

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
        Call the OpenAI Chat Completions endpoint.

        Raises
        ------
        LLMProviderError
            On HTTP errors, JSON parse failures, or unexpected responses.
        """
        import httpx

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise LLMProviderError(
                f"OpenAI request timed out after {self._timeout}s."
            ) from exc
        except httpx.RequestError as exc:
            raise LLMProviderError(
                f"OpenAI network error: {type(exc).__name__}"
            ) from exc

        if resp.status_code != 200:
            # Do NOT include response body — it may echo back the key
            raise LLMProviderError(
                f"OpenAI API returned HTTP {resp.status_code}.  "
                "Check OPENAI_API_KEY and model name."
            )

        try:
            data = resp.json()
        except Exception as exc:
            raise LLMProviderError("OpenAI response was not valid JSON.") from exc

        return self._parse_response(data)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"] or ""
        except (KeyError, IndexError) as exc:
            raise LLMProviderError(
                f"Unexpected OpenAI response structure: {exc}"
            ) from exc

        usage = data.get("usage", {})
        return LLMResponse(
            content=content,
            model=data.get("model", self._model),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------

def create_from_settings(settings: Any) -> OpenAIClient:
    """
    Construct an OpenAIClient from the application Settings object.

    Raises ValueError if OPENAI_API_KEY is not configured.
    """
    return OpenAIClient(
        api_key=settings.openai_api_key,
        model=settings.effective_llm_model,
        base_url=settings.openai_base_url,
        timeout=settings.llm_request_timeout,
    )


# ---------------------------------------------------------------------------
# Provider error
# ---------------------------------------------------------------------------

class LLMProviderError(RuntimeError):
    """Raised when an LLM provider call fails."""
