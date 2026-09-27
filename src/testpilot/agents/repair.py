"""
Failure Analysis and Repair Agents for TestPilot AI.

Implements the automated failure diagnosis and iterative repair workflow:
  Generated Test -> Execute -> Detect Failure -> Analyze Failure -> Repair Test -> Re-execute

Design rules:
  - Reuses BaseAgent and SessionContext abstractions.
  - Reuses BaseLLMClient and LLMClientFactory for provider-agnostic inference.
  - Reuses extract_test_code_and_explanation and validate_generated_code from generator.
  - Distinguishes generated-test defects from genuine source-code bugs.
  - Strictly enforces bounded loop iterations (default 2, maximum 5).
  - Never overwrites human tests or silently accepts broken code.
"""

from __future__ import annotations

import difflib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from testpilot.agents.base import AgentResult, BaseAgent
from testpilot.agents.executor import execute_tests
from testpilot.agents.generator import (
    extract_test_code_and_explanation,
    validate_generated_code,
)
from testpilot.models.repair import (
    FailureAnalysis,
    FailureCategory,
    RepairAttemptRecord,
    RepairReport,
    RepairStatus,
)
from testpilot.session_context import PipelineStep, RepairAttempt
from testpilot.utils.logging import get_logger

if TYPE_CHECKING:
    from testpilot.config import Settings
    from testpilot.llm.client import BaseLLMClient, LLMMessage
    from testpilot.models.execution import ExecutionReport, TestCaseResultItem
    from testpilot.session_context import SessionContext

_log = get_logger("testpilot.agents.repair")

_MAX_CODE_CONTEXT_BYTES = 16384
_MAX_TRACEBACK_BYTES = 4096


# ---------------------------------------------------------------------------
# Classification & Analysis Helpers
# ---------------------------------------------------------------------------

def classify_failure_heuristically(
    failure_type: str,
    failure_message: str,
    traceback_str: str,
) -> tuple[FailureCategory, str, bool]:
    """
    Rule-based diagnostic fallback for common pytest failure patterns.

    Returns
    -------
    tuple[FailureCategory, str, bool]
        (category, explanation, is_repairable_at_test_level)
    """
    ftype = (failure_type or "").strip()
    fmsg = (failure_message or "").strip().lower()
    tb = (traceback_str or "").strip().lower()
    combined = f"{ftype} {fmsg} {tb}"

    # Missing imports or fixtures
    if ftype in ("NameError", "ImportError", "ModuleNotFoundError") or "fixture" in fmsg and "not found" in fmsg:
        return (
            FailureCategory.MISSING_FIXTURE_IMPORT_SETUP,
            f"Test failed due to an unresolved reference or missing dependency ({ftype or 'import/fixture issue'}).",
            True,
        )

    # Syntax or indentation errors in generated test
    if ftype in ("SyntaxError", "IndentationError", "TabError"):
        return (
            FailureCategory.GENERATED_TEST_ISSUE,
            f"The generated test code contains invalid Python syntax: {failure_message}",
            True,
        )

    # Wrong type arguments passed in test call
    if ftype == "TypeError" and ("unexpected keyword argument" in combined or "missing required positional argument" in combined):
        return (
            FailureCategory.GENERATED_TEST_ISSUE,
            f"Test calls function with incorrect parameters or signature: {failure_message}",
            True,
        )

    # Value assertion mismatch
    if ftype == "AssertionError" or "assert " in combined:
        return (
            FailureCategory.INCORRECT_EXPECTATION,
            "Assertion failed: the test expectation did not match the actual return value or behavior.",
            True,
        )

    # Unhandled exception inside source function (e.g. ZeroDivisionError, IndexError)
    if ftype in ("ZeroDivisionError", "IndexError", "KeyError", "AttributeError", "ValueError"):
        # If the test did not use pytest.raises when testing invalid input, it's a test issue
        if "pytest.raises" not in tb:
            return (
                FailureCategory.INCORRECT_EXPECTATION,
                f"Test encountered unhandled {ftype}. If testing an error case, it should wrap the call in pytest.raises({ftype}).",
                True,
            )
        return (
            FailureCategory.SOURCE_CODE_DEFECT,
            f"Source code raised unexpected {ftype}: {failure_message}",
            False,
        )

    # Environment/subprocess issues
    if "permission denied" in combined or "timeout" in combined or "file not found" in combined:
        return (
            FailureCategory.ENVIRONMENT_DEPENDENCY_ISSUE,
            "Environment or filesystem issue encountered during execution.",
            False,
        )

    return (
        FailureCategory.UNKNOWN,
        f"Unclassified failure ({ftype}): {failure_message[:200]}",
        True,
    )


