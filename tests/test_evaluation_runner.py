"""
Tests for Phase 5: Evaluation & Benchmarking (testpilot.evaluation.runner and models).

Verifies:
- BenchmarkEvaluationResult and SuiteEvaluationResult model creation and computed fields.
- JSON serialization roundtrips.
- Integration with RunMetrics and append_metrics.
- Full pipeline execution: Analyze -> Generate -> Execute -> Repair -> Re-execute -> Metrics.
- Isolation mode guarantees original benchmark repository is never modified.
- Coverage delta calculation (before -> after).
- Repair metrics collection when initial generated tests fail.
- Source code defect handling: Safety gate halts with NOT_REPAIRABLE.
- Suite runner aggregating results across multiple benchmark repositories.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from testpilot.config import Settings
from testpilot.evaluation.runner import (
    EvaluationRunner,
    run_benchmark_evaluation,
)
from testpilot.llm.client import BaseLLMClient, LLMMessage, LLMResponse
from testpilot.models.evaluation import (
    BenchmarkEvaluationResult,
    BenchmarkEvaluationStatus,
    ExperimentApproach,
    RunMetrics,
    SuiteEvaluationResult,
    append_metrics,
)


# ---------------------------------------------------------------------------
# Test Fake LLM
# ---------------------------------------------------------------------------

class FakeEvalLLM(BaseLLMClient):
    """Controllable fake LLM for evaluation tests supporting generation, analysis, and repair."""

    def __init__(
        self,
        generation_content: str = "",
        analysis_content: str = "",
        repair_content: str = "",
        raises_exc: Exception | None = None,
    ) -> None:
        self._gen_content = generation_content
        self._analysis_content = analysis_content
        self._repair_content = repair_content
        self._raises = raises_exc
        self.call_count = 0
        self.calls: list[list[LLMMessage]] = []

    @property
    def provider_name(self) -> str:
        return "fake-eval"

    @property
    def model_name(self) -> str:
        return "fake-eval-model"

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        self.call_count += 1
        self.calls.append(messages)
        if self._raises:
            raise self._raises

        sys_msg = messages[0].content if messages else ""

        # Failure analysis request
        if "diagnostician" in sys_msg:
            content = self._analysis_content or (
                '{"category": "incorrect_expectation", "is_repairable_at_test_level": true, '
                '"explanation": "Assertion value mismatch", "suggested_fix": "Fix expected return value"}'
            )
        # Test repair request
        elif "repair" in sys_msg:
            content = self._repair_content or (
                "```python\n"
                "from calculator.converter import celsius_to_fahrenheit\n\n"
                "def test_celsius_repaired():\n"
                "    assert celsius_to_fahrenheit(0) == 32.0\n"
                "```"
            )
        # Test generation request (default)
        else:
            content = self._gen_content or (
                "```python\n"
                "from calculator.converter import celsius_to_fahrenheit, km_to_miles\n\n"
                "def test_celsius_to_fahrenheit_freezing():\n"
                "    assert celsius_to_fahrenheit(0) == 32.0\n\n"
                "def test_km_to_miles_simple():\n"
                "    assert km_to_miles(10) > 6.0\n"
                "```"
            )

        return LLMResponse(
            content=content,
            model=self.model_name,
            prompt_tokens=150,
            completion_tokens=80,
            total_tokens=230,
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def benchmark_repo() -> Path:
    repo = Path(__file__).parent.parent / "benchmarks" / "repositories" / "python_simple"
    assert repo.exists(), f"Benchmark repo not found at {repo}"
    return repo


@pytest.fixture
def defect_repo() -> Path:
    repo = Path(__file__).parent.parent / "benchmarks" / "repositories" / "python_defect"
    assert repo.exists(), f"Defect repo not found at {repo}"
    return repo


# ---------------------------------------------------------------------------
# Unit Tests: Evaluation Models
# ---------------------------------------------------------------------------

class TestEvaluationModels:
    def test_benchmark_result_construction_and_defaults(self):
        res = BenchmarkEvaluationResult(
            benchmark_name="python_simple",
            repository_path="/fake/path",
        )
        assert res.benchmark_name == "python_simple"
        assert res.status == BenchmarkEvaluationStatus.ERROR
        assert res.resolved is False
        assert res.has_coverage_improvement is False

    def test_benchmark_result_resolved_and_coverage(self):
        res = BenchmarkEvaluationResult(
            benchmark_name="python_simple",
            repository_path="/fake/path",
            status=BenchmarkEvaluationStatus.SUCCESS,
            final_passed=31,
            final_failed=0,
            coverage_before=65.0,
            coverage_after=88.5,
            coverage_delta=23.5,
        )
        assert res.resolved is True
        assert res.has_coverage_improvement is True

    def test_json_serialization_roundtrip(self):
        res = BenchmarkEvaluationResult(
            benchmark_name="python_simple",
            repository_path="/fake/path",
            target_module="src/calculator/converter.py",
            status=BenchmarkEvaluationStatus.SUCCESS,
            tests_generated=4,
            valid_generated_tests=4,
            final_passed=33,
            final_failed=0,
            coverage_delta=15.2,
        )
        raw_json = res.model_dump_json()
        loaded = BenchmarkEvaluationResult.model_validate_json(raw_json)
        assert loaded.benchmark_name == "python_simple"
        assert loaded.tests_generated == 4
        assert loaded.coverage_delta == 15.2
        assert loaded.resolved is True

    def test_to_run_metrics_and_append(self, tmp_path):
        res = BenchmarkEvaluationResult(
            benchmark_name="python_simple",
            repository_path=str(tmp_path),
            status=BenchmarkEvaluationStatus.SUCCESS,
            tests_generated=5,
            valid_generated_tests=5,
            final_passed=30,
            final_failed=0,
            coverage_before=70.0,
            coverage_after=90.0,
            coverage_delta=20.0,
            total_duration_seconds=3.5,
        )
        metrics = res.to_run_metrics(run_id="run-001", approach=ExperimentApproach.MULTI)
        assert isinstance(metrics, RunMetrics)
        assert metrics.run_id == "run-001"
        assert metrics.repository == "python_simple"
        assert metrics.coverage_delta == 20.0
        assert metrics.tests_generated == 5
        assert metrics.wall_clock_seconds == 3.5

        out_file = append_metrics(metrics, tmp_path)
        assert out_file.exists()
        line = out_file.read_text(encoding="utf-8").strip()
        data = json.loads(line)
        assert data["run_id"] == "run-001"
        assert data["tests_generated"] == 5

    def test_suite_evaluation_result(self):
        suite = SuiteEvaluationResult(suite_name="Hackathon Suite")
        res1 = BenchmarkEvaluationResult(
            benchmark_name="b1",
            repository_path="p1",
            status=BenchmarkEvaluationStatus.SUCCESS,
        )
        res2 = BenchmarkEvaluationResult(
            benchmark_name="b2",
            repository_path="p2",
            status=BenchmarkEvaluationStatus.NOT_REPAIRABLE,
        )
        suite.results.extend([res1, res2])
        suite.benchmarks_run = 2
        suite.benchmarks_succeeded = 1
        suite.benchmarks_failed = 1
        assert len(suite.results) == 2
        assert suite.benchmarks_succeeded == 1


# ---------------------------------------------------------------------------
# Integration Tests: Evaluation Runner
# ---------------------------------------------------------------------------

class TestEvaluationRunner:
    def test_run_benchmark_invalid_path(self, tmp_path):
        non_existent = tmp_path / "does_not_exist"
        result = run_benchmark_evaluation(non_existent)
        assert result.status == BenchmarkEvaluationStatus.VALIDATION_ERROR
        assert len(result.errors) > 0

    def test_run_benchmark_python_simple_full_pipeline(self, benchmark_repo):
        """
        Test complete Analyze -> Generate -> Execute -> Verify workflow on python_simple.
        Verifies:
        - Target converter.py is selected
        - Tests generated and AST validated
        - Baseline 29 tests pass initially
        - Final test count increases (> 29)
        - Real coverage increases (coverage_delta > 0)
        - Isolation mode ensures original repo files are unchanged!
        """
        # Count test files in original repo before run
        tests_dir = benchmark_repo / "tests"
        files_before = set(p.name for p in tests_dir.iterdir() if p.is_file())

        fake_llm = FakeEvalLLM()
        result = run_benchmark_evaluation(
            repo_path=benchmark_repo,
            target_module="src/calculator/converter.py",
            llm_client=fake_llm,
            isolate=True,
        )

        assert result.status == BenchmarkEvaluationStatus.SUCCESS
        assert result.resolved is True
        assert result.benchmark_name == "python_simple"
        assert "converter.py" in result.target_module
        assert result.analysis_completed is True
        assert result.tests_generated >= 2
        assert result.valid_generated_tests >= 2
        assert result.initial_passed == 29
        assert result.initial_failed == 0
        assert result.final_passed > 29  # 29 baseline + 2 generated
        assert result.final_failed == 0
        assert result.repair_required is False
        assert result.coverage_before is not None
        assert result.coverage_after is not None
        assert result.coverage_after > result.coverage_before
        assert result.coverage_delta is not None and result.coverage_delta > 0

        # Verify ISOLATION: original benchmark repo tests folder is completely clean!
        files_after = set(p.name for p in tests_dir.iterdir() if p.is_file())
        assert files_before == files_after, "Isolation failure: original repo was modified!"

    def test_run_benchmark_with_repair_loop(self, tmp_path):
        """
        Test case where generated test initially fails, triggering Phase 4 repair.
        Repair succeeds and re-execution passes.
        """
        # Create self-contained repo
        src_dir = tmp_path / "src" / "math_pkg"
        src_dir.mkdir(parents=True)
        (src_dir / "__init__.py").write_text("", encoding="utf-8")
        (src_dir / "calc.py").write_text(
            "def add(a: int, b: int) -> int: return a + b\n",
            encoding="utf-8",
        )
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir(parents=True)
        (tests_dir / "__init__.py").write_text("", encoding="utf-8")

        # Fake LLM generates a failing test first, then repairs it
        failing_gen = (
            "```python\n"
            "from math_pkg.calc import add\n\n"
            "def test_add_failing():\n"
            "    assert add(2, 3) == 999\n"
            "```"
        )
        repaired_code = (
            "```python\n"
            "from math_pkg.calc import add\n\n"
            "def test_add_failing():\n"
            "    assert add(2, 3) == 5\n"
            "```"
        )
        fake_llm = FakeEvalLLM(
            generation_content=failing_gen,
            repair_content=repaired_code,
        )

        result = run_benchmark_evaluation(
            repo_path=tmp_path,
            target_module="src/math_pkg/calc.py",
            llm_client=fake_llm,
            isolate=False,
            max_repair_attempts=2,
        )

        assert result.status == BenchmarkEvaluationStatus.SUCCESS
        assert result.resolved is True
        assert result.repair_required is True
        assert result.repair_attempts >= 1
        assert result.failures_resolved >= 1
        assert result.final_passed >= 1
        assert result.final_failed == 0

    def test_run_benchmark_source_defect_safety_gate(self, defect_repo):
        """
        Demonstrate the Phase 4 & Phase 5 Safety Gate:
        When testing python_defect repo, the generated test exposes the intentional bug.
        FailureAnalysisAgent classifies as SOURCE_CODE_DEFECT, halting with NOT_REPAIRABLE.
        """
        # Generator generates test asserting correct mathematical property
        gen_test = (
            "```python\n"
            "from buggy_pkg.validator import is_even\n\n"
            "def test_is_even():\n"
            "    assert is_even(4) is True\n"
            "```"
        )
        # LLM diagnostician correctly flags genuine source code bug
        defect_analysis = (
            '{"category": "source_code_defect", "is_repairable_at_test_level": false, '
            '"explanation": "Source code function is_even evaluates n % 2 == 1 which is odd, not even."}'
        )
        fake_llm = FakeEvalLLM(
            generation_content=gen_test,
            analysis_content=defect_analysis,
        )

        result = run_benchmark_evaluation(
            repo_path=defect_repo,
            target_module="src/buggy_pkg/validator.py",
            llm_client=fake_llm,
            isolate=True,
            max_repair_attempts=2,
        )

        assert result.status == BenchmarkEvaluationStatus.NOT_REPAIRABLE
        assert result.has_source_code_defects is True
        assert result.repair_status == "not_repairable"
        assert result.resolved is False

    def test_evaluation_runner_class_and_suite(self, benchmark_repo, defect_repo):
        fake_llm = FakeEvalLLM()
        runner = EvaluationRunner(llm_client=fake_llm, isolate=True)

        suite_res = runner.run_suite([benchmark_repo, defect_repo])
        assert suite_res.benchmarks_run == 2
        assert len(suite_res.results) == 2
        assert suite_res.benchmarks_succeeded == 1  # python_simple succeeds
        assert suite_res.benchmarks_failed == 1     # python_defect halts on safety gate
