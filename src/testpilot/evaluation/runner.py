"""
Evaluation and benchmarking runner for TestPilot AI.

Executes and measures the full end-to-end TestPilot pipeline:
  Analyze -> Generate -> Execute -> Repair -> Re-execute -> Metrics

Design rules:
  - Reuses existing agents (analyzer, generator, executor, repairer).
  - Never mutates the original benchmark repository (supports isolated execution).
  - Collects real, measurable metrics across every phase.
  - Measures coverage deltas when coverage is available.
  - Distinguishes genuine source code defects (safety gate) from test repairs.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from testpilot.agents.analyzer import analyze_repository
from testpilot.agents.executor import execute_tests
from testpilot.agents.generator import generate_tests
from testpilot.agents.repair import run_repair_loop
from testpilot.models.execution import ExecutionStatus
from testpilot.models.evaluation import (
    BenchmarkEvaluationResult,
    BenchmarkEvaluationStatus,
    SuiteEvaluationResult,
)
from testpilot.models.generation import GenerationStatus
from testpilot.models.repair import RepairStatus
from testpilot.utils.logging import get_logger

if TYPE_CHECKING:
    from testpilot.config import Settings
    from testpilot.llm.client import BaseLLMClient
    from testpilot.models.execution import ExecutionReport
    from testpilot.models.generation import GenerationReport
    from testpilot.models.repair import RepairReport

_log = get_logger("testpilot.evaluation")


def _find_default_target_module(repo_path: Path) -> Path | None:
    """Find a sensible default Python module to target in the repository."""
    src_dir = repo_path / "src"
    search_dir = src_dir if src_dir.is_dir() else repo_path

    # Look for candidate Python files that are not __init__.py, conftest.py, or tests
    candidates: list[Path] = []
    for py_file in search_dir.rglob("*.py"):
        rel = py_file.relative_to(repo_path)
        parts = rel.parts
        if (
            "tests" in parts
            or "test" in parts
            or ".venv" in parts
            or "venv" in parts
            or "__pycache__" in parts
            or py_file.name.startswith("__")
            or py_file.name.startswith("test_")
            or py_file.name == "conftest.py"
        ):
            continue
        candidates.append(py_file)

    if not candidates:
        return None

    # Prefer intentionally uncovered modules like converter.py if present
    for c in candidates:
        if "converter" in c.stem:
            return c

    return candidates[0]


def run_benchmark_evaluation(
    repo_path: Path | str,
    target_module: Path | str | None = None,
    *,
    llm_client: BaseLLMClient | None = None,
    settings: Settings | None = None,
    isolate: bool = True,
    write_to_disk: bool = True,
    max_repair_attempts: int | None = None,
    run_id: str = "eval",
) -> BenchmarkEvaluationResult:
    """
    Execute a full benchmark evaluation through the TestPilot pipeline.

    Measures:
      1. Repository analysis & gap detection
      2. Baseline test execution & coverage before
      3. Test generation & AST validation
      4. Post-generation test execution
      5. Failure analysis & iterative repair (if failures occur)
      6. Final test execution & coverage after

    Parameters
    ----------
    repo_path:
        Path to the repository to evaluate.
    target_module:
        Optional target source module. If None, chosen from coverage gaps or sources.
    llm_client:
        Configured LLM client. If None, instantiated from settings.
    settings:
        Settings instance for timeouts and provider configuration.
    isolate:
        If True, copies the repository to a temporary workspace so the original
        repository remains completely untouched and reproducible.
    write_to_disk:
        Whether generated and repaired test files are written into the workspace.
    max_repair_attempts:
        Maximum repair loop iterations (defaults to config).
    run_id:
        Identifier for logging.

    Returns
    -------
    BenchmarkEvaluationResult
        Structured evaluation metrics.
    """
    start_time = time.monotonic()
    source_repo_path = Path(repo_path).resolve()
    repo_name = source_repo_path.name

    result = BenchmarkEvaluationResult(
        benchmark_name=repo_name,
        repository_path=str(source_repo_path),
        started_at=datetime.now(tz=UTC),
    )

    if not source_repo_path.exists() or not source_repo_path.is_dir():
        msg = f"Repository path does not exist or is not a directory: {source_repo_path}"
        result.errors.append(msg)
        result.status = BenchmarkEvaluationStatus.VALIDATION_ERROR
        result.total_duration_seconds = round(time.monotonic() - start_time, 3)
        result.completed_at = datetime.now(tz=UTC)
        return result

    # Ensure LLM client
    if llm_client is None:
        from testpilot.llm.client import LLMClientFactory

        llm_client = LLMClientFactory.from_settings(settings)

    # Use a temporary directory for isolation if requested
    temp_dir_obj = None
    if isolate:
        temp_dir_obj = tempfile.TemporaryDirectory()
        work_repo = Path(temp_dir_obj.name) / repo_name
        shutil.copytree(
            source_repo_path,
            work_repo,
            ignore=shutil.ignore_patterns(
                ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"
            ),
        )
        _log.info("Running evaluation in isolated workspace: %s", work_repo)
    else:
        work_repo = source_repo_path

    try:
        # 1. Phase 1: Repository Analysis
        _log.info("Phase 1: Analyzing repository %s", work_repo)
        analysis = analyze_repository(work_repo, run_id=run_id, settings=settings)
        result.analysis_completed = True
        result.detected_framework = analysis.test_framework or "unknown"
        if analysis.coverage_gaps:
            result.gap_targets = [g.symbol_name or g.file for g in analysis.coverage_gaps]

        # 2. Phase 2: Initial Baseline Execution & Coverage
        _log.info("Phase 2: Running initial baseline test execution")
        initial_exec: ExecutionReport = execute_tests(
            work_repo,
            settings=settings,
            with_coverage=True,
            run_id=run_id,
        )
        result.initial_execution_status = initial_exec.status.value
        result.initial_passed = initial_exec.passed_count
        result.initial_failed = initial_exec.failed_count
        result.initial_execution_duration_seconds = initial_exec.duration_seconds
        result.coverage_before = initial_exec.coverage.coverage_pct

        # 3. Resolve target module
        target_path: Path | None = None
        if target_module:
            tm = Path(target_module)
            target_path = tm if tm.is_absolute() else (work_repo / tm).resolve()
        else:
            # Try uncovered files from analysis coverage gaps
            if analysis.coverage_gaps:
                for gap in analysis.coverage_gaps:
                    candidate = (work_repo / gap.file).resolve()
                    if candidate.exists() and candidate.is_file():
                        target_path = candidate
                        break
            if not target_path or not target_path.exists():
                target_path = _find_default_target_module(work_repo)

        if not target_path or not target_path.exists():
            msg = f"Could not determine valid target source module in {work_repo}"
            result.errors.append(msg)
            result.status = BenchmarkEvaluationStatus.VALIDATION_ERROR
            return result

        target_rel = str(target_path.relative_to(work_repo)).replace("\\", "/")
        result.target_module = target_rel

        # 4. Phase 3: Test Generation
        _log.info("Phase 3: Generating tests for %s", target_rel)
        gen_start = time.monotonic()
        gen_report: GenerationReport = generate_tests(
            work_repo,
            target_file=target_path,
            analysis=analysis,
            llm_client=llm_client,
            settings=settings,
            write_to_disk=write_to_disk,
            run_id=run_id,
        )
        result.generation_status = gen_report.status.value
        result.tests_generated = gen_report.total_tests_generated
        result.valid_generated_tests = sum(
            f.test_count for f in gen_report.generated_files if f.is_valid
        )
        result.generated_files = [f.file_path for f in gen_report.generated_files]
        result.generation_duration_seconds = gen_report.duration_seconds
        result.errors.extend(gen_report.errors)
        result.warnings.extend(gen_report.warnings)

        if gen_report.status not in (GenerationStatus.SUCCESS, GenerationStatus.SYNTAX_ERROR):
            result.status = BenchmarkEvaluationStatus.GENERATION_FAILED
            return result

        # 5. Phase 2: Post-Generation Execution
        _log.info("Phase 2: Executing tests after generation")
        post_gen_exec: ExecutionReport = execute_tests(
            work_repo,
            settings=settings,
            with_coverage=True,
            run_id=run_id,
        )

        # 6. Phase 4: Failure Analysis & Repair (if failures occurred)
        target_test_file = result.generated_files[0] if result.generated_files else None
        if post_gen_exec.has_failures:
            _log.info("Failures detected after test generation. Invoking Phase 4 Repair.")
            result.repair_required = True
            repair_report: RepairReport = run_repair_loop(
                work_repo,
                test_file=target_test_file,
                llm_client=llm_client,
                settings=settings,
                max_iterations=max_repair_attempts or (settings.max_repair_iterations if settings else 2),
                write_to_disk=write_to_disk,
                run_id=run_id,
            )
            result.repair_status = repair_report.status.value
            result.repair_attempts = repair_report.iterations_run
            result.failures_resolved = repair_report.failures_fixed_count
            result.repair_duration_seconds = repair_report.duration_seconds
            result.repaired_files = list(repair_report.repaired_files)
            result.has_source_code_defects = repair_report.has_source_code_defects
            result.errors.extend(repair_report.errors)
            result.warnings.extend(repair_report.warnings)
        else:
            _log.info("All generated tests passed immediately. No repair needed.")
            result.repair_required = False
            result.repair_status = "no_failures"

        # 7. Phase 2: Final Verification Execution
        _log.info("Phase 2: Running final test execution to measure final status and coverage")
        final_exec: ExecutionReport = execute_tests(
            work_repo,
            settings=settings,
            with_coverage=True,
            run_id=run_id,
        )
        result.final_execution_status = final_exec.status.value
        result.final_passed = final_exec.passed_count
        result.final_failed = final_exec.failed_count
        result.final_execution_duration_seconds = final_exec.duration_seconds
        result.coverage_after = final_exec.coverage.coverage_pct

        if result.coverage_before is not None and result.coverage_after is not None:
            result.coverage_delta = round(result.coverage_after - result.coverage_before, 2)

        # 8. Overall Pipeline Status
        if result.has_source_code_defects or (
            result.repair_required and result.repair_status == RepairStatus.NOT_REPAIRABLE.value
        ):
            result.status = BenchmarkEvaluationStatus.NOT_REPAIRABLE
        elif (
            final_exec.status == ExecutionStatus.PASSED
            and final_exec.passed_count > 0
            and (not result.repair_required or result.repair_status == "success")
        ):
            result.status = BenchmarkEvaluationStatus.SUCCESS
        elif result.failures_resolved > 0 and result.final_failed > 0:
            result.status = BenchmarkEvaluationStatus.PARTIAL
        else:
            result.status = BenchmarkEvaluationStatus.FAILED

    finally:
        if temp_dir_obj is not None:
            try:
                temp_dir_obj.cleanup()
            except Exception as exc:  # noqa: BLE001
                _log.debug("Cleanup of temporary evaluation workspace failed: %s", exc)

    result.total_duration_seconds = round(time.monotonic() - start_time, 3)
    result.completed_at = datetime.now(tz=UTC)
    return result


class EvaluationRunner:
    """
    High-level runner managing single benchmark evaluations and benchmark suites.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        llm_client: BaseLLMClient | None = None,
        isolate: bool = True,
    ) -> None:
        self._settings = settings
        self._llm = llm_client
        self._isolate = isolate

    def run(
        self,
        repo_path: Path | str,
        target_module: Path | str | None = None,
        write_to_disk: bool = True,
        max_repair_attempts: int | None = None,
        run_id: str = "eval",
    ) -> BenchmarkEvaluationResult:
        """Run evaluation on a single benchmark repository."""
        return run_benchmark_evaluation(
            repo_path=repo_path,
            target_module=target_module,
            llm_client=self._llm,
            settings=self._settings,
            isolate=self._isolate,
            write_to_disk=write_to_disk,
            max_repair_attempts=max_repair_attempts,
            run_id=run_id,
        )

    def run_suite(
        self,
        benchmark_repos: list[Path | str],
        suite_name: str = "TestPilot Benchmark Suite",
        run_id: str = "suite",
    ) -> SuiteEvaluationResult:
        """Run evaluation on a list of benchmark repositories and aggregate results."""
        start_time = time.monotonic()
        suite_res = SuiteEvaluationResult(
            suite_name=suite_name,
            started_at=datetime.now(tz=UTC),
        )

        for b_path in benchmark_repos:
            res = self.run(b_path, run_id=f"{run_id}_{Path(b_path).name}")
            suite_res.results.append(res)
            suite_res.benchmarks_run += 1
            if res.status == BenchmarkEvaluationStatus.SUCCESS:
                suite_res.benchmarks_succeeded += 1
            else:
                suite_res.benchmarks_failed += 1

        suite_res.total_duration_seconds = round(time.monotonic() - start_time, 3)
        suite_res.completed_at = datetime.now(tz=UTC)
        return suite_res
