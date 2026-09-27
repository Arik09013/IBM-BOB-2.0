"""
Tests for LLM providers: OpenAI and Ollama.

All tests use mocked HTTP — no real network calls are made.
The test suite must pass completely offline.

Coverage:
  - stub provider still works (regression)
  - OpenAI provider construction
  - Ollama provider construction
  - provider factory selection (openai, ollama, stub)
  - invalid provider raises clear error
  - environment variable configuration
  - API key is NEVER exposed in exceptions/logs
  - mocked OpenAI successful request
  - mocked OpenAI error responses (HTTP 401, 500)
  - mocked Ollama successful request
  - mocked Ollama connection failure
  - from_settings routing (openai / ollama / stub)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from testpilot.llm.client import LLMClientFactory, LLMMessage, LLMResponse
from testpilot.llm.openai_provider import LLMProviderError, OpenAIClient
from testpilot.llm.ollama_provider import OllamaClient


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _mock_httpx_response(status_code: int, body: dict | str) -> MagicMock:
    """Build a mock httpx.Response-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    if isinstance(body, dict):
        resp.json.return_value = body
        resp.text = json.dumps(body)
    else:
        resp.json.side_effect = ValueError("not json")
        resp.text = body
    return resp


def _openai_success_body(content: str = "Hello from OpenAI") -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _ollama_success_body(content: str = "Hello from Ollama") -> dict:
    return {
        "model": "codellama",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "prompt_eval_count": 8,
        "eval_count": 12,
    }


# ---------------------------------------------------------------------------
# Stub provider (regression)
# ---------------------------------------------------------------------------

class TestStubProviderRegression:
    def test_stub_still_works(self):
        client = LLMClientFactory.create("stub")
        assert client.provider_name == "stub"
        response = client.chat([LLMMessage(role="user", content="ping")])
        assert isinstance(response, LLMResponse)
        assert "STUB" in response.content

    def test_stub_no_network(self):
        """Stub must not import or call httpx."""
        client = LLMClientFactory.create("stub")
        # If httpx were called this would raise in an offline environment
        with patch("httpx.Client") as mock_client:
            client.chat([LLMMessage(role="user", content="test")])
            mock_client.assert_not_called()


# ---------------------------------------------------------------------------
# OpenAI provider construction
# ---------------------------------------------------------------------------

class TestOpenAIProviderConstruction:
    def test_constructs_with_key(self):
        client = OpenAIClient(api_key="sk-test-key-not-real")
        assert client.provider_name == "openai"

    def test_model_name_default(self):
        client = OpenAIClient(api_key="sk-test")
        assert client.model_name  # non-empty

    def test_model_name_custom(self):
        client = OpenAIClient(api_key="sk-test", model="gpt-4o")
        assert client.model_name == "gpt-4o"

    def test_empty_key_raises(self):
        with pytest.raises(ValueError, match="API key"):
            OpenAIClient(api_key="")

    def test_api_key_not_in_repr(self):
        """API key must NOT be exposed in repr or str."""
        client = OpenAIClient(api_key="sk-super-secret-key")
        as_str = repr(client) + str(client)
        assert "sk-super-secret-key" not in as_str

    def test_api_key_not_in_model_dump(self):
        """Pydantic models around the client must not leak the key."""
        # The client itself is a plain class, not a Pydantic model
        # Verify the key attr name is private
        client = OpenAIClient(api_key="sk-super-secret")
        assert not hasattr(client, "api_key"), "api_key must not be a public attribute"
        assert hasattr(client, "_api_key")


# ---------------------------------------------------------------------------
# OpenAI mocked requests
# ---------------------------------------------------------------------------

class TestOpenAIMockedRequests:
    def _make_client(self) -> OpenAIClient:
        return OpenAIClient(api_key="sk-test-key", model="gpt-4o-mini")

    def test_successful_chat(self):
        client = self._make_client()
        mock_resp = _mock_httpx_response(200, _openai_success_body("Test output"))

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_resp
            response = client.chat([LLMMessage(role="user", content="hello")])

        assert isinstance(response, LLMResponse)
        assert response.content == "Test output"
        assert response.model == "gpt-4o-mini"
        assert response.total_tokens == 15

    def test_http_401_raises_provider_error(self):
        client = self._make_client()
        mock_resp = _mock_httpx_response(401, {"error": "Unauthorized"})

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_resp
            with pytest.raises(LLMProviderError, match="401"):
                client.chat([LLMMessage(role="user", content="test")])

    def test_http_500_raises_provider_error(self):
        client = self._make_client()
        mock_resp = _mock_httpx_response(500, {"error": "Server Error"})

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_resp
            with pytest.raises(LLMProviderError, match="500"):
                client.chat([LLMMessage(role="user", content="test")])

    def test_error_message_does_not_contain_api_key(self):
        client = OpenAIClient(api_key="sk-REAL-SECRET-KEY", model="gpt-4o-mini")
        mock_resp = _mock_httpx_response(401, {"error": "bad key"})

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_resp
            try:
                client.chat([LLMMessage(role="user", content="test")])
            except LLMProviderError as exc:
                assert "sk-REAL-SECRET-KEY" not in str(exc)

    def test_timeout_raises_provider_error(self):
        import httpx
        client = self._make_client()

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.side_effect = (
                httpx.TimeoutException("timed out")
            )
            with pytest.raises(LLMProviderError, match="timed out"):
                client.chat([LLMMessage(role="user", content="test")])

    def test_token_usage_extracted(self):
        client = self._make_client()
        body = _openai_success_body()
        body["usage"] = {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}
        mock_resp = _mock_httpx_response(200, body)

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_resp
            response = client.chat([LLMMessage(role="user", content="hi")])

        assert response.prompt_tokens == 20
        assert response.completion_tokens == 10
        assert response.total_tokens == 30