def analyze_failure_with_llm(
    test_item: TestCaseResultItem,
    test_code: str,
    source_code: str,
    llm_client: BaseLLMClient,
    settings: Settings | None = None,
) -> FailureAnalysis:
    """
    Use LLM to diagnose the root cause of a failing test case.

    Falls back to heuristic classification if the LLM call fails or returns
    an unparseable response.
    """
    from testpilot.llm.client import LLMMessage

    # Compute heuristic default as baseline
    h_cat, h_exp, h_rep = classify_failure_heuristically(
        test_item.failure_type,
        test_item.failure_message,
        test_item.traceback,
    )

    system_prompt = (
        "You are an expert automated testing diagnostician.\n"
        "Analyze the following pytest test failure against the source code under test.\n"
        "Classify the failure into exactly ONE category from:\n"
        "- generated_test_issue: The test has a defect (bad syntax, wrong call parameters, bad type)\n"
        "- incorrect_expectation: The test asserted an incorrect expected value or forgot pytest.raises\n"
        "- missing_fixture_import_setup: Missing import, missing fixture, or uninitialized setup\n"
        "- source_code_defect: The test exposed a genuine bug in the target source code\n"
        "- environment_dependency_issue: Missing system dependency, path issue, or environment problem\n"
        "- unknown: Cannot be determined\n\n"
        "Output ONLY valid JSON with keys: 'category', 'is_repairable_at_test_level' (boolean), "
        "'explanation' (string), 'suggested_fix' (string)."
    )

    user_prompt = (
        f"Failing test: `{test_item.nodeid}`\n"
        f"Failure type: `{test_item.failure_type}`\n"
        f"Failure message: {test_item.failure_message}\n\n"
        f"Traceback excerpt:\n```\n{test_item.traceback[:_MAX_TRACEBACK_BYTES]}\n```\n\n"
        f"Test file code:\n```python\n{test_code[:_MAX_CODE_CONTEXT_BYTES]}\n```\n\n"
        f"Source code under test:\n```python\n{source_code[:_MAX_CODE_CONTEXT_BYTES]}\n```\n"
    )

    temp = settings.llm_temperature if settings else 0.1
    try:
        resp = llm_client.chat(
            [LLMMessage(role="system", content=system_prompt), LLMMessage(role="user", content=user_prompt)],
            temperature=temp,
            max_tokens=1024,
        )
        content = resp.content.strip()
        # Parse JSON from response
        if "{" in content and "}" in content:
            start = content.find("{")
            end = content.rfind("}") + 1
            data = json.loads(content[start:end])
            raw_cat = data.get("category", "").lower()
            try:
                cat = FailureCategory(raw_cat)
            except ValueError:
                cat = h_cat
            return FailureAnalysis(
                test_nodeid=test_item.nodeid,
                category=cat,
                is_repairable_at_test_level=bool(data.get("is_repairable_at_test_level", h_rep)),
                explanation=str(data.get("explanation", h_exp)),
                suggested_fix=str(data.get("suggested_fix", "")),
                root_cause=f"{test_item.failure_type}: {test_item.failure_message}",
                failure_type=test_item.failure_type,
                failure_message=test_item.failure_message,
            )
    except Exception as exc:  # noqa: BLE001
        _log.warning("LLM failure analysis error, falling back to heuristic: %s", exc)

    return FailureAnalysis(
        test_nodeid=test_item.nodeid,
        category=h_cat,
        is_repairable_at_test_level=h_rep,
        explanation=h_exp,
        suggested_fix="",
        root_cause=f"{test_item.failure_type}: {test_item.failure_message}",
        failure_type=test_item.failure_type,
        failure_message=test_item.failure_message,
    )


