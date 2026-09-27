"""
SessionContext — shared pipeline state for a single TestPilot run.

The SessionContext is the single source of truth passed between agents.
It is serialised to disk at the end of every pipeline step, making runs
resumable and providing a complete, machine-readable audit trail for
research experiments.

Design rules:
- Every field has a sensible default so partial construction is safe.
- No field stores raw secrets or API keys.
- The model is intentionally forward-compatible: future agents can add
  fields without breaking existing session files.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from testpilot.models.execution import ExecutionReport
from testpilot.models.generation import GenerationReport
from testpilot.models.repair import RepairReport

if TYPE_CHECKING:
    from testpilot.models.repository import RepositoryAnalysis


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class PipelineStep(str, Enum):
    """Current position in the agent pipeline."""

    INIT = "init"
    ANALYSIS = "analysis"
    GAP_DETECTION = "gap_detection"
    TEST_GENERATION = "test_generation"
    EXECUTION = "execution"
    FAILURE_ANALYSIS = "failure_analysis"
    REPAIR = "repair"
    REVALIDATION = "revalidation"
    REPORTING = "reporting"
    COMPLETE = "complete"
    FAILED = "failed"


class TestCaseResult(BaseModel):
    """Result record for a single generated test function."""

    test_id: str
    """Unique identifier for this test (e.g. 'test_add_positive_numbers')."""

    test_file: str
    """Relative path to the generated test file."""

    target_function: str
    """Fully-qualified name of the function under test."""

    status: Literal["passed", "failed", "error", "skipped"] = "skipped"
    outcome_detail: str = ""
    """Raw stdout/stderr captured from the test runner, trimmed to 2 KB."""

    is_invalid: bool = False
    """True when the test itself is malformed (syntax/import error)."""

    is_logic_failure: bool = False
    """True when the failure indicates a defect in the source code."""


class RepairAttempt(BaseModel):
    """Record of a single repair suggestion produced by the Repair Agent."""

    attempt_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    iteration: int
    target_test_id: str
    patch_file: str = ""
    """Relative path to the unified diff patch file."""

    rationale: str = ""
    """Plain-language explanation of the proposed change."""

    applied: bool = False
    """Whether the patch was applied for re-validation."""

    resolved: bool = False
    """Whether re-validation confirmed the failure is fixed."""


class TimingInfo(BaseModel):
    """Wall-clock timestamps for each pipeline step."""

    run_started_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    analysis_started_at: datetime | None = None
    generation_started_at: datetime | None = None
    execution_started_at: datetime | None = None
    failure_analysis_started_at: datetime | None = None
    repair_started_at: datetime | None = None
    reporting_started_at: datetime | None = None
    run_finished_at: datetime | None = None

    @property
    def total_seconds(self) -> float | None:
        if self.run_finished_at is None:
            return None
        return (self.run_finished_at - self.run_started_at).total_seconds()


# ---------------------------------------------------------------------------
# Core context model
# ---------------------------------------------------------------------------

class SessionContext(BaseModel):
    """
    Shared mutable state for one end-to-end TestPilot pipeline run.

    Passed into each agent; agents read their required inputs and write
    their outputs back.  The orchestrator persists this object to disk
    after each step.
    """

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    """Short unique identifier for this run (12 hex chars)."""

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    repo_path: Path | None = None
    """Resolved absolute path to the repository under analysis."""

    repo_identifier: str = ""
    """Human-readable repo label (e.g. 'my-project' or 'github.com/user/repo')."""

    approach: Literal["single", "multi"] = "multi"
    """Experiment condition: 'single' = one LLM call, 'multi' = full pipeline."""

    # ------------------------------------------------------------------
    # Pipeline state
    # ------------------------------------------------------------------
    current_step: PipelineStep = PipelineStep.INIT
    iteration_count: int = 0
    """Number of completed repair→re-validation cycles."""

    # ------------------------------------------------------------------
    # Analysis outputs (populated by Repository Analyzer)
    # ------------------------------------------------------------------
    detected_language: str = ""
    detected_framework: str = ""
    detected_test_framework: str = ""
    coverage_before: float | None = None
    """Line/branch coverage % before test generation, if measurable."""

    gap_targets: list[str] = Field(default_factory=list)
    """Fully-qualified names of functions identified as untested."""

    repository_analysis: Any | None = None
    """
    RepositoryAnalysis produced by the Repository Analyzer agent.
    Typed as Any to avoid a circular import; consumers should cast to
    RepositoryAnalysis.  Serialised as a nested dict in JSON output.
    """

    # ------------------------------------------------------------------
    # Generation outputs (populated by Test Generation Agent)
    # ------------------------------------------------------------------
    generated_test_files: list[str] = Field(default_factory=list)
    """Relative paths of generated test files written to disk."""

    tests_generated_count: int = 0
    generation_report: GenerationReport | None = None
    """
    GenerationReport produced by the TestGenerationAgent.
    Serialised as a nested dict in JSON output.
    """

    # ------------------------------------------------------------------
    # Execution outputs (populated by Execution Agent — not yet implemented)
    # ------------------------------------------------------------------
    test_results: list[TestCaseResult] = Field(default_factory=list)
    coverage_after: float | None = None
    execution_report: ExecutionReport | None = None
    """
    ExecutionReport produced by the TestExecutionAgent.
    Serialised as a nested dict in JSON output.
    """

    @property
    def tests_passed(self) -> int:
        return sum(1 for t in self.test_results if t.status == "passed")

    @property
    def tests_failed(self) -> int:
        return sum(1 for t in self.test_results if t.status in ("failed", "error"))

    @property
    def invalid_tests(self) -> int:
        return sum(1 for t in self.test_results if t.is_invalid)

    @property
    def logic_failures(self) -> int:
        return sum(1 for t in self.test_results if t.is_logic_failure)

    # ------------------------------------------------------------------
    # Repair outputs (populated by FailureAnalysisAgent & RepairAgent)
    # ------------------------------------------------------------------
    repair_attempts: list[RepairAttempt] = Field(default_factory=list)
    repair_report: RepairReport | None = None
    """
    RepairReport produced by the RepairAgent / run_repair_loop.
    Serialised as a nested dict in JSON output.
    """

    @property
    def successful_repairs(self) -> int:
        return sum(1 for r in self.repair_attempts if r.resolved)

    # ------------------------------------------------------------------
    # Human interaction
    # ------------------------------------------------------------------
    human_intervention_count: int = 0
    """Number of times the user was asked to provide input or confirm."""

    # ------------------------------------------------------------------
    # Timing
    # ------------------------------------------------------------------
    timing: TimingInfo = Field(default_factory=TimingInfo)

    # ------------------------------------------------------------------
    # LLM usage tracking
    # ------------------------------------------------------------------
    llm_call_count: int = 0
    token_usage: dict[str, int] = Field(
        default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )

    # ------------------------------------------------------------------
    # Artefact paths
    # ------------------------------------------------------------------
    output_dir: Path | None = None
    report_md_path: Path | None = None
    report_json_path: Path | None = None
    session_log_path: Path | None = None

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    """Catch-all for per-agent extra fields during development."""

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def save(self, path: Path | None = None) -> Path:
        """Serialise this context to a JSON file and return the path."""
        target = path or (self.output_dir / "session_context.json" if self.output_dir else Path("session_context.json"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: Path) -> "SessionContext":
        """Deserialise a previously saved SessionContext from disk."""
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
