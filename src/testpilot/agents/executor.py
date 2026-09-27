"""
Test Execution Agent for TestPilot AI.

Executes a repository's test suite safely using the existing subprocess
infrastructure, parses pytest results machine-readably (JUnit XML + stdout),
collects real coverage data, and produces a structured ExecutionReport.

Design rules:
  - NEVER modifies the target repository.
  - Reuses testpilot.utils.execution.run_pytest (no duplicate subprocess runners).
  - Machine-readable parsing via JUnit XML and coverage JSON with stdout fallbacks.
  - Target test failures are distinguished from TestPilot execution crashes.
  - No secret or credential handling.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from testpilot.agents.base import AgentResult, BaseAgent
from testpilot.models.execution import (
    _MAX_REPORT_OUTPUT_BYTES,
    ExecutionCoverage,
    ExecutionReport,
    ExecutionStatus,
    ExecutionSummary,
    TestCaseResultItem,
    TestStatus,
)
from testpilot.models.repository import CoverageStatus
from testpilot.session_context import PipelineStep, TestCaseResult
from testpilot.utils.execution import (
    DEFAULT_TIMEOUT,
    ExecutionEnvironment,
    ExecutionResult,
    detect_environment,
    run_pytest,
)
from testpilot.utils.logging import get_logger

if TYPE_CHECKING:
    from testpilot.config import Settings
    from testpilot.llm.client import BaseLLMClient
    from testpilot.session_context import SessionContext

_log = get_logger("testpilot.agents.executor")

# Maximum length for captured traceback excerpts in individual test results
_MAX_TRACEBACK_LENGTH = 4096


# ---------------------------------------------------------------------------
# Agent implementation
# ---------------------------------------------------------------------------

class TestExecutionAgent(BaseAgent):
    """
    Test execution agent in the TestPilot AI pipeline.

    Takes a SessionContext, validates the repository, runs pytest via the
    execution utility, parses results, populates ExecutionReport, and updates
    the context.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        settings: Settings,
    ) -> None:
        super().__init__(llm_client, settings)
        self._log = get_logger("testpilot.agents.executor")

    @property
    def name(self) -> str:
        return "executor"

    def run(self, context: SessionContext) -> AgentResult:
        self._log_start(context)

        # 1. Validate repo_path in context
        if context.repo_path is None:
            msg = "SessionContext.repo_path is not set; cannot execute tests."
            context.errors.append(msg)
            report = ExecutionReport(
                repository_path="",
                status=ExecutionStatus.VALIDATION_ERROR,
                errors=[msg],
            )
            context.execution_report = report
            self._log_finish(context, AgentResult(success=False, context=context, message=msg, errors=[msg]))
            return AgentResult(success=False, context=context, message=msg, errors=[msg])

        repo_path = Path(context.repo_path).resolve()
        if not repo_path.exists() or not repo_path.is_dir():
            msg = f"Repository path does not exist or is not a directory: {repo_path}"
            context.errors.append(msg)
            report = ExecutionReport(
                repository_path=str(repo_path),
                status=ExecutionStatus.VALIDATION_ERROR,
                errors=[msg],
            )
            context.execution_report = report
            self._log_finish(context, AgentResult(success=False, context=context, message=msg, errors=[msg]))
            return AgentResult(success=False, context=context, message=msg, errors=[msg])

        # 2. Analyze repository if not already analyzed
        if getattr(context, "repository_analysis", None) is None:
            from testpilot.agents.analyzer import analyze_repository

            self._log.info("RepositoryAnalysis not found in context; running static analysis first.")
            analysis = analyze_repository(
                repo_path=repo_path,
                settings=self._settings,
                run_id=context.run_id,
                attempt_coverage=False,
            )
            context.repository_analysis = analysis
            context.detected_language = analysis.language
            context.detected_test_framework = analysis.test_framework

        # 3. Record execution start timing
        if context.timing.execution_started_at is None:
            context.timing.execution_started_at = datetime.now(tz=UTC)

        # 4. Execute tests
        timeout = self._settings.test_execution_timeout if self._settings else DEFAULT_TIMEOUT
        report = execute_tests(
            repo_path=repo_path,
            settings=self._settings,
            timeout=timeout,
            run_id=context.run_id,
        )

        # 5. Populate SessionContext
        context.execution_report = report
        context.coverage_after = report.coverage.coverage_pct
        context.current_step = PipelineStep.EXECUTION

        # Synchronise legacy test_results list on SessionContext
        context.test_results = [
            TestCaseResult(
                test_id=t.nodeid,
                test_file=t.file,
                target_function=t.name,
                status=_map_status_to_legacy(t.status),
                outcome_detail=(t.failure_message or t.traceback)[:2048],
                is_invalid=(t.status == TestStatus.ERROR),
                is_logic_failure=(t.status == TestStatus.FAILED),
            )
            for t in report.tests
        ]

        # 6. Distinguish test failures from runner crashes
        if report.status in (ExecutionStatus.PASSED, ExecutionStatus.TEST_FAILURES, ExecutionStatus.NO_TESTS):
            success = True
            msg = (
                f"Executed {report.summary.total} test(s): "
                f"{report.summary.passed} passed, {report.summary.failed} failed, "
                f"{report.summary.skipped} skipped, {report.summary.errors} error(s). "
                f"Duration: {report.duration_seconds:.2f}s."
            )
        elif report.status == ExecutionStatus.TIMEOUT:
            success = False
            msg = f"Test execution timed out after {report.duration_seconds:.1f}s."
            context.errors.extend(report.errors)
        elif report.status == ExecutionStatus.COLLECTION_ERROR:
            success = False
            msg = f"Collection error during test execution: {report.errors[0] if report.errors else 'Syntax/import error'}"
            context.errors.extend(report.errors)
        else:
            success = False
            msg = f"Execution error ({report.status.value}): {report.errors[0] if report.errors else 'Unknown error'}"
            context.errors.extend(report.errors)

        result = AgentResult(success=success, context=context, message=msg, errors=report.errors)
        self._log_finish(context, result)
        return result


