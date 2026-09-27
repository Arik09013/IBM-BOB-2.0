"""
Repository Analyzer Agent for TestPilot AI.

Inspects a local Python repository and produces a structured RepositoryAnalysis
that downstream agents (Test Generation, etc.) can consume.

Capabilities:
  - Python source and test file discovery (recursive, with ignore rules)
  - AST-based symbol extraction (functions, classes, methods)
  - pytest detection from config files and import scanning
  - Optional real coverage measurement via pytest-cov subprocess
  - Resilient error handling: syntax errors, missing tooling, empty repos

Phase 1A: Python-only.
JavaScript/TypeScript/Go support is out of scope for this phase.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from testpilot.agents.base import AgentResult, BaseAgent
from testpilot.models.repository import (
    CoverageGap,
    CoverageStatus,
    CoverageSummary,
    FileSummary,
    RepositoryAnalysis,
    SymbolInfo,
    SymbolKind,
)
from testpilot.utils.logging import get_logger

if TYPE_CHECKING:
    from testpilot.config import Settings
    from testpilot.llm.client import BaseLLMClient
    from testpilot.session_context import SessionContext


# ---------------------------------------------------------------------------
# Directories and file patterns to ignore during discovery
# ---------------------------------------------------------------------------

_IGNORE_DIRS: frozenset[str] = frozenset({
    ".git",
    ".venv",
    "venv",
    ".env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    "build",
    "dist",
    "node_modules",
    # TestPilot-generated directories
    "output",
    "generated_tests",
    "repair_patches",
    "session_logs",
    ".tmp",
    "tmp",
})

_TEST_FILENAME_PATTERNS: tuple[str, ...] = (
    "test_",      # prefix: test_calculator.py
    "_test",      # suffix: calculator_test.py
)

_TEST_DIRNAME_PATTERNS: tuple[str, ...] = (
    "tests",
    "test",
    "testing",
)

# Maximum raw output bytes captured from coverage subprocess
_MAX_OUTPUT_BYTES = 4096

# Coverage subprocess timeout (seconds)
_COVERAGE_TIMEOUT = 60


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class RepositoryAnalyzerAgent(BaseAgent):
    """
    First agent in the TestPilot pipeline.

    Accepts a repository path from SessionContext.repo_path and writes a
    RepositoryAnalysis back into SessionContext.repository_analysis.
    """

    def __init__(
        self,
        llm_client: "BaseLLMClient",
        settings: "Settings",
    ) -> None:
        super().__init__(llm_client, settings)
        self._log = get_logger("testpilot.agents.analyzer")

    @property
    def name(self) -> str:
        return "analyzer"

    def run(self, context: "SessionContext") -> AgentResult:
        self._log_start(context)

        if context.repo_path is None:
            msg = "SessionContext.repo_path is not set; cannot analyse repository."
            context.errors.append(msg)
            return AgentResult(success=False, context=context, message=msg, errors=[msg])

        analysis = analyze_repository(
            repo_path=context.repo_path,
            settings=self._settings,
            run_id=context.run_id,
        )

        # Write structured result back into context
        context.repository_analysis = analysis  # type: ignore[attr-defined]
        context.detected_language = analysis.language
        context.detected_test_framework = analysis.test_framework
        context.coverage_before = analysis.coverage_summary.line_coverage_pct
        context.gap_targets = [
            s.qualified_name for s in analysis.untested_public_functions
        ]
        context.warnings.extend(analysis.warnings)
        context.errors.extend(analysis.errors)

        status = "success" if not analysis.errors else "partial"
        msg = (
            f"Analyzed {analysis.source_file_count} source file(s), "
            f"{analysis.test_file_count} test file(s), "
            f"{analysis.symbol_count} symbol(s).  "
            f"Coverage: {analysis.coverage_summary.status.value}."
        )
        self._log.info(msg)
        self._log_finish(context, AgentResult(success=True, context=context, message=msg))
        return AgentResult(success=(status == "success"), context=context, message=msg)


# ---------------------------------------------------------------------------
# Public functional API (used by agent and CLI independently)
# ---------------------------------------------------------------------------

def analyze_repository(
    repo_path: Path,
    *,
    settings: "Settings | None" = None,
    run_id: str = "cli",
    attempt_coverage: bool = True,
) -> RepositoryAnalysis:
    """
    Analyse *repo_path* and return a fully populated RepositoryAnalysis.

    This function is the main entry point used by both the agent and the CLI
    command.  It is intentionally free of agent-specific state so it can be
    called directly in tests.

    Parameters
    ----------
    repo_path:
        Absolute or relative path to the repository root.
    settings:
        Optional Settings object.  Used for execution_timeout.
    run_id:
        Used for log tagging only.
    attempt_coverage:
        When True (default), try to run pytest-cov in a subprocess.
    """
    log = get_logger("testpilot.analyzer", run_id=run_id)
    start = time.monotonic()

    repo_path = repo_path.resolve()
    analysis = RepositoryAnalysis(repository_path=str(repo_path))

    # ------------------------------------------------------------------
    # Guard: path must exist and be a directory
    # ------------------------------------------------------------------
    if not repo_path.exists():
        analysis.errors.append(f"Repository path does not exist: {repo_path}")
        analysis.coverage_summary.status = CoverageStatus.NOT_ATTEMPTED
        analysis.duration_seconds = time.monotonic() - start
        return analysis

    if not repo_path.is_dir():
        analysis.errors.append(f"Repository path is not a directory: {repo_path}")
        analysis.coverage_summary.status = CoverageStatus.NOT_ATTEMPTED
        analysis.duration_seconds = time.monotonic() - start
        return analysis

    log.info("Starting repository analysis: %s", repo_path)

    # ------------------------------------------------------------------
    # Step 1: discover Python files
    # ------------------------------------------------------------------
    _discover_files(repo_path, analysis)
    log.info(
        "Discovered %d source files, %d test files",
        analysis.source_file_count,
        analysis.test_file_count,
    )

    if not analysis.all_python_files:
        analysis.warnings.append("No Python files found in repository.")
        analysis.coverage_summary.status = CoverageStatus.NOT_ATTEMPTED
        analysis.duration_seconds = time.monotonic() - start
        return analysis

    # ------------------------------------------------------------------
    # Step 2: detect Python version
    # ------------------------------------------------------------------
    analysis.python_version = _detect_python_version(repo_path)

    # ------------------------------------------------------------------
    # Step 3: detect test framework
    # ------------------------------------------------------------------
    _detect_test_framework(repo_path, analysis)
    log.info("Test framework: %s (detected=%s)", analysis.test_framework, analysis.test_framework_detected)

    # ------------------------------------------------------------------
    # Step 4: AST symbol extraction
    # ------------------------------------------------------------------
    for rel_path in analysis.source_files:
        abs_path = repo_path / rel_path
        _extract_symbols(abs_path, rel_path, analysis)
    log.info("Extracted %d symbols", analysis.symbol_count)

    # ------------------------------------------------------------------
    # Step 5: coverage collection (optional, subprocess-isolated)
    # ------------------------------------------------------------------
    if attempt_coverage:
        timeout = settings.test_execution_timeout if settings else _COVERAGE_TIMEOUT
        _collect_coverage(repo_path, analysis, timeout=timeout)
    else:
        analysis.coverage_summary.status = CoverageStatus.NOT_ATTEMPTED

    analysis.duration_seconds = round(time.monotonic() - start, 3)
    log.info("Analysis complete in %.2fs", analysis.duration_seconds)
    return analysis


# ---------------------------------------------------------------------------
# Step 1 — File discovery
# ---------------------------------------------------------------------------

def _discover_files(repo_path: Path, analysis: RepositoryAnalysis) -> None:
    """Walk *repo_path* and classify all .py files."""
    all_py: list[str] = []
    source: list[str] = []
    test: list[str] = []
    summaries: list[FileSummary] = []

    for py_file in sorted(_walk_python_files(repo_path)):
        rel = str(py_file.relative_to(repo_path))
        is_test = _is_test_file(py_file, repo_path)
        all_py.append(rel)
        summaries.append(FileSummary(path=rel, is_test_file=is_test))
        if is_test:
            test.append(rel)
        else:
            source.append(rel)

    analysis.all_python_files = all_py
    analysis.source_files = source
    analysis.test_files = test
    analysis.file_summaries = summaries


def _walk_python_files(root: Path):
    """Yield .py file Paths under *root*, skipping ignored directories."""
    for item in root.iterdir():
        if item.is_dir():
            if item.name in _IGNORE_DIRS or item.name.endswith(".egg-info"):
                continue
            yield from _walk_python_files(item)
        elif item.is_file() and item.suffix == ".py":
            yield item


def _is_test_file(py_file: Path, repo_root: Path) -> bool:
    """Return True when *py_file* looks like a test file by name or location."""
    name = py_file.stem.lower()
    if any(name.startswith(p) or name.endswith(p.rstrip("_")) for p in _TEST_FILENAME_PATTERNS):
        return True
    # Check if any ancestor directory has a test-like name
    try:
        parts = py_file.relative_to(repo_root).parts
    except ValueError:
        parts = py_file.parts
    for part in parts[:-1]:  # exclude the filename itself
        if part.lower() in _TEST_DIRNAME_PATTERNS:
            return True
    return False


# ---------------------------------------------------------------------------
# Step 2 — Python version detection
# ---------------------------------------------------------------------------

def _detect_python_version(repo_path: Path) -> str:
    """Infer the target Python version from project metadata files."""
    # pyproject.toml: requires-python = ">=3.11"
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'requires-python\s*=\s*["\']([^"\']+)["\']', text)
        if m:
            raw = m.group(1).strip()
            # Extract the first version number
            ver = re.search(r"(\d+\.\d+)", raw)
            if ver:
                return ver.group(1)

    # setup.cfg / setup.py: python_requires
    for fname in ("setup.cfg", "setup.py"):
        f = repo_path / fname
        if f.exists():
            text = f.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"python_requires\s*[=:]\s*[\"']?([>=<!\d., ]+)", text)
            if m:
                ver = re.search(r"(\d+\.\d+)", m.group(1))
                if ver:
                    return ver.group(1)

    # .python-version file (pyenv)
    pv = repo_path / ".python-version"
    if pv.exists():
        raw_ver = pv.read_text(encoding="utf-8").strip()
        m = re.match(r"(\d+\.\d+)", raw_ver)
        if m:
            return m.group(1)

    return ""


# ---------------------------------------------------------------------------
# Step 3 — Test framework detection
# ---------------------------------------------------------------------------

def _detect_test_framework(repo_path: Path, analysis: RepositoryAnalysis) -> None:
    """Populate analysis.test_framework* fields by inspecting project metadata."""

    # pyproject.toml
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        if "[tool.pytest" in text or "pytest" in text:
            _set_pytest(analysis, "pyproject.toml")
            return

    # setup.cfg
    setup_cfg = repo_path / "setup.cfg"
    if setup_cfg.exists():
        text = setup_cfg.read_text(encoding="utf-8", errors="replace")
        if "[tool:pytest]" in text or "pytest" in text:
            _set_pytest(analysis, "setup.cfg")
            return

    # pytest.ini / tox.ini
    for fname in ("pytest.ini", "tox.ini"):
        f = repo_path / fname
        if f.exists():
            _set_pytest(analysis, fname)
            return

    # requirements*.txt files
    for req_file in sorted(repo_path.glob("requirements*.txt")):
        text = req_file.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^\s*pytest", text, re.MULTILINE):
            _set_pytest(analysis, req_file.name)
            return

    # Scan test files for pytest import
    for rel in analysis.test_files[:10]:  # only sample first 10 for speed
        abs_path = repo_path / rel
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
            if "import pytest" in text or "from pytest" in text:
                _set_pytest(analysis, f"import in {rel}")
                return
        except OSError:
            pass

    # No framework detected
    if analysis.test_files:
        analysis.warnings.append(
            "Test files found but no recognised test framework detected."
        )


def _set_pytest(analysis: RepositoryAnalysis, source: str) -> None:
    analysis.test_framework = "pytest"
    analysis.test_framework_detected = True
    analysis.test_framework_config_source = source


# ---------------------------------------------------------------------------
# Step 4 — AST symbol extraction
# ---------------------------------------------------------------------------

def _extract_symbols(abs_path: Path, rel_path: str, analysis: RepositoryAnalysis) -> None:
    """Parse *abs_path* with ast and append discovered symbols to analysis."""
    try:
        source = abs_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(abs_path))
    except SyntaxError as exc:
        msg = f"Syntax error in {rel_path}: {exc}"
        analysis.parse_errors.append(msg)
        analysis.warnings.append(msg)
        # Update the FileSummary for this file
        for fs in analysis.file_summaries:
            if fs.path == rel_path:
                fs.parse_error = str(exc)
        return
    except OSError as exc:
        analysis.warnings.append(f"Could not read {rel_path}: {exc}")
        return

    visitor = _SymbolVisitor(rel_path)
    visitor.visit(tree)
    analysis.symbols.extend(visitor.symbols)

    # Update symbol count on the FileSummary
    for fs in analysis.file_summaries:
        if fs.path == rel_path:
            fs.symbol_count = len(visitor.symbols)


class _SymbolVisitor(ast.NodeVisitor):
    """AST visitor that extracts function and class symbol information."""

    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path
        self.symbols: list[SymbolInfo] = []
        self._class_stack: list[str] = []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_symbol(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
        kind: SymbolKind,
    ) -> SymbolInfo:
        name = node.name
        parent = self._class_stack[-1] if self._class_stack else None
        qualified = f"{parent}.{name}" if parent else name
        is_dunder = name.startswith("__") and name.endswith("__")
        is_private = name.startswith("_") and not is_dunder
        return SymbolInfo(
            name=name,
            qualified_name=qualified,
            kind=kind,
            file=self.rel_path,
            line=node.lineno,
            is_private=is_private,
            is_dunder=is_dunder,
            parent_class=parent,
        )

    # ------------------------------------------------------------------
    # Visitors
    # ------------------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.symbols.append(self._make_symbol(node, SymbolKind.CLASS))
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if self._class_stack:
            kind = (
                SymbolKind.CONSTRUCTOR if node.name == "__init__"
                else SymbolKind.METHOD
            )
        else:
            kind = SymbolKind.FUNCTION
        self.symbols.append(self._make_symbol(node, kind))
        # Do NOT recurse into nested functions with generic_visit so we
        # avoid inflating symbol counts with closures.

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if self._class_stack:
            kind = SymbolKind.ASYNC_METHOD
        else:
            kind = SymbolKind.ASYNC_FUNCTION
        self.symbols.append(self._make_symbol(node, kind))


# ---------------------------------------------------------------------------
# Step 5 — Coverage collection
# ---------------------------------------------------------------------------

def _collect_coverage(
    repo_path: Path,
    analysis: RepositoryAnalysis,
    timeout: float = _COVERAGE_TIMEOUT,
) -> None:
    """
    Attempt to run pytest with coverage in a subprocess and parse the result.

    This function NEVER fabricates coverage values.  If collection fails for
    any reason, status is set to an appropriate CoverageStatus and the reason
    is recorded.
    """
    summary = analysis.coverage_summary

    if not analysis.test_files:
        summary.status = CoverageStatus.NO_TESTS
        summary.error_detail = "No test files found; skipping coverage collection."
        return

    if not analysis.test_framework_detected:
        summary.status = CoverageStatus.UNAVAILABLE
        summary.error_detail = "No recognised test framework detected; skipping coverage."
        return

    # Check that pytest is available in the *current* Python environment
    pytest_available = _check_tool_available("pytest")
    cov_available = _check_tool_available("coverage")

    if not pytest_available:
        summary.status = CoverageStatus.UNAVAILABLE
        summary.error_detail = "pytest not found in the current environment."
        return

    # Build command: use pytest-cov if available, else raw coverage
    cmd = _build_coverage_command(repo_path, cov_available)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        summary.status = CoverageStatus.EXECUTION_ERROR
        summary.error_detail = f"Coverage subprocess timed out after {timeout}s."
        return
    except FileNotFoundError as exc:
        summary.status = CoverageStatus.UNAVAILABLE
        summary.error_detail = f"Could not launch test runner: {exc}"
        return
    except Exception as exc:  # noqa: BLE001
        summary.status = CoverageStatus.EXECUTION_ERROR
        summary.error_detail = f"Unexpected subprocess error: {exc}"
        return

    # Capture output (trimmed)
    combined = (result.stdout or "") + (result.stderr or "")
    summary.raw_output = combined[:_MAX_OUTPUT_BYTES]

    # Parse test counts from pytest output
    _parse_pytest_counts(combined, summary)

    # Parse coverage percentage
    pct = _parse_coverage_pct(combined)

    if pct is not None:
        summary.line_coverage_pct = pct
        summary.status = (
            CoverageStatus.COLLECTED
            if result.returncode in (0, 1)  # 0=all pass, 1=some fail
            else CoverageStatus.EXECUTION_ERROR
        )
        if result.returncode not in (0, 1):
            summary.error_detail = (
                f"pytest exited with code {result.returncode}."
            )
        # Even if some tests fail, mark as TESTS_FAILED but keep coverage data
        if summary.tests_failed and summary.tests_failed > 0:
            summary.status = CoverageStatus.TESTS_FAILED

        # Build coverage gap list from JSON report if available
        _parse_coverage_gaps(repo_path, analysis)
    else:
        # Coverage output not parseable — but tests may have run
        if result.returncode == 0:
            summary.status = CoverageStatus.UNAVAILABLE
            summary.error_detail = "pytest ran but no coverage percentage found in output."
        elif result.returncode == 1:
            summary.status = CoverageStatus.TESTS_FAILED
            summary.error_detail = "Some tests failed; coverage data unavailable."
        else:
            summary.status = CoverageStatus.EXECUTION_ERROR
            summary.error_detail = (
                f"pytest exited with code {result.returncode}.  "
                f"Output: {combined[:300]}"
            )


def _check_tool_available(tool: str) -> bool:
    """Return True if *tool* is importable in the current Python environment."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", tool, "--version"],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _build_coverage_command(repo_path: Path, cov_available: bool) -> list[str]:
    """Build the pytest command list for coverage collection."""
    # Try pytest-cov first (cleaner output)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--co", "-q", "--no-header",
             "--tb=no", "-p", "no:cacheprovider"],
            cwd=str(repo_path),
            capture_output=True,
            timeout=15,
        )
        has_pytest_cov = b"pytest-cov" in result.stdout or b"pytest-cov" in result.stderr
    except Exception:  # noqa: BLE001
        has_pytest_cov = False

    # Determine src layout
    src_dirs = _find_source_dirs(repo_path)
    cov_args: list[str] = []
    for src in src_dirs:
        cov_args += [f"--cov={src}"]

    if not cov_args:
        cov_args = ["--cov=."]

    return [
        sys.executable, "-m", "pytest",
        "--tb=short",
        "--no-header",
        "-q",
        *cov_args,
        "--cov-report=term-missing",
        "--cov-report=json:.testpilot_cov.json",
    ]