# ---------------------------------------------------------------------------
# Test Repair Prompting
# ---------------------------------------------------------------------------

def generate_unified_diff(original: str, repaired: str, filename: str = "test_file.py") -> str:
    """Generate a clean unified diff between original and repaired code."""
    orig_lines = original.splitlines(keepends=True)
    rep_lines = repaired.splitlines(keepends=True)
    diff = difflib.unified_diff(
        orig_lines,
        rep_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )
    return "".join(diff)


def build_repair_prompt(
    test_code: str,
    source_code: str,
    analyses: list[FailureAnalysis],
    test_file_rel: str,
) -> list[LLMMessage]:
    """Construct structured messages instructing the LLM to fix failing tests."""
    from testpilot.llm.client import LLMMessage

    system_prompt = (
        "You are an expert Python test repair engineer.\n"
        "Your task is to repair failing pytest tests in the provided test file.\n"
        "Rules:\n"
        "1. Fix the failing assertions, wrong parameters, missing imports, or unhandled exceptions.\n"
        "2. Do NOT delete or comment out tests to fake passing. Fix them properly.\n"
        "3. Preserve all existing tests that are already working correctly.\n"
        "4. Enclose your complete, runnable, updated Python test file in a single ```python ... ``` block.\n"
        "5. Output valid Python code with NO placeholders or ellipses (...)."
    )

    failures_desc = []
    for a in analyses:
        failures_desc.append(
            f"- Test: `{a.test_nodeid}`\n"
            f"  Category: {a.category.value}\n"
            f"  Diagnosis: {a.explanation}\n"
            f"  Suggested fix: {a.suggested_fix or 'Adjust assertion/call to match module specification.'}"
        )

    user_prompt = (
        f"Test file to repair: `{test_file_rel}`\n\n"
        f"Failures to resolve:\n" + "\n".join(failures_desc) + "\n\n"
        f"Current test file code:\n```python\n{test_code[:_MAX_CODE_CONTEXT_BYTES]}\n```\n\n"
        f"Source code under test:\n```python\n{source_code[:_MAX_CODE_CONTEXT_BYTES]}\n```\n\n"
        "Please provide the complete repaired Python test file in a ```python ... ``` block."
    )

    return [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content=user_prompt),
    ]


# ---------------------------------------------------------------------------
# Core Bounded Repair Loop
# ---------------------------------------------------------------------------

