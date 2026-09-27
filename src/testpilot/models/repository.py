"""
Repository analysis data models for TestPilot AI.

These Pydantic models are the structured output produced by the Repository
Analyzer agent.  They are intentionally serialisation-safe so they can be:

  1. Stored inside SessionContext.
  2. Persisted to disk as JSON for later inspection.
  3. Consumed by the future Test Generation Agent.

Design rules:
  - Every field has a default so partial construction is safe.
  - All Path fields are stored as strings for JSON compatibility.
  - No field stores API keys, secrets, or fabricated data.
  - Coverage fields are populated only when real execution data is available.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SymbolKind(str, Enum):
    """Coarse classification of a Python symbol extracted by AST analysis."""

    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    CLASS = "class"
    METHOD = "method"
    ASYNC_METHOD = "async_method"
    CONSTRUCTOR = "constructor"


class CoverageStatus(str, Enum):
    """Outcome of the coverage collection attempt."""

    COLLECTED = "collected"
    """Real coverage data was successfully collected."""

    UNAVAILABLE = "unavailable"
    """Coverage tooling (pytest-cov / coverage.py) is not installed."""

    NO_TESTS = "no_tests"
    """The repository has no test files to execute."""

    TESTS_FAILED = "tests_failed"
    """Tests ran but one or more failed; coverage may be partial."""

    EXECUTION_ERROR = "execution_error"
    """The test-runner subprocess itself failed (import error, timeout, etc.)."""

    NOT_ATTEMPTED = "not_attempted"
    """Coverage collection was not attempted (e.g. empty repo, invalid path)."""


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class SymbolInfo(BaseModel):
    """Structured record for a single Python symbol extracted by AST analysis."""

    name: str
    """Unqualified symbol name (e.g. 'add', '__init__', 'Calculator')."""

    qualified_name: str
    """Module-relative qualified name (e.g. 'Calculator.add')."""

    kind: SymbolKind

    file: str
    """Repository-relative path to the source file containing this symbol."""

    line: int
    """1-based line number of the symbol definition."""

    is_private: bool = False
    """True when the name starts with an underscore (excluding dunder names)."""

    is_dunder: bool = False
    """True when the name is surrounded by double underscores (e.g. __init__)."""

    parent_class: str | None = None
    """Unqualified name of the enclosing class, if any."""


class FileSummary(BaseModel):
    """Summary for a single Python file."""

    path: str
    """Repository-relative path."""

    is_test_file: bool = False
    parse_error: str | None = None
    """Set when AST parsing of this file failed; the error message is stored here."""

    symbol_count: int = 0


class CoverageSummary(BaseModel):
    """Coverage measurement results from a real pytest execution."""

    status: CoverageStatus = CoverageStatus.NOT_ATTEMPTED

    line_coverage_pct: float | None = None
    """Overall line coverage percentage (0.0–100.0), or None if unavailable."""

    lines_covered: int | None = None
    lines_total: int | None = None

    raw_output: str = ""
    """Trimmed stdout/stderr from the coverage runner (max ~4 KB)."""

    error_detail: str = ""
    """Human-readable explanation when coverage could not be collected."""

    tests_ran: int | None = None
    tests_passed: int | None = None
    tests_failed: int | None = None


class CoverageGap(BaseModel):
    """A symbol or file that appears to lack test coverage."""

    file: str
    """Repository-relative path."""

    symbol_name: str | None = None
    """Qualified symbol name, if the gap is at function/method level."""

    uncovered_lines: list[int] = Field(default_factory=list)
    """Line numbers reported as not covered by coverage.py."""

    gap_type: Literal["file", "symbol", "lines"] = "file"


# ---------------------------------------------------------------------------
# Top-level analysis result
# ---------------------------------------------------------------------------

class RepositoryAnalysis(BaseModel):
    """
    Full structured output of the Repository Analyzer agent.

    Produced once per analyzer run.  All Path values are stored as strings
    so the model is JSON-serialisable with Pydantic's default encoder.
    """

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    repository_path: str
    """Absolute path to the analysed repository root."""

    analysed_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    # ------------------------------------------------------------------
    # Repository metadata
    # ------------------------------------------------------------------
    language: str = "python"
    python_version: str = ""
    """Detected Python version string (e.g. '3.11'), or empty if not determined."""

    test_framework: str = ""
    """Detected test framework name (e.g. 'pytest'), or empty if none found."""

    test_framework_detected: bool = False
    test_framework_config_source: str = ""
    """Where the framework was detected (e.g. 'pyproject.toml', 'setup.cfg')."""

    # ------------------------------------------------------------------
    # File inventory
    # ------------------------------------------------------------------
    source_files: list[str] = Field(default_factory=list)
    """Repository-relative paths of Python source files (non-test)."""

    test_files: list[str] = Field(default_factory=list)
    """Repository-relative paths of Python test files."""

    all_python_files: list[str] = Field(default_factory=list)
    """All discovered Python files (source + test + other)."""

    file_summaries: list[FileSummary] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Symbol inventory
    # ------------------------------------------------------------------
    symbols: list[SymbolInfo] = Field(default_factory=list)
    """All symbols extracted from source files (non-test)."""

    # ------------------------------------------------------------------
    # Coverage
    # ------------------------------------------------------------------
    coverage_summary: CoverageSummary = Field(default_factory=CoverageSummary)
    coverage_gaps: list[CoverageGap] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)
    """Files that could not be parsed by AST (stored separately for clarity)."""

    # ------------------------------------------------------------------
    # Timing / research metadata
    # ------------------------------------------------------------------
    duration_seconds: float = 0.0
    """Wall-clock duration of the analysis in seconds."""

    # ------------------------------------------------------------------
    # Computed convenience properties
    # ------------------------------------------------------------------
    @property
    def source_file_count(self) -> int:
        return len(self.source_files)

    @property
    def test_file_count(self) -> int:
        return len(self.test_files)

    @property
    def symbol_count(self) -> int:
        return len(self.symbols)

    @property
    def has_tests(self) -> bool:
        return len(self.test_files) > 0

    @property
    def public_symbols(self) -> list[SymbolInfo]:
        return [s for s in self.symbols if not s.is_private and not s.is_dunder]

    @property
    def untested_public_functions(self) -> list[SymbolInfo]:
        """
        Public functions/methods that appear in coverage_gaps.
        Populated only when real coverage data is available.
        """
        gapped = {g.symbol_name for g in self.coverage_gaps if g.symbol_name}
        return [s for s in self.public_symbols if s.qualified_name in gapped]
