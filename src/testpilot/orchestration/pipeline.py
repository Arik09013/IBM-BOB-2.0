"""
Pipeline orchestrator for TestPilot AI.

Phase 0 status: PLACEHOLDER ONLY.

The intended end-to-end sequence is:

    Analysis
    → Test Generation
    → Execution
    → Failure Analysis
    → Repair
    → Re-validation
    → Report

None of the actual agent implementations exist yet.  This module
defines the orchestrator interface and demonstrates the intended
control flow without simulating fake agent outputs.

Implementation is scheduled for Phases 1–4.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from testpilot.agents.base import NotImplementedAgent
from testpilot.session_context import PipelineStep, SessionContext
from testpilot.utils.logging import SessionLogger, get_logger

if TYPE_CHECKING:
    from testpilot.config import Settings
    from testpilot.llm.client import BaseLLMClient


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------

class PipelineResult:
    """
    Summary returned to the CLI after the pipeline completes (or aborts).

    Attributes
    ----------
    success:
        True only when the full pipeline ran to completion without fatal errors.
    context:
        Final SessionContext snapshot.
    message:
        Human-readable outcome summary.
    """

    def __init__(self, success: bool, context: SessionContext, message: str = "") -> None:
        self.success = success
        self.context = context
        self.message = message


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Pipeline:
    """
    Controls the end-to-end TestPilot agent pipeline.

    Phase 0 behaviour:
    - Validates the repository path.
    - Initialises the SessionContext and SessionLogger.
    - Steps through the planned pipeline sequence using NotImplementedAgent
      placeholders so the control flow is clear.
    - Saves the session context to disk.
    - Returns a PipelineResult indicating that agents are not yet available.

    Phase 1+ behaviour:
    - Replace NotImplementedAgent instances with concrete agent classes.
    - Add the repair loop (bounded by Settings.max_repair_iterations).
    - Add no-improvement early exit.
    """

    def __init__(self, settings: "Settings", llm_client: "BaseLLMClient") -> None:
        self._settings = settings
        self._llm = llm_client
        self._logger = get_logger("testpilot.pipeline")

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, repo_path: Path) -> PipelineResult:
        """
        Execute the full pipeline against *repo_path*.

        Parameters
        ----------
        repo_path:
            Resolved, validated path to the repository under test.

        Returns
        -------
        PipelineResult
        """
        run_id = str(uuid.uuid4())[:12]
        self._logger = get_logger("testpilot.pipeline", run_id=run_id)

        context = self._init_context(repo_path, run_id)
        output_dir = self._settings.ensure_output_dir() / run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        context.output_dir = output_dir

        session_log_path = output_dir / "session.jsonl"
        context.session_log_path = session_log_path

        with SessionLogger(session_log_path, run_id) as session_log:
            session_log.log("pipeline_start", {
                "repo": str(repo_path),
                "approach": context.approach,
            })

            try:
                result = self._execute_pipeline(context, session_log)
            except Exception as exc:  # noqa: BLE001 — catch-all to always produce a result
                context.current_step = PipelineStep.FAILED
                context.errors.append(f"Unhandled pipeline error: {exc}")
                result = PipelineResult(
                    success=False,
                    context=context,
                    message=f"Pipeline aborted: {exc}",
                )
                self._logger.error("Pipeline aborted with unhandled exception: %s", exc)
            finally:
                context.timing.run_finished_at = datetime.now(tz=timezone.utc)
                context.save(output_dir / "session_context.json")
                session_log.log("pipeline_finish", {
                    "success": result.success,
                    "step": context.current_step.value,
                    "wall_seconds": context.timing.total_seconds,
                })

        return result

    # ------------------------------------------------------------------
    # Private — pipeline steps
    # ------------------------------------------------------------------

    def _init_context(self, repo_path: Path, run_id: str) -> SessionContext:
        return SessionContext(
            run_id=run_id,
            repo_path=repo_path,
            repo_identifier=repo_path.name,
            approach=self._settings.approach,
        )

    def _execute_pipeline(
        self,
        context: SessionContext,
        session_log: SessionLogger,
    ) -> PipelineResult:
        """
        Walk through each pipeline step in order.

        Phase 0: every step uses a NotImplementedAgent placeholder.
        The pipeline returns after the first step with a clear message.
        """
        self._logger.info("Pipeline starting.  Approach: %s", context.approach)
        self._logger.warning(
            "Phase 0 — agent implementations are not available yet.  "
            "The pipeline will report its intended sequence and exit."
        )

        steps: list[tuple[PipelineStep, str]] = [
            (PipelineStep.ANALYSIS,         "analyzer"),
            (PipelineStep.TEST_GENERATION,  "generator"),
            (PipelineStep.EXECUTION,        "executor"),
            (PipelineStep.FAILURE_ANALYSIS, "failure_analyzer"),
            (PipelineStep.REPAIR,           "repair"),
            (PipelineStep.REVALIDATION,     "executor"),      # reuses executor
            (PipelineStep.REPORTING,        "reporter"),
        ]

        for step, agent_name in steps:
            context.current_step = step
            session_log.log("step_start", {"step": step.value, "agent": agent_name})

            agent = NotImplementedAgent(
                agent_name=agent_name,
                llm_client=self._llm,
                settings=self._settings,
            )
            agent_result = agent.run(context)
            context = agent_result.context

            session_log.log("step_finish", {
                "step": step.value,
                "agent": agent_name,
                "success": agent_result.success,
                "message": agent_result.message,
            })

            self._logger.info(
                "Step %-20s  ➜  %s",
                step.value,
                "✗ NOT IMPLEMENTED" if not agent_result.success else "✓ done",
            )

        context.current_step = PipelineStep.COMPLETE

        summary = (
            "Phase 0 pipeline walkthrough complete.  "
            f"{len(steps)} steps demonstrated using placeholder agents.  "
            "Implement Phase 1 agents to run the actual pipeline."
        )

        return PipelineResult(success=False, context=context, message=summary)

    # ------------------------------------------------------------------
    # Repair loop (Phase 1+ — skeleton shown here for reference)
    # ------------------------------------------------------------------

    def _should_continue_repair_loop(self, context: SessionContext, prev_failures: int) -> bool:
        """
        Decide whether another repair iteration is warranted.

        Rules (all must be satisfied):
        1. Iteration count has not reached the configured maximum.
        2. There are still failing tests.
        3. The failure count has decreased since the last iteration
           (no-improvement early exit when enabled).
        """
        if context.iteration_count >= self._settings.max_repair_iterations:
            return False
        if context.tests_failed == 0:
            return False
        if self._settings.no_improvement_exit and context.tests_failed >= prev_failures:
            return False
        return True