def _map_status_to_legacy(
    status: TestStatus,
) -> Literal["passed", "failed", "error", "skipped"]:
    """Map TestStatus enum to TestCaseResult status literal."""
    if status == TestStatus.PASSED:
        return "passed"
    if status == TestStatus.FAILED:
        return "failed"
    if status == TestStatus.ERROR:
        return "error"
    return "skipped"



# ---------------------------------------------------------------------------
# Public functional API
# ---------------------------------------------------------------------------

def execute_tests(
    repo_path: Path,
    *,
    settings: Settings | None = None,
    env: ExecutionEnvironment | None = None,
    with_coverage: bool = True,
    extra_args: list[str] | None = None,
    timeout: float | None = None,
    run_id: str = "cli",
) -> ExecutionReport:
    """
    Execute tests in *repo_path* and return a fully populated ExecutionReport.

    Standalone entry point used by TestExecutionAgent, CLI, and unit tests.
    Does not modify the repository.

    Parameters
    ----------
    repo_path:
        Path to the repository root.
    settings:
        Optional Settings object for default configuration.
    env:
        Pre-detected ExecutionEnvironment. If None, detected automatically.
    with_coverage:
        Whether to attempt real coverage collection using pytest-cov.
    extra_args:
        Additional command line arguments passed to pytest.
    timeout:
        Subprocess timeout in seconds.
    run_id:
        Identifier for logging.
    """
    log = get_logger("testpilot.executor", run_id=run_id)
    start_time = time.monotonic()
    started_at = datetime.now(tz=UTC)

    repo_path = repo_path.resolve()
    report = ExecutionReport(
        repository_path=str(repo_path),
        started_at=started_at,
    )

    # 1. Validate repository path
    if not repo_path.exists() or not repo_path.is_dir():
        err = f"Repository path does not exist or is not a directory: {repo_path}"
        report.errors.append(err)
        report.status = ExecutionStatus.VALIDATION_ERROR
        report.duration_seconds = round(time.monotonic() - start_time, 3)
        report.completed_at = datetime.now(tz=UTC)
        return report

    # 2. Detect environment
    if env is None:
        env = detect_environment(repo_path)

    if not env.pytest_available:
        err = f"pytest is not available in the environment ({env.python_executable})."
        report.errors.append(err)
        report.status = ExecutionStatus.ENVIRONMENT_ERROR
        report.duration_seconds = round(time.monotonic() - start_time, 3)
        report.completed_at = datetime.now(tz=UTC)
        return report

    # 3. Determine timeout
    effective_timeout = timeout
    if effective_timeout is None:
        effective_timeout = settings.test_execution_timeout if settings else DEFAULT_TIMEOUT

    # 4. Prepare temporary directory for machine-readable output files
    with tempfile.TemporaryDirectory() as td:
        temp_dir = Path(td)
        junit_xml_path = temp_dir / "junit.xml"
        cov_json_path = temp_dir / "cov.json"

        # Construct runner arguments
        pytest_args: list[str] = [
            f"--junitxml={junit_xml_path}",
            "-o",
            "junit_family=xunit2",
            "-rA",
        ]

        attempt_cov = with_coverage and env.coverage_available
        if attempt_cov:
            pytest_args.append(f"--cov-report=json:{cov_json_path}")
        elif with_coverage and not env.coverage_available:
            report.coverage.status = CoverageStatus.UNAVAILABLE
            report.coverage.error_detail = "pytest-cov or coverage is not installed in the environment."

        if extra_args:
            pytest_args.extend(extra_args)

        log.info("Running pytest in %s (timeout=%ss, coverage=%s)", repo_path, effective_timeout, attempt_cov)

        exec_result: ExecutionResult = run_pytest(
            repo_path=repo_path,
            env=env,
            extra_args=pytest_args,
            timeout=effective_timeout,
            with_coverage=attempt_cov,
        )

        # 5. Populate basic execution metadata
        report.command = exec_result.command
        report.exit_code = exec_result.exit_code
        report.duration_seconds = exec_result.duration_seconds
        report.timed_out = exec_result.timed_out
        report.completed_at = datetime.now(tz=UTC)

        # Bound stdout and stderr
        stdout_raw = exec_result.stdout or ""
        stderr_raw = exec_result.stderr or ""
        if len(stdout_raw) > _MAX_REPORT_OUTPUT_BYTES:
            report.stdout = stdout_raw[:_MAX_REPORT_OUTPUT_BYTES] + "\n... [truncated]"
            report.stdout_truncated = True
        else:
            report.stdout = stdout_raw

        if len(stderr_raw) > _MAX_REPORT_OUTPUT_BYTES:
            report.stderr = stderr_raw[:_MAX_REPORT_OUTPUT_BYTES] + "\n... [truncated]"
            report.stderr_truncated = True
        else:
            report.stderr = stderr_raw

        # 6. Parse results
        _parse_execution_outcomes(
            exec_result=exec_result,
            junit_xml_path=junit_xml_path,
            cov_json_path=cov_json_path,
            repo_path=repo_path,
            report=report,
            attempted_coverage=attempt_cov,
        )

    log.info(
        "Execution complete: status=%s, total=%d, passed=%d, failed=%d in %.2fs",
        report.status.value,
        report.summary.total,
        report.summary.passed,
        report.summary.failed,
        report.duration_seconds,
    )
    return report