def _find_source_dirs(repo_path: Path) -> list[str]:
    """Heuristic: find non-test Python directories to measure coverage on."""
    candidates = []
    for item in repo_path.iterdir():
        if item.is_dir() and item.name not in _IGNORE_DIRS and item.name not in _TEST_DIRNAME_PATTERNS:
            # Check if it contains Python files
            if any(item.glob("*.py")):
                candidates.append(item.name)
    return candidates


def _parse_pytest_counts(output: str, summary: CoverageSummary) -> None:
    """Extract test pass/fail counts from pytest terminal output."""
    # e.g. "3 passed, 1 failed in 0.42s"  or  "5 passed in 0.10s"
    m = re.search(r"(\d+) passed", output)
    if m:
        summary.tests_passed = int(m.group(1))
    m = re.search(r"(\d+) failed", output)
    if m:
        summary.tests_failed = int(m.group(1))
    passed = summary.tests_passed or 0
    failed = summary.tests_failed or 0
    if passed + failed > 0:
        summary.tests_ran = passed + failed


def _parse_coverage_pct(output: str) -> float | None:
    """
    Extract the total coverage percentage from pytest-cov terminal output.

    Looks for patterns like:
      TOTAL   120   38   68%
      Total coverage: 68.00%
    """
    # pytest-cov table: "TOTAL  <stmts>  <miss>  <cover>%"
    m = re.search(r"^TOTAL\s+\d+\s+\d+\s+(\d+)%", output, re.MULTILINE)
    if m:
        return float(m.group(1))
    # coverage.py: "Total coverage: 68%"
    m = re.search(r"[Tt]otal\s+coverage[:\s]+(\d+(?:\.\d+)?)%", output)
    if m:
        return float(m.group(1))
    return None