def run_repair_loop(
    repo_path: Path,
    test_file: Path | str | None = None,
    *,
    llm_client: BaseLLMClient | None = None,
    settings: Settings | None = None,
    max_iterations: int | None = None,
    write_to_disk: bool = True,
    run_id: str = "cli",
) -> RepairReport:
    """
    Execute tests, analyze failures, repair test code, and verify fixes in a bounded loop.

    Parameters
    ----------
    repo_path:
        Path to the repository root.
    test_file:
        Optional specific test file to focus repair on.
    llm_client:
        Configured BaseLLMClient. If None, loaded from settings.
    settings:
        Settings object for timeouts, LLM models, and iteration limits.
    max_iterations:
        Maximum repair cycles (defaults to settings.max_repair_iterations, e.g. 2).
    write_to_disk:
        Whether to overwrite test files with repaired code.
    run_id:
        Identifier for logging.

    Returns
    -------
    RepairReport
        Full summary of analyses, attempts, diffs, and outcomes.
    """
    start_time = time.monotonic()
    repo_path = repo_path.resolve()

    # Enforce bounded limit
    configured_max = max_iterations or (settings.max_repair_iterations if settings else 2)
    effective_max = min(max(1, configured_max), 5)

    report = RepairReport(
        repository_path=str(repo_path),
        test_file=str(test_file or ""),
        started_at=datetime.now(tz=UTC),
        max_iterations=effective_max,
    )

    # 1. Validate repository path
    if not repo_path.exists() or not repo_path.is_dir():
        msg = f"Repository path does not exist or is not a directory: {repo_path}"
        report.errors.append(msg)
        report.status = RepairStatus.VALIDATION_ERROR
        report.duration_seconds = round(time.monotonic() - start_time, 3)
        report.completed_at = datetime.now(tz=UTC)
        return report

    # 2. Ensure LLM client
    if llm_client is None:
        from testpilot.llm.client import LLMClientFactory

        llm_client = LLMClientFactory.from_settings(settings)

    # 3. Initial test execution
    timeout = settings.test_execution_timeout if settings else 30.0
    _log.info("Running initial test execution for repair check in %s", repo_path)
    initial_exec: ExecutionReport = execute_tests(
        repo_path=repo_path,
        settings=settings,
        timeout=timeout,
        run_id=run_id,
    )

    if not initial_exec.has_failures:
        _log.info("No test failures detected. No repair required.")
        report.status = RepairStatus.NO_FAILURES
        report.duration_seconds = round(time.monotonic() - start_time, 3)
        report.completed_at = datetime.now(tz=UTC)
        return report

    report.initial_failures = list(initial_exec.failed_tests)
    report.final_failures = list(initial_exec.failed_tests)
    current_failed_items = list(initial_exec.failed_test_items)
    current_failed_tests = list(initial_exec.failed_tests)

    # Resolve target test file
    target_test_path: Path | None = None
    if test_file:
        tf = Path(test_file)
        target_test_path = tf if tf.is_absolute() else (repo_path / tf).resolve()
    elif current_failed_items and current_failed_items[0].file:
        target_test_path = (repo_path / current_failed_items[0].file).resolve()

    if not target_test_path or not target_test_path.exists():
        msg = f"Could not locate failing test file: {target_test_path}"
        report.errors.append(msg)
        report.status = RepairStatus.ERROR
        report.duration_seconds = round(time.monotonic() - start_time, 3)
        report.completed_at = datetime.now(tz=UTC)
        return report

    test_file_rel = str(target_test_path.relative_to(repo_path)).replace("\\", "/")
    report.test_file = test_file_rel

    # Try to locate corresponding source code
    source_code = _find_source_code_for_test(repo_path, target_test_path)

    # 4. Bounded repair loop
    iteration = 0
    while iteration < effective_max:
        iteration += 1
        iter_start = time.monotonic()
        report.iterations_run = iteration
        _log.info("Starting repair iteration %d/%d for %s", iteration, effective_max, test_file_rel)

        # Read current test code
        try:
            current_test_code = target_test_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            msg = f"Failed to read test file '{target_test_path}': {exc}"
            report.errors.append(msg)
            report.status = RepairStatus.ERROR
            break

        # A. Analyze failures
        iter_analyses: list[FailureAnalysis] = []
        for fi in current_failed_items:
            # Analyze failures relevant to this test file
            if not fi.file or fi.file == test_file_rel or test_file_rel in fi.nodeid:
                analysis = analyze_failure_with_llm(
                    test_item=fi,
                    test_code=current_test_code,
                    source_code=source_code,
                    llm_client=llm_client,
                    settings=settings,
                )
                iter_analyses.append(analysis)

        if not iter_analyses:
            # Fall back to analyzing all failed items
            for fi in current_failed_items:
                analysis = analyze_failure_with_llm(
                    test_item=fi,
                    test_code=current_test_code,
                    source_code=source_code,
                    llm_client=llm_client,
                    settings=settings,
                )
                iter_analyses.append(analysis)

        report.analyses.extend(iter_analyses)

        # B. Check repairability
        repairable = [a for a in iter_analyses if a.is_repairable_at_test_level]
        if not repairable:
            _log.info("None of the failures are repairable at test level (source defect or environment).")
            report.status = RepairStatus.NOT_REPAIRABLE
            report.final_failures = list(current_failed_tests)
            break

        # C. Request repaired test code from LLM
        prompt_messages = build_repair_prompt(
            test_code=current_test_code,
            source_code=source_code,
            analyses=repairable,
            test_file_rel=test_file_rel,
        )

        try:
            llm_resp = llm_client.chat(
                prompt_messages,
                temperature=settings.llm_temperature if settings else 0.2,
                max_tokens=settings.llm_max_tokens if settings else 4096,
            )
            repaired_code_raw, _ = extract_test_code_and_explanation(llm_resp.content)
        except Exception as exc:  # noqa: BLE001
            msg = f"LLM error during test repair: {exc}"
            report.errors.append(msg)
            report.status = RepairStatus.LLM_ERROR
            report.final_failures = list(current_failed_tests)
            break

        # D. Validate repaired code via AST
        is_valid, test_cases, val_error = validate_generated_code(repaired_code_raw)

        diff_str = generate_unified_diff(current_test_code, repaired_code_raw, test_file_rel)
        attempt_rec = RepairAttemptRecord(
            iteration=iteration,
            test_file=test_file_rel,
            original_failures=current_failed_tests,
            analyses=iter_analyses,
            repaired_code=repaired_code_raw if is_valid else "",
            patch_diff=diff_str,
            is_ast_valid=is_valid,
            validation_error=val_error,
            duration_seconds=round(time.monotonic() - iter_start, 3),
        )

        if not is_valid:
            _log.warning("Candidate repaired code failed AST validation: %s", val_error)
            attempt_rec.validation_error = val_error
            report.attempts.append(attempt_rec)
            report.status = RepairStatus.VALIDATION_FAILED
            report.final_failures = list(current_failed_tests)
            continue

        # E. Apply repair to disk if requested
        if write_to_disk:
            try:
                target_test_path.write_text(repaired_code_raw, encoding="utf-8")
                if test_file_rel not in report.repaired_files:
                    report.repaired_files.append(test_file_rel)
                _log.info("Applied repaired test code to %s", target_test_path)
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"Failed to write repaired test file: {exc}")
                report.status = RepairStatus.ERROR
                report.attempts.append(attempt_rec)
                report.final_failures = list(current_failed_tests)
                break

        # F. Re-execute tests to verify fix
        _log.info("Re-executing test suite to verify repair...")
        re_exec: ExecutionReport = execute_tests(
            repo_path=repo_path,
            settings=settings,
            timeout=timeout,
            run_id=run_id,
        )

        attempt_rec.remaining_failures = list(re_exec.failed_tests)
        attempt_rec.re_execution_passed = not re_exec.has_failures
        report.attempts.append(attempt_rec)

        if not re_exec.has_failures:
            _log.info("All tests passed on iteration %d! Repair successful.", iteration)
            report.status = RepairStatus.SUCCESS
            report.final_failures = []
            break

        # Failures remain: update state for next iteration
        current_failed_tests = list(re_exec.failed_tests)
        current_failed_items = list(re_exec.failed_test_items)
        report.final_failures = current_failed_tests
        report.status = RepairStatus.MAX_ITERATIONS_EXCEEDED

    # Post-loop status determination
    if report.status not in (
        RepairStatus.SUCCESS,
        RepairStatus.NOT_REPAIRABLE,
        RepairStatus.VALIDATION_FAILED,
        RepairStatus.LLM_ERROR,
        RepairStatus.VALIDATION_ERROR,
        RepairStatus.MAX_ITERATIONS_EXCEEDED,
    ):
        if report.resolved:
            report.status = RepairStatus.SUCCESS
        elif report.attempts:
            report.status = RepairStatus.MAX_ITERATIONS_EXCEEDED
        else:
            report.status = RepairStatus.ERROR

    report.duration_seconds = round(time.monotonic() - start_time, 3)
    report.completed_at = datetime.now(tz=UTC)
    return report