# ---------------------------------------------------------------------------
# Outcome parsing & synthesis
# ---------------------------------------------------------------------------

def _parse_execution_outcomes(
    exec_result: ExecutionResult,
    junit_xml_path: Path,
    cov_json_path: Path,
    repo_path: Path,
    report: ExecutionReport,
    attempted_coverage: bool,
) -> None:
    """Parse XML, JSON coverage, and stdout to construct complete ExecutionReport."""

    # 1. Parse JUnit XML if available
    xml_tests: list[TestCaseResultItem] = []
    if junit_xml_path.exists():
        try:
            xml_tests = _parse_junit_xml(junit_xml_path.read_text(encoding="utf-8", errors="replace"), repo_path)
        except Exception as exc:  # noqa: BLE001
            report.warnings.append(f"Failed to parse JUnit XML: {exc}")

    # 2. Parse stdout summary info (-rA section and test count line)
    stdout_tests, stdout_summary = _parse_stdout_tests(exec_result.combined_output)

    # 3. Merge test results
    tests = _merge_test_records(xml_tests=xml_tests, stdout_tests=stdout_tests)
    report.tests = tests

    # 4. Synthesise summary numbers
    summary = ExecutionSummary()
    for t in tests:
        if t.status == TestStatus.PASSED:
            summary.passed += 1
        elif t.status == TestStatus.FAILED:
            summary.failed += 1
        elif t.status == TestStatus.ERROR:
            summary.errors += 1
        elif t.status == TestStatus.SKIPPED:
            summary.skipped += 1
        elif t.status == TestStatus.XFAILED:
            summary.xfailed += 1
        elif t.status == TestStatus.XPASSED:
            summary.xpassed += 1

    summary.total = (
        summary.passed
        + summary.failed
        + summary.errors
        + summary.skipped
        + summary.xfailed
        + summary.xpassed
    )

    # If test list was empty (e.g. collection error or unparsed output), use stdout counters if available
    if summary.total == 0 and stdout_summary:
        summary.passed = stdout_summary.get("passed", 0)
        summary.failed = stdout_summary.get("failed", 0)
        summary.errors = stdout_summary.get("errors", 0)
        summary.skipped = stdout_summary.get("skipped", 0)
        summary.xfailed = stdout_summary.get("xfailed", 0)
        summary.xpassed = stdout_summary.get("xpassed", 0)
        summary.total = sum(stdout_summary.values())

    report.summary = summary

    # 5. Determine overall ExecutionStatus
    if exec_result.timed_out:
        report.status = ExecutionStatus.TIMEOUT
        report.errors.append(exec_result.error_detail or "Test execution timed out.")
        report.success = False
    elif exec_result.exit_code == 0:
        report.status = ExecutionStatus.PASSED
        report.success = True
    elif exec_result.exit_code == 1:
        # Pytest code 1 = tests were collected and run, but some failed
        report.status = ExecutionStatus.TEST_FAILURES
        report.success = True  # target tests failing is a normal test execution outcome
    elif exec_result.exit_code == 2:
        # Pytest code 2 = interrupted, usually collection error
        combined_lower = exec_result.combined_output.lower()
        if "error during collection" in combined_lower or "collection failure" in combined_lower or "errors" in combined_lower:
            report.status = ExecutionStatus.COLLECTION_ERROR
            report.errors.append("Pytest collection error occurred.")
        else:
            report.status = ExecutionStatus.ERROR
            report.errors.append("Pytest execution was interrupted.")
        report.success = False
    elif exec_result.exit_code == 5:
        # Pytest code 5 = no tests collected
        report.status = ExecutionStatus.NO_TESTS
        report.success = True
    elif exec_result.exit_code in (3, 4):
        report.status = ExecutionStatus.ENVIRONMENT_ERROR
        report.errors.append(f"Pytest exited with error code {exec_result.exit_code}.")
        report.success = False
    else:
        if report.summary.failed > 0:
            report.status = ExecutionStatus.TEST_FAILURES
            report.success = True
        else:
            report.status = ExecutionStatus.ERROR
            report.errors.append(exec_result.error_detail or f"Unknown execution failure (exit code {exec_result.exit_code}).")
            report.success = False

    # 6. Parse coverage if attempted
    if attempted_coverage:
        if cov_json_path.exists():
            try:
                report.coverage = _parse_coverage_json(
                    cov_json_path.read_text(encoding="utf-8", errors="replace"),
                    repo_path=repo_path,
                )
            except Exception as exc:  # noqa: BLE001
                report.warnings.append(f"Failed to parse coverage JSON: {exc}")
                report.coverage = _parse_coverage_stdout(exec_result.combined_output)
        else:
            report.coverage = _parse_coverage_stdout(exec_result.combined_output)

        if report.coverage.coverage_pct is not None:
            if report.status == ExecutionStatus.TEST_FAILURES:
                report.coverage.status = CoverageStatus.TESTS_FAILED
            else:
                report.coverage.status = CoverageStatus.COLLECTED
        else:
            report.coverage.status = CoverageStatus.EXECUTION_ERROR
            report.coverage.error_detail = "Coverage JSON not generated and could not parse stdout."