def _parse_coverage_gaps(repo_path: Path, analysis: RepositoryAnalysis) -> None:
    """
    Parse the JSON coverage report produced by --cov-report=json to build
    a list of CoverageGap entries.
    """
    cov_json = repo_path / ".testpilot_cov.json"
    if not cov_json.exists():
        return

    try:
        data = json.loads(cov_json.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    finally:
        # Clean up the temporary coverage JSON file
        try:
            cov_json.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass

    files = data.get("files", {})
    for abs_path_str, file_data in files.items():
        try:
            rel = str(Path(abs_path_str).relative_to(repo_path))
        except ValueError:
            rel = abs_path_str

        missing_lines: list[int] = file_data.get("missing_lines", [])
        if not missing_lines:
            continue

        # File-level gap
        analysis.coverage_gaps.append(
            CoverageGap(file=rel, uncovered_lines=missing_lines, gap_type="lines")
        )

        # Symbol-level gaps — find symbols whose definition line is uncovered
        for sym in analysis.symbols:
            if sym.file == rel and sym.line in missing_lines:
                analysis.coverage_gaps.append(
                    CoverageGap(
                        file=rel,
                        symbol_name=sym.qualified_name,
                        uncovered_lines=[sym.line],
                        gap_type="symbol",
                    )
                )

    # Update coverage line totals from summary
    summary_data = data.get("totals", {})
    if summary_data:
        analysis.coverage_summary.lines_covered = summary_data.get("covered_lines")
        analysis.coverage_summary.lines_total = summary_data.get("num_statements")
