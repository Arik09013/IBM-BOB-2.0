"""
Agent base interface for TestPilot AI.

Every specialized agent in the pipeline implements BaseAgent.

Design contract:
- Agents receive a SessionContext and a Settings object.
- Agents return an updated SessionContext.
- Agents must not mutate global state.
- Agents must not store secrets or API keys internally.
- Each agent logs its start and finish events via the session logger.

NOT YET IMPLEMENTED (Phase 1+):
  - RepositoryAnalyzerAgent
  - TestGenerationAgent
  - ExecutionAgent
  - FailureAnalysisAgent
  - RepairAgent
  - ReportAgent
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from testpilot.config import Settings
    from testpilot.llm.client import BaseLLMClient
    from testpilot.session_context import SessionContext


# ---------------------------------------------------------------------------
# Agent result
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    """
    Outcome of a single agent run.

    Attributes
    ----------
    success:
        True when the agent completed its task without a fatal error.
    context:
        Updated SessionContext after the agent's work.
    message:
        Human-readable summary of what happened (shown in CLI output).
    errors:
        Non-fatal errors encountered during execution.
    """

    success: bool
    context: "SessionContext"
    message: str = ""
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class BaseAgent(ABC):
    """
    Abstract base class for all TestPilot pipeline agents.

    Subclasses must implement:
      - ``name``     — a short identifier (e.g. 'analyzer', 'generator')
      - ``run()``    — the agent's main logic

    Subclasses receive a shared LLM client and Settings at construction
    time so they never need to create their own LLM connections.
    """

    def __init__(
        self,
        llm_client: "BaseLLMClient",
        settings: "Settings",
    ) -> None:
        self._llm = llm_client
        self._settings = settings

    # ------------------------------------------------------------------
    # Must implement
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this agent (used in logs and reports)."""

    @abstractmethod
    def run(self, context: "SessionContext") -> AgentResult:
        """
        Execute this agent's logic.

        Parameters
        ----------
        context:
            Current shared pipeline state.  Read required inputs;
            write outputs back before returning.

        Returns
        -------
        AgentResult
            Always returned — never raises for a recoverable failure.
            Set ``success=False`` and populate ``errors`` for failures.
        """

    # ------------------------------------------------------------------
    # Optional hooks — subclasses may override
    # ------------------------------------------------------------------

    def pre_run(self, context: "SessionContext") -> None:
        """
        Called immediately before ``run()``.

        Use for setup, validation of inputs, or logging.
        Default implementation is a no-op.
        """

    def post_run(self, context: "SessionContext", result: AgentResult) -> None:
        """
        Called immediately after ``run()``.

        Use for cleanup, post-validation, or logging.
        Default implementation is a no-op.
        """

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _log_start(self, context: "SessionContext") -> None:
        """Log the agent's start event to stderr (no PII, no secrets)."""
        from testpilot.utils.logging import get_logger

        logger = get_logger(f"testpilot.agents.{self.name}", run_id=context.run_id)
        logger.info("Agent '%s' starting.  Step: %s", self.name, context.current_step.value)

    def _log_finish(self, context: "SessionContext", result: AgentResult) -> None:
        """Log the agent's completion event."""
        from testpilot.utils.logging import get_logger

        logger = get_logger(f"testpilot.agents.{self.name}", run_id=context.run_id)
        status = "SUCCESS" if result.success else "FAILURE"
        logger.info(
            "Agent '%s' finished.  Status: %s.  %s",
            self.name,
            status,
            result.message or "",
        )


# ---------------------------------------------------------------------------
# Placeholder agent (used by the Phase 0 pipeline to demonstrate the interface)
# ---------------------------------------------------------------------------

class NotImplementedAgent(BaseAgent):
    """
    A placeholder agent that clearly signals it is not yet implemented.

    Used by the Phase 0 orchestrator to stand in for future agents without
    simulating fake output.
    """

    def __init__(self, agent_name: str, llm_client: "BaseLLMClient", settings: "Settings") -> None:
        super().__init__(llm_client, settings)
        self._name = agent_name

    @property
    def name(self) -> str:
        return self._name

    def run(self, context: "SessionContext") -> AgentResult:
        message = (
            f"Agent '{self._name}' is not yet implemented.  "
            "This is a Phase 0 placeholder.  See Phase 1 for implementation."
        )
        context.warnings.append(message)
        return AgentResult(success=False, context=context, message=message)