# ---------------------------------------------------------------------------
# JUnit XML parser
# ---------------------------------------------------------------------------

def _parse_junit_xml(xml_content: str, repo_path: Path) -> list[TestCaseResultItem]:
    """Parse JUnit XML string into structured TestCaseResultItem objects."""
    results: list[TestCaseResultItem] = []
    if not xml_content.strip():
        return results

    root = ET.fromstring(xml_content)

    for tc in root.iter("testcase"):
        classname = tc.get("classname", "")
        name = tc.get("name", "")
        file_attr = tc.get("file", "")
        time_attr = tc.get("time")

        duration: float | None = None
        if time_attr:
            try:
                duration = round(float(time_attr), 4)
            except ValueError:
                duration = None

        status = TestStatus.PASSED
        failure_msg = ""
        failure_type = ""
        traceback = ""

        # Check for child elements: failure, error, skipped
        failure_elem = tc.find("failure")
        error_elem = tc.find("error")
        skipped_elem = tc.find("skipped")

        if failure_elem is not None:
            status = TestStatus.FAILED
            raw_msg = failure_elem.get("message", "")
            raw_type = failure_elem.get("type", "")
            raw_tb = (failure_elem.text or "").strip()
            failure_type, failure_msg, traceback = _extract_failure_info(raw_msg, raw_tb, raw_type)
        elif error_elem is not None:
            status = TestStatus.ERROR
            raw_msg = error_elem.get("message", "")
            raw_type = error_elem.get("type", "")
            raw_tb = (error_elem.text or "").strip()
            failure_type, failure_msg, traceback = _extract_failure_info(raw_msg, raw_tb, raw_type)
        elif skipped_elem is not None:
            skip_type = skipped_elem.get("type", "")
            if skip_type in ("pytest.xfail", "xfail"):
                status = TestStatus.XFAILED
            else:
                status = TestStatus.SKIPPED
            failure_msg = skipped_elem.get("message", "") or (skipped_elem.text or "").strip()

        # Build nodeid and relative file path
        file_path, nodeid = _build_nodeid_from_xml(classname, name, file_attr, repo_path)

        results.append(
            TestCaseResultItem(
                nodeid=nodeid,
                name=name,
                file=file_path,
                classname=classname,
                status=status,
                duration_seconds=duration,
                failure_type=failure_type,
                failure_message=failure_msg,
                traceback=traceback[:_MAX_TRACEBACK_LENGTH],
            )
        )

    return results