def _find_source_code_for_test(repo_path: Path, test_path: Path) -> str:
    """Locate the target source file corresponding to a given test file."""
    stem = test_path.stem
    # Remove standard test prefixes
    for prefix in ("test_testpilot_", "test_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break

    # Look for matching .py file in repo
    candidates = list(repo_path.glob(f"**/{stem}.py"))
    for c in candidates:
        if "tests" not in c.parts and ".venv" not in c.parts:
            try:
                return c.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass

    return ""


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

class FailureAnalysisAgent(BaseAgent):
    """
    Failure analysis agent in the TestPilot AI pipeline.

    Diagnoses test failures recorded in SessionContext.execution_report and
    classifies them into structured categories with root-cause explanations.
    """

    def __init__(self, llm_client: BaseLLMClient, settings: Settings) -> None:
        super().__init__(llm_client, settings)
        self._log = get_logger("testpilot.agents.failure_analyst")

    @property
    def name(self) -> str:
        return "failure_analyst"

    def run(self, context: SessionContext) -> AgentResult:
        self._log_start(context)

        if context.repo_path is None:
            msg = "SessionContext.repo_path is not set; cannot analyze failures."
            context.errors.append(msg)
            return AgentResult(success=False, context=context, message=msg, errors=[msg])

        if context.execution_report is None or not context.execution_report.has_failures:
            msg = "No test failures found in context.execution_report to analyze."
            return AgentResult(success=True, context=context, message=msg)

        context.current_step = PipelineStep.FAILURE_ANALYSIS
        repo_path = Path(context.repo_path).resolve()
        failed_items = context.execution_report.failed_test_items

        analyses: list[FailureAnalysis] = []
        for fi in failed_items:
            test_file = (repo_path / fi.file).resolve() if fi.file else None
            test_code = test_file.read_text(encoding="utf-8", errors="replace") if test_file and test_file.exists() else ""
            source_code = _find_source_code_for_test(repo_path, test_file) if test_file else ""

            analysis = analyze_failure_with_llm(
                test_item=fi,
                test_code=test_code,
                source_code=source_code,
                llm_client=self._llm,
                settings=self._settings,
            )
            analyses.append(analysis)

        # Store in repair_report if available or create partial report
        if context.repair_report is None:
            context.repair_report = RepairReport(
                repository_path=str(repo_path),
                initial_failures=context.execution_report.failed_tests,
                analyses=analyses,
            )
        else:
            context.repair_report.analyses = analyses

        msg = f"Analyzed {len(analyses)} test failure(s)."
        self._log_finish(context, AgentResult(success=True, context=context, message=msg))
        return AgentResult(success=True, context=context, message=msg)


class RepairAgent(BaseAgent):
    """
    Repair agent in the TestPilot AI pipeline.

    Orchestrates the bounded failure analysis -> test repair -> re-validation loop.
    Updates SessionContext with repair attempts and re-execution reports.
    """

    def __init__(self, llm_client: BaseLLMClient, settings: Settings) -> None:
        super().__init__(llm_client, settings)
        self._log = get_logger("testpilot.agents.repairer")

    @property
    def name(self) -> str:
        return "repairer"

    def run(self, context: SessionContext) -> AgentResult:
        self._log_start(context)

        if context.repo_path is None:
            msg = "SessionContext.repo_path is not set; cannot repair tests."
            context.errors.append(msg)
            return AgentResult(success=False, context=context, message=msg, errors=[msg])

        repo_path = Path(context.repo_path).resolve()
        context.current_step = PipelineStep.REPAIR

        # Run bounded repair loop
        report = run_repair_loop(
            repo_path=repo_path,
            llm_client=self._llm,
            settings=self._settings,
            max_iterations=self._settings.max_repair_iterations if self._settings else 2,
            write_to_disk=True,
            run_id=context.run_id,
        )

        # Update SessionContext
        context.repair_report = report
        context.iteration_count = report.iterations_run

        for att in report.attempts:
            for analysis in att.analyses:
                context.repair_attempts.append(
                    RepairAttempt(
                        iteration=att.iteration,
                        target_test_id=analysis.test_nodeid,
                        patch_file="",
                        rationale=analysis.explanation,
                        applied=att.is_ast_valid,
                        resolved=att.re_execution_passed,
                    )
                )

        if report.resolved:
            context.current_step = PipelineStep.COMPLETE
            msg = (
                f"Repair succeeded in {report.iterations_run} iteration(s). "
                f"All tests passing."
            )
            res = AgentResult(success=True, context=context, message=msg)
        else:
            context.current_step = PipelineStep.FAILED
            msg = (
                f"Repair finished with status '{report.status.value}' after "
                f"{report.iterations_run} iteration(s). Remaining failures: {len(report.final_failures)}."
            )
            res = AgentResult(success=False, context=context, message=msg, errors=report.errors)

        self._log_finish(context, res)
        return res
