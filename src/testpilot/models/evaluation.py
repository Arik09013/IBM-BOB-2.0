"""
Evaluation data models for TestPilot AI research experiments.

These are schemas only — no experiment results are generated or fabricated here.

Each completed pipeline run should produce one RunMetrics record, which is
appended to ``benchmarks/results/metrics.jsonl`` for later analysis with
``evaluation/compare.py``.

The schema is designed to support side-by-side comparison of three
experimental conditions:
  - 'manual'  : a developer writes tests by hand (recorded manually)
  - 'single'  : one LLM call per target, no repair loop
  - 'multi'   : full multi-agent TestPilot pipeline

No claims are made about which approach performs better.
Results must come from actual runs, not from this file.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum, StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, computed_field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ExperimentApproach(str, Enum):
    """Experimental condition label."""

    MANUAL = "manual"
    SINGLE = "single"
    MULTI = "multi"


# ---------------------------------------------------------------------------
# Primary metrics record — one per completed run
# ---------------------------------------------------------------------------

class RunMetrics(BaseModel):
    """
    All measurable metrics for a single TestPilot pipeline run.

    Populated by the Report Agent at the end of each run.
    Intended to be serialised as a single JSON line in metrics.jsonl.
    """

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    run_id: str
    """Unique run identifier (matches SessionContext.run_id)."""

    repository: str
    """Human-readable name or path of the repository under test."""

    approach: ExperimentApproach
    """Experiment condition for this run."""

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    # ------------------------------------------------------------------
    # Coverage
    # ------------------------------------------------------------------
    coverage_before: float | None = None
    """Line/branch coverage % before test generation.  None if unmeasurable."""

    coverage_after: float | None = None
    """Line/branch coverage % after test generation and repair."""

    @computed_field  # type: ignore[misc]
    @property
    def coverage_delta(self) -> float | None:
        """Improvement in coverage percentage (after − before)."""
        if self.coverage_before is None or self.coverage_after is None:
            return None
        return round(self.coverage_after - self.coverage_before, 2)

    # ------------------------------------------------------------------
    # Test counts
    # ------------------------------------------------------------------
    tests_generated: int = 0
    """Total number of test functions produced by the generation agent."""

    tests_passed: int = 0
    """Tests that passed on first execution (before any repair)."""

    tests_failed: int = 0
    """Tests that failed or errored on first execution."""

    invalid_tests: int = 0
    """Tests that failed due to a defect in the generated test itself."""

    logic_failures: int = 0
    """Tests that failed because the source code has a real defect."""

    @computed_field  # type: ignore[misc]
    @property
    def pass_rate(self) -> float | None:
        """Fraction of generated tests that passed: tests_passed / tests_generated."""
        if self.tests_generated == 0:
            return None
        return round(self.tests_passed / self.tests_generated, 4)

    # ------------------------------------------------------------------
    # Repair loop
    # ------------------------------------------------------------------
    repair_attempts: int = 0
    """Total repair patches proposed by the Repair Agent."""

    successful_repairs: int = 0
    """Repairs confirmed to resolve a failure in re-validation."""

    @computed_field  # type: ignore[misc]
    @property
    def repair_success_rate(self) -> float | None:
        """Fraction of repair attempts that succeeded."""
        if self.repair_attempts == 0:
            return None
        return round(self.successful_repairs / self.repair_attempts, 4)

    iteration_count: int = 0
    """Number of repair→re-validation cycles used (0 = no repair needed)."""

    # ------------------------------------------------------------------
    # Human effort
    # ------------------------------------------------------------------
    human_interventions: int = 0
    """Number of times the user was asked to provide input."""

    # ------------------------------------------------------------------
    # Performance
    # ------------------------------------------------------------------
    wall_clock_seconds: float | None = None
    """Total end-to-end runtime in seconds."""

    llm_calls: int = 0
    """Total number of LLM API calls made during the run."""

    token_usage: dict[str, int] = Field(
        default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    errors_encountered: int = 0
    """Number of non-fatal errors logged during the run."""

    notes: str = ""
    """Free-text notes (e.g. manual experiment observations)."""


# ---------------------------------------------------------------------------
# Experiment summary — aggregated over multiple runs of the same condition
# ---------------------------------------------------------------------------

class ConditionSummary(BaseModel):
    """
    Aggregate statistics for all runs of a single experimental condition
    against the same benchmark repository.

    Populated by ``evaluation/compare.py``, never fabricated here.
    """

    repository: str
    approach: ExperimentApproach
    run_count: int = 0

    # Mean values across runs (None until populated from actual data)
    mean_coverage_delta: float | None = None
    mean_pass_rate: float | None = None
    mean_repair_success_rate: float | None = None
    mean_wall_clock_seconds: float | None = None
    mean_llm_calls: float | None = None
    mean_token_usage: float | None = None
    mean_human_interventions: float | None = None


# ---------------------------------------------------------------------------
# Benchmark run configuration — used to document experiment conditions
# ---------------------------------------------------------------------------

class BenchmarkConfig(BaseModel):
    """
    Documents the configuration under which a benchmark experiment was run.
    Stored alongside results so experiments are reproducible.
    """

    benchmark_id: str
    description: str
    repository_path: str
    language: str
    test_framework: str
    llm_provider: str
    llm_model: str
    max_repair_iterations: int
    approach: ExperimentApproach
    run_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    testpilot_version: str = "0.1.0"
    notes: str = ""


# ---------------------------------------------------------------------------
# Persistence helper
# ---------------------------------------------------------------------------

def append_metrics(metrics: RunMetrics, results_dir: Path) -> Path:
    """
    Append a RunMetrics record to the JSONL metrics file.

    Creates the file and directory if they do not exist.
    Returns the path to the metrics file.
    """
    import json

    results_dir.mkdir(parents=True, exist_ok=True)
    metrics_file = results_dir / "metrics.jsonl"

    with metrics_file.open("a", encoding="utf-8") as f:
        f.write(metrics.model_dump_json() + "\n")

    return metrics_file


# ---------------------------------------------------------------------------
# Phase 5: Benchmark Evaluation Models
# ---------------------------------------------------------------------------

class BenchmarkEvaluationStatus(StrEnum):
    """Overall outcome of an end-to-end benchmark evaluation."""

    SUCCESS = "success"
    """All generated tests were executed, repaired if needed, and passed with zero failures."""

    PARTIAL = "partial"
    """Some failures were resolved, but others remain."""

    NOT_REPAIRABLE = "not_repairable"
    """Failures were identified as genuine source code defects or environment issues (Phase 4 safety gate)."""

    GENERATION_FAILED = "generation_failed"
    """Test generation failed AST syntax validation or encountered LLM error."""

    FAILED = "failed"
    """Evaluation completed but tests failed to pass or repair limits were exceeded."""

    VALIDATION_ERROR = "validation_error"
    """Benchmark repository path or target module was invalid."""

    ERROR = "error"
    """An unexpected fatal error occurred during evaluation."""


class BenchmarkEvaluationResult(BaseModel):
    """
    Complete evaluation result measuring Analyze -> Generate -> Execute -> Repair.

    Produced by EvaluationRunner / run_benchmark_evaluation().
    """

    benchmark_name: str
    repository_path: str
    target_module: str = ""
    status: BenchmarkEvaluationStatus = BenchmarkEvaluationStatus.ERROR

    started_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    completed_at: datetime | None = None
    total_duration_seconds: float = 0.0

    # Phase 1: Analysis metrics
    analysis_completed: bool = False
    detected_framework: str = ""
    gap_targets: list[str] = Field(default_factory=list)

    # Phase 3: Generation metrics
    generation_status: str = ""
    tests_generated: int = 0
    valid_generated_tests: int = 0
    generated_files: list[str] = Field(default_factory=list)
    generation_duration_seconds: float = 0.0

    # Phase 2: Initial Execution metrics
    initial_execution_status: str = ""
    initial_passed: int = 0
    initial_failed: int = 0
    initial_execution_duration_seconds: float = 0.0

    # Phase 4: Repair metrics
    repair_required: bool = False
    repair_status: str = "no_failures"
    repair_attempts: int = 0
    failures_resolved: int = 0
    repair_duration_seconds: float = 0.0
    repaired_files: list[str] = Field(default_factory=list)
    has_source_code_defects: bool = False

    # Phase 2: Final Execution metrics
    final_execution_status: str = ""
    final_passed: int = 0
    final_failed: int = 0
    final_execution_duration_seconds: float = 0.0

    # Coverage metrics
    coverage_before: float | None = None
    coverage_after: float | None = None
    coverage_delta: float | None = None

    # Error and warning logs
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def resolved(self) -> bool:
        """True if final execution passed with 0 failures and status is success."""
        return self.status == BenchmarkEvaluationStatus.SUCCESS and self.final_failed == 0

    @property
    def has_coverage_improvement(self) -> bool:
        """True if coverage increased after test generation/repair."""
        return self.coverage_delta is not None and self.coverage_delta > 0

    def to_run_metrics(
        self,
        run_id: str | None = None,
        approach: ExperimentApproach = ExperimentApproach.MULTI,
    ) -> RunMetrics:
        """Convert this evaluation result to a RunMetrics instance for JSONL logging."""
        import uuid

        rid = run_id or str(uuid.uuid4())[:12]
        return RunMetrics(
            run_id=rid,
            repository=self.benchmark_name,
            approach=approach,
            timestamp=self.started_at,
            coverage_before=self.coverage_before,
            coverage_after=self.coverage_after,
            tests_generated=self.tests_generated,
            tests_passed=self.final_passed,
            tests_failed=self.final_failed,
            invalid_tests=max(0, self.tests_generated - self.valid_generated_tests),
            logic_failures=1 if self.has_source_code_defects else 0,
            repair_attempts=self.repair_attempts,
            successful_repairs=self.failures_resolved,
            iteration_count=self.repair_attempts,
            wall_clock_seconds=self.total_duration_seconds,
            errors_encountered=len(self.errors),
            notes=f"Target: {self.target_module}; Status: {self.status.value}",
        )


class SuiteEvaluationResult(BaseModel):
    """Aggregated evaluation results across a suite of benchmarks."""

    suite_name: str = "TestPilot Benchmark Suite"
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    completed_at: datetime | None = None
    total_duration_seconds: float = 0.0
    benchmarks_run: int = 0
    benchmarks_succeeded: int = 0
    benchmarks_failed: int = 0
    results: list[BenchmarkEvaluationResult] = Field(default_factory=list)