def _build_nodeid_from_xml(
    classname: str, name: str, file_attr: str, repo_path: Path
) -> tuple[str, str]:
    """
    Construct canonical repository-relative file path and pytest nodeid.
    """
    # 1. If file_attr is provided by xunit2 (e.g. tests/test_calc.py or absolute)
    if file_attr:
        fpath = Path(file_attr)
        if fpath.is_absolute():
            try:
                rel_file = str(fpath.relative_to(repo_path)).replace("\\", "/")
            except ValueError:
                rel_file = str(fpath).replace("\\", "/")
        else:
            rel_file = str(fpath).replace("\\", "/")

        # Check if classname contains an inner class
        class_parts = classname.split(".")
        if class_parts and class_parts[-1] and class_parts[-1][0].isupper():
            nodeid = f"{rel_file}::{class_parts[-1]}::{name}"
        else:
            nodeid = f"{rel_file}::{name}"
        return rel_file, nodeid

    # 2. Derive file path from classname (e.g. tests.test_arithmetic.TestAdd)
    parts = classname.split(".") if classname else []
    if not parts:
        return "", name

    class_name = ""
    if len(parts) >= 2 and parts[-1] and parts[-1][0].isupper():
        class_name = parts[-1]
        file_parts = parts[:-1]
    else:
        file_parts = parts

    rel_file = "/".join(file_parts)
    if not rel_file.endswith(".py"):
        rel_file += ".py"

    nodeid = f"{rel_file}::{class_name}::{name}" if class_name else f"{rel_file}::{name}"
    return rel_file, nodeid



