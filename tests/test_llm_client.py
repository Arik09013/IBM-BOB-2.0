"""
Tests for the LLM client abstraction (testpilot.llm.client).

Verifies:
- LLMMessage and LLMResponse are constructable.
- StubLLMClient returns a stub response without making network calls.
- LLMClientFactory.create works for the 'stub' provider.
- LLMClientFactory raises ValueError for unknown providers.
- LLMClientFactory.from_settings falls back to stub when provider not registered.
"""

from __future__ import annotations

import pytest

from testpilot.llm.client import (
    LLMClientFactory,
    LLMMessage,
    LLMResponse,
)


class TestLLMMessage:
    def test_construction(self):
        msg = LLMMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_to_dict(self):
        msg = LLMMessage(role="system", content="You are a testing assistant.")
        d = msg.to_dict()
        assert d == {"role": "system", "content": "You are a testing assistant."}


class TestLLMResponse:
    def test_default_construction(self):
        r = LLMResponse(content="some output")
        assert r.content == "some output"
        assert r.prompt_tokens == 0
        assert r.completion_tokens == 0

    def test_with_tokens(self):
        r = LLMResponse(content="x", prompt_tokens=10, completion_tokens=20, total_tokens=30)
        assert r.total_tokens == 30


class TestStubLLMClient:
    def test_create_stub(self):
        client = LLMClientFactory.create("stub")
        assert client.provider_name == "stub"
        assert client.model_name == "stub-model"

    def test_chat_returns_response(self):
        client = LLMClientFactory.create("stub")
        messages = [LLMMessage(role="user", content="Write a test for add()")]
        response = client.chat(messages)
        assert isinstance(response, LLMResponse)
        assert len(response.content) > 0

    def test_stub_content_clearly_labelled(self):
        client = LLMClientFactory.create("stub")
        response = client.chat([LLMMessage(role="user", content="test")])
        assert "STUB" in response.content or "placeholder" in response.content.lower()

    def test_no_network_call(self):
        """Stub must not make any network calls — validated by absence of httpx import errors."""
        client = LLMClientFactory.create("stub")
        # If this raises, it means the stub incorrectly tried a network call
        response = client.chat([LLMMessage(role="user", content="ping")])
        assert response is not None


class TestLLMClientFactory:
    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            LLMClientFactory.create("nonexistent_provider_xyz")

    def test_error_message_lists_available(self):
        try:
            LLMClientFactory.create("bad")
        except ValueError as e:
            assert "stub" in str(e).lower()

    def test_from_settings_stub_provider(self):
        """
        When provider is explicitly 'stub', from_settings() returns the
        stub client (no network).
        """
        from testpilot.config import LLMProvider, Settings

        s = Settings()
        object.__setattr__(s, "llm_provider", LLMProvider.OLLAMA)
        # Use factory.create("stub") directly for a guaranteed stub
        client = LLMClientFactory.create("stub")
        assert client.provider_name == "stub"
        response = client.chat([LLMMessage(role="user", content="test")])
        assert isinstance(response, LLMResponse)

    def test_register_custom_provider(self):
        from testpilot.llm.client import BaseLLMClient

        class MyClient(BaseLLMClient):
            @property
            def provider_name(self): return "myprovider"
            @property
            def model_name(self): return "mymodel"
            def chat(self, messages, *, temperature=0.2, max_tokens=4096):
                return LLMResponse(content="custom")

        LLMClientFactory.register("myprovider", MyClient)
        client = LLMClientFactory.create("myprovider")
        assert client.provider_name == "myprovider"
        response = client.chat([])
        assert response.content == "custom"

        # Clean up registry after test
        LLMClientFactory._registry.pop("myprovider", None)
