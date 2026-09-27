"""
Execution data models for TestPilot AI.

These Pydantic models represent the structured output produced by the
TestExecutionAgent and pytest test execution.

Design rules:
  - Every field has a sensible default so partial construction is always safe.
  - All Path fields are stored as strings for JSON serialisation compatibility.
  - No secrets, credentials, or API keys are stored.
  - Coverage values reflect real measured test execution — never fabricated.
  - Output streams (stdout, stderr) are bounded to avoid huge memory footprint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from testpilot.models.repository import CoverageStatus

# Bounded output constants (per stream)
_MAX_REPORT_OUTPUT_BYTES = 32768


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ExecutionStatus(StrEnum):
    """Overall outcome of a test execution run."""

    PASSED = "passed"
    """All discovered tests executed and passed."""

    TEST_FAILURES = "test_failures"
    """Tests ran to completion, but one or more test assertions/checks failed."""

    COLLECTION_ERROR = "collection_error"
    """Pytest encountered errors during test discovery/collection (e.g. syntax/import errors)."""

    TIMEOUT = "timeout"
    """The test execution subprocess was killed due to exceeding the timeout."""

    ENVIRONMENT_ERROR = "environment_error"
    """Pytest could not be executed due to a missing runner, executable, or misconfiguration."""

    VALIDATION_ERROR = "validation_error"
    """Repository path is invalid, missing, or not a directory."""

    NO_TESTS = "no_tests"
    """Pytest ran successfully but no tests were collected."""

    ERROR = "error"
    """An unexpected fatal execution error occurred."""


class TestStatus(StrEnum):
    """Execution status of an individual test case."""


    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"
    XFAILED = "xfailed"
    XPASSED = "xpassed"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class TestCaseResultItem(BaseModel):
    """Structured result for an individual test case."""

    nodeid: str
    """Canonical test identifier (e.g. 'tests/test_calc.py::TestAdd::test_positive')."""

    name: str = ""
    """Short test function or method name (e.g. 'test_positive')."""

    file: str = ""
    """Repository-relative path to the test file."""

    classname: str = ""
    """Test class or module hierarchy name."""

    status: TestStatus = TestStatus.PASSED

    duration_seconds: float | None = None
    """Execution duration in seconds, if reported by the runner."""

    failure_type: str = ""
    """Exception or failure type (e.g. 'AssertionError', 'RuntimeError')."""

    failure_message: str = ""
    """Short summary message of the failure or error."""

    traceback: str = ""
    """Relevant traceback excerpt (trimmed to avoid excessive size)."""


class ExecutionSummary(BaseModel):
    """High-level counters for a test run."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    xfailed: int = 0
    xpassed: int = 0

    @property
    def pass_rate(self) -> float | None:
        """Fraction of total tests that passed (0.0 - 1.0), or None if total is 0."""
        if self.total == 0:
            return None
        return round(self.passed / self.total, 4)


class ExecutionCoverage(BaseModel):
    """Real coverage measurement from test execution."""

    status: CoverageStatus = CoverageStatus.NOT_ATTEMPTED

    coverage_pct: float | None = None
    """Overall line coverage percentage (0.0–100.0), or None if unavailable."""

    lines_covered: int | None = None
    lines_total: int | None = None

    missing_lines_by_file: dict[str, list[int]] = Field(default_factory=dict)
    """Repository-relative file path mapped to list of uncovered line numbers."""

    raw_output: str = ""
    """Trimmed raw output from the coverage reporter."""

    error_detail: str = ""
    """Human-readable detail if coverage collection failed."""


# ---------------------------------------------------------------------------
# Top-level Execution Report
# ---------------------------------------------------------------------------

class ExecutionReport(BaseModel):
    """
    Complete structured report of a repository test execution.

    Created by TestExecutionAgent / execute_tests().
    Stored in SessionContext.execution_report and persisted as JSON.
    """

    # Execution metadata
    repository_path: str
    command: list[str] = Field(default_factory=list)
    exit_code: int = -1
    status: ExecutionStatus = ExecutionStatus.ERROR

    started_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=UTC)
    )
    completed_at: datetime | None = None
    duration_seconds: float = 0.0
    timed_out: bool = False
    success: bool = False
    """True when the test execution completed normally (even if target tests failed)."""

    # Test summary and per-test items
    summary: ExecutionSummary = Field(default_factory=ExecutionSummary)
    tests: list[TestCaseResultItem] = Field(default_factory=list)

    # Bounded outputs
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False

    # Coverage
    coverage: ExecutionCoverage = Field(default_factory=ExecutionCoverage)

    # Diagnostics
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def total_tests(self) -> int:
        return self.summary.total

    @property
    def passed_count(self) -> int:
        return self.summary.passed

    @property
    def failed_count(self) -> int:
        return self.summary.failed

    @property
    def pass_rate(self) -> float | None:
        return self.summary.pass_rate

    @property
    def has_failures(self) -> bool:
        """True if any tests failed, errored, or collection failed."""
        return (
            self.summary.failed > 0
            or self.summary.errors > 0
            or self.status in (ExecutionStatus.TEST_FAILURES, ExecutionStatus.COLLECTION_ERROR)
        )

    @property
    def failed_tests(self) -> list[str]:
        """List of nodeids for all failed or errored tests."""
        return [
            t.nodeid
            for t in self.tests
            if t.status in (TestStatus.FAILED, TestStatus.ERROR)
        ]

    @property
    def failed_test_items(self) -> list[TestCaseResultItem]:
        """List of TestCaseResultItem objects for all failed or errored tests."""
        return [
            t
            for t in self.tests
            if t.status in (TestStatus.FAILED, TestStatus.ERROR)
        ]