def _extract_failure_info(
    raw_msg: str, raw_tb: str, raw_type: str = ""
) -> tuple[str, str, str]:
    """
    Extract structured (failure_type, short_message, traceback_excerpt)
    without attempting root-cause failure analysis.
    """
    failure_type = raw_type
    short_msg = raw_msg

    # If failure_type not explicitly given, look for ExceptionName:
    if not failure_type:
        m = re.search(r"([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Failure|Interrupt|Warning))", raw_msg)
        if m:
            failure_type = m.group(1)

    if not failure_type and raw_tb:
        # Search traceback from bottom up
        for line in reversed(raw_tb.splitlines()):
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Failure|Interrupt|Warning))(?::\s*(.*))?$", line.strip())
            if m:
                failure_type = m.group(1)
                if not short_msg and m.group(2):
                    short_msg = m.group(2).strip()
                break

    # Extract short first-line message
    if short_msg:
        # Take first non-empty line
        lines = [line.strip() for line in short_msg.splitlines() if line.strip()]
        if lines:
            first_line = lines[0]
            # Strip redundant 'AssertionError: ' prefix if already captured
            if failure_type and first_line.startswith(f"{failure_type}:"):
                first_line = first_line[len(failure_type) + 1:].strip()
            short_msg = first_line

    return failure_type, short_msg, raw_tb


# ---------------------------------------------------------------------------
# Pytest stdout parser
# ---------------------------------------------------------------------------

_STDOUT_SUMMARY_RE = re.compile(
    r"^([A-Z]+)\s+([^\s\-]+)(?:\s+-\s+(.*))?$", re.MULTILINE
)


def _parse_stdout_tests(output: str) -> tuple[list[TestCaseResultItem], dict[str, int]]:
    """
    Parse test items and summary counters from pytest terminal output.
    """
    tests: list[TestCaseResultItem] = []
    summary_counts: dict[str, int] = {}

    # 1. Parse individual lines from the 'short test summary info' block
    summary_start = output.find("short test summary info")
    if summary_start != -1:
        block = output[summary_start:]
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith("=") or line.startswith("!"):
                continue

            status_str, _, remainder = line.partition(" ")
            remainder = remainder.strip()
            status_map = {
                "PASSED": TestStatus.PASSED,
                "FAILED": TestStatus.FAILED,
                "ERROR": TestStatus.ERROR,
                "SKIPPED": TestStatus.SKIPPED,
                "XFAIL": TestStatus.XFAILED,
                "XPASS": TestStatus.XPASSED,
            }
            if status_str not in status_map:
                continue

            test_status = status_map[status_str]
            # Remainder can be 'tests/test_x.py::test_foo - message' or 'tests/test_x.py::test_foo'
            nodeid = remainder
            msg = ""
            if " - " in remainder:
                nodeid, _, msg = remainder.partition(" - ")
                nodeid = nodeid.strip()
                msg = msg.strip()
            elif status_str == "SKIPPED" and remainder.startswith("["):
                # Pytest summary format: 'SKIPPED [1] file:line: reason'
                # This is a location counter, not a test nodeid; ignore it.
                continue

            nodeid = nodeid.replace("\\", "/")
            file_part = nodeid.split("::")[0] if "::" in nodeid else ""
            name_part = nodeid.split("::")[-1] if "::" in nodeid else nodeid

            tests.append(
                TestCaseResultItem(
                    nodeid=nodeid,
                    name=name_part,
                    file=file_part,
                    status=test_status,
                    failure_message=msg,
                )
            )

    # 2. Extract final counters line: e.g. "1 failed, 28 passed, 1 skipped in 0.42s"
    m_pass = re.search(r"(\d+)\s+passed", output)
    if m_pass:
        summary_counts["passed"] = int(m_pass.group(1))

    m_fail = re.search(r"(\d+)\s+failed", output)
    if m_fail:
        summary_counts["failed"] = int(m_fail.group(1))

    m_err = re.search(r"(\d+)\s+errors?", output)
    if m_err:
        summary_counts["errors"] = int(m_err.group(1))

    m_skip = re.search(r"(\d+)\s+skipped", output)
    if m_skip:
        summary_counts["skipped"] = int(m_skip.group(1))

    m_xfail = re.search(r"(\d+)\s+xfailed", output)
    if m_xfail:
        summary_counts["xfailed"] = int(m_xfail.group(1))

    m_xpass = re.search(r"(\d+)\s+xpassed", output)
    if m_xpass:
        summary_counts["xpassed"] = int(m_xpass.group(1))

    return tests, summary_counts


