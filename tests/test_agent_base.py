"""
Tests for the agent base interface (testpilot.agents.base).

Verifies:
- BaseAgent is abstract and cannot be instantiated directly.
- NotImplementedAgent is importable, instantiable, and returns a clear result.
- AgentResult fields are correct.
"""

from __future__ import annotations

import pytest

from testpilot.agents.base import AgentResult, BaseAgent, NotImplementedAgent
from testpilot.session_context import SessionContext


@pytest.fixture
def stub_llm():
    from testpilot.llm.client import LLMClientFactory
    return LLMClientFactory.create("stub")


@pytest.fixture
def default_settings():
    from testpilot.config import Settings
    return Settings()


class TestBaseAgentIsAbstract:
    def test_cannot_instantiate_directly(self, stub_llm, default_settings):
        with pytest.raises(TypeError):
            BaseAgent(llm_client=stub_llm, settings=default_settings)  # type: ignore[abstract]


class TestNotImplementedAgent:
    def test_instantiates(self, stub_llm, default_settings):
        agent = NotImplementedAgent("test-agent", stub_llm, default_settings)
        assert agent.name == "test-agent"

    def test_run_returns_agent_result(self, stub_llm, default_settings):
        agent = NotImplementedAgent("analyzer", stub_llm, default_settings)
        ctx = SessionContext()
        result = agent.run(ctx)
        assert isinstance(result, AgentResult)

    def test_run_returns_success_false(self, stub_llm, default_settings):
        agent = NotImplementedAgent("analyzer", stub_llm, default_settings)
        result = agent.run(SessionContext())
        assert result.success is False

    def test_run_adds_warning_to_context(self, stub_llm, default_settings):
        agent = NotImplementedAgent("generator", stub_llm, default_settings)
        ctx = SessionContext()
        result = agent.run(ctx)
        assert len(result.context.warnings) > 0

    def test_run_message_contains_agent_name(self, stub_llm, default_settings):
        agent = NotImplementedAgent("my-agent", stub_llm, default_settings)
        result = agent.run(SessionContext())
        assert "my-agent" in result.message


class TestAgentResult:
    def test_success_true(self):
        ctx = SessionContext()
        r = AgentResult(success=True, context=ctx, message="done")
        assert r.success is True
        assert r.message == "done"
        assert r.errors == []

    def test_errors_list(self):
        ctx = SessionContext()
        r = AgentResult(success=False, context=ctx, errors=["something went wrong"])
        assert len(r.errors) == 1