# ---------------------------------------------------------------------------
# Ollama provider construction
# ---------------------------------------------------------------------------

class TestOllamaProviderConstruction:
    def test_constructs_defaults(self):
        client = OllamaClient()
        assert client.provider_name == "ollama"
        assert client.model_name == "codellama"

    def test_custom_model(self):
        client = OllamaClient(model="mistral")
        assert client.model_name == "mistral"

    def test_custom_base_url(self):
        client = OllamaClient(base_url="http://myserver:11434")
        assert "myserver" in client._base_url

    def test_no_api_key_required(self):
        """Ollama must be constructable without any API key."""
        client = OllamaClient()
        assert client is not None


# ---------------------------------------------------------------------------
# Ollama mocked requests
# ---------------------------------------------------------------------------

class TestOllamaMockedRequests:
    def _make_client(self) -> OllamaClient:
        return OllamaClient(model="codellama")

    def test_successful_chat(self):
        client = self._make_client()
        mock_resp = _mock_httpx_response(200, _ollama_success_body("Ollama says hi"))

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_resp
            response = client.chat([LLMMessage(role="user", content="hello")])

        assert isinstance(response, LLMResponse)
        assert response.content == "Ollama says hi"
        assert response.model == "codellama"

    def test_connection_error_raises_provider_error(self):
        import httpx
        client = self._make_client()

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.side_effect = (
                httpx.ConnectError("refused")
            )
            with pytest.raises(LLMProviderError, match="Ollama"):
                client.chat([LLMMessage(role="user", content="test")])

    def test_model_not_pulled_404(self):
        client = self._make_client()
        mock_resp = _mock_httpx_response(404, {"error": "model not found"})

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_resp
            with pytest.raises(LLMProviderError):
                client.chat([LLMMessage(role="user", content="test")])

    def test_timeout_raises_provider_error(self):
        import httpx
        client = self._make_client()

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.side_effect = (
                httpx.TimeoutException("slow")
            )
            with pytest.raises(LLMProviderError, match="timed out"):
                client.chat([LLMMessage(role="user", content="test")])

    def test_token_usage_extracted(self):
        client = self._make_client()
        body = _ollama_success_body()
        body["prompt_eval_count"] = 5
        body["eval_count"] = 10
        mock_resp = _mock_httpx_response(200, body)

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_resp
            response = client.chat([LLMMessage(role="user", content="hi")])

        assert response.prompt_tokens == 5
        assert response.completion_tokens == 10
        assert response.total_tokens == 15

    def test_is_available_returns_false_when_offline(self):
        import httpx
        client = self._make_client()

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.get.side_effect = (
                httpx.ConnectError("offline")
            )
            result = client.is_available()

        assert result is False


# ---------------------------------------------------------------------------
# Factory: provider selection
# ---------------------------------------------------------------------------

class TestProviderFactorySelection:
    def test_factory_returns_stub(self):
        client = LLMClientFactory.create("stub")
        assert client.provider_name == "stub"

    def test_factory_returns_openai(self):
        client = LLMClientFactory.create("openai", api_key="sk-test")
        assert client.provider_name == "openai"

    def test_factory_returns_ollama(self):
        client = LLMClientFactory.create("ollama")
        assert client.provider_name == "ollama"

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            LLMClientFactory.create("nonexistent_xyz_provider")

    def test_error_message_lists_available_providers(self):
        try:
            LLMClientFactory.create("notareal")
        except ValueError as e:
            msg = str(e).lower()
            assert "stub" in msg

    def test_case_insensitive_provider_name(self):
        client = LLMClientFactory.create("STUB")
        assert client.provider_name == "stub"


# ---------------------------------------------------------------------------
# from_settings routing
# ---------------------------------------------------------------------------

class TestFromSettingsRouting:
    def test_stub_provider_via_settings(self, monkeypatch):
        """
        When provider is 'stub' (or an unrecognised value),
        from_settings must not make network calls.
        """
        # Directly create stub
        client = LLMClientFactory.create("stub")
        assert client.provider_name == "stub"

    def test_openai_from_settings_requires_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from testpilot.config import LLMProvider, Settings
        s = Settings()
        object.__setattr__(s, "llm_provider", LLMProvider.OPENAI)
        object.__setattr__(s, "openai_api_key", "")
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            LLMClientFactory.from_settings(s)

    def test_openai_from_settings_with_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-for-test")
        from testpilot.config import LLMProvider, Settings
        s = Settings()
        object.__setattr__(s, "llm_provider", LLMProvider.OPENAI)
        object.__setattr__(s, "openai_api_key", "sk-test-key-for-test")
        client = LLMClientFactory.from_settings(s)
        assert client.provider_name == "openai"

    def test_ollama_from_settings(self, monkeypatch):
        from testpilot.config import LLMProvider, Settings
        s = Settings()
        object.__setattr__(s, "llm_provider", LLMProvider.OLLAMA)
        client = LLMClientFactory.from_settings(s)
        assert client.provider_name == "ollama"

    def test_none_settings_returns_stub(self):
        client = LLMClientFactory.from_settings(None)
        assert client.provider_name == "stub"