def _merge_test_records(
    xml_tests: list[TestCaseResultItem], stdout_tests: list[TestCaseResultItem]
) -> list[TestCaseResultItem]:
    """
    Merge XML test cases with stdout test cases to get the best of both:
    exact duration/traceback from XML, and exact nodeid/xpass status from stdout.
    """
    if not stdout_tests:
        return xml_tests
    if not xml_tests:
        return [st for st in stdout_tests if "::" in st.nodeid or not st.nodeid.startswith("[")]

    # Map stdout tests by nodeid and by name for matching
    stdout_by_nodeid = {t.nodeid: t for t in stdout_tests}
    stdout_by_name = {t.name: t for t in stdout_tests}

    merged: list[TestCaseResultItem] = []
    matched_stdout_nodeids: set[str] = set()

    for xt in xml_tests:
        # Match by nodeid first
        st = stdout_by_nodeid.get(xt.nodeid)
        if st is None:
            # Match by function name
            st = stdout_by_name.get(xt.name)

        if st is not None:
            matched_stdout_nodeids.add(st.nodeid)
            # Use canonical nodeid and file from stdout if available
            canonical_nodeid = st.nodeid if "::" in st.nodeid else xt.nodeid
            canonical_file = st.file if st.file else xt.file
            # XPASS appears as passed in basic xunit XML, take XPASS from stdout
            final_status = st.status if st.status in (TestStatus.XPASSED, TestStatus.XFAILED) else xt.status

            merged.append(
                TestCaseResultItem(
                    nodeid=canonical_nodeid,
                    name=xt.name,
                    file=canonical_file,
                    classname=xt.classname,
                    status=final_status,
                    duration_seconds=xt.duration_seconds,
                    failure_type=xt.failure_type or st.failure_type,
                    failure_message=xt.failure_message or st.failure_message,
                    traceback=xt.traceback,
                )
            )
        else:
            merged.append(xt)

    # Append any remaining stdout tests not in XML (e.g. collection error items)
    for st in stdout_tests:
        if (
            st.nodeid not in matched_stdout_nodeids
            and st.name not in {m.name for m in merged}
            and "::" in st.nodeid
            and not st.nodeid.startswith("[")
        ):
            merged.append(st)

    return merged



# ---------------------------------------------------------------------------
# Coverage parsers
# ---------------------------------------------------------------------------

def _parse_coverage_json(json_content: str, repo_path: Path) -> ExecutionCoverage:
    """Parse JSON coverage report produced by --cov-report=json:<path>."""
    cov = ExecutionCoverage()
    data = json.loads(json_content)

    totals = data.get("totals", {})
    if totals:
        cov.coverage_pct = round(float(totals.get("percent_covered", 0.0)), 2)
        cov.lines_covered = totals.get("covered_lines")
        cov.lines_total = totals.get("num_statements")

    files = data.get("files", {})
    missing_map: dict[str, list[int]] = {}
    for path_str, file_data in files.items():
        try:
            rel = str(Path(path_str).relative_to(repo_path)).replace("\\", "/")
        except ValueError:
            rel = str(Path(path_str)).replace("\\", "/")

        missing_lines = file_data.get("missing_lines", [])
        if missing_lines:
            missing_map[rel] = missing_lines

    cov.missing_lines_by_file = missing_map
    cov.status = CoverageStatus.COLLECTED
    return cov


def _parse_coverage_stdout(output: str) -> ExecutionCoverage:
    """Fallback parser: extract total coverage percentage from terminal table."""
    cov = ExecutionCoverage()

    # Look for pytest-cov summary line: "TOTAL <stmts> <miss> <cover>%"
    m = re.search(r"^TOTAL\s+(\d+)\s+(\d+)\s+(\d+(?:\.\d+)?)%", output, re.MULTILINE)
    if m:
        stmts = int(m.group(1))
        miss = int(m.group(2))
        pct = float(m.group(3))
        cov.lines_total = stmts
        cov.lines_covered = stmts - miss
        cov.coverage_pct = round(pct, 2)
        cov.status = CoverageStatus.COLLECTED
        return cov

    # Look for "Total coverage: 65.0%"
    m2 = re.search(r"[Tt]otal\s+coverage[:\s]+(\d+(?:\.\d+)?)%", output)
    if m2:
        cov.coverage_pct = round(float(m2.group(1)), 2)
        cov.status = CoverageStatus.COLLECTED
        return cov

    cov.status = CoverageStatus.UNAVAILABLE
    cov.error_detail = "No coverage summary found in test output."
    return cov
