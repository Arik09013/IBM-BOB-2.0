"""
Tests for FailureAnalysisAgent, RepairAgent, and run_repair_loop() (testpilot.agents.repair).

Verifies:
- Heuristic failure classification across common exception categories.
- LLM-assisted failure diagnosis with graceful heuristic fallback.
- Unified diff generation for test code modifications.
- Bounded repair loop execution (success, max iterations, not repairable).
- AST syntax validation preventing malformed repair code from being applied.
- Full SessionContext integration and roundtrip JSON persistence.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from testpilot.agents.repair import (
    FailureAnalysisAgent,
    RepairAgent,
    analyze_failure_with_llm,
    build_repair_prompt,
    classify_failure_heuristically,
    generate_unified_diff,
    run_repair_loop,
)
from testpilot.config import Settings
from testpilot.llm.client import BaseLLMClient, LLMMessage, LLMResponse
from testpilot.models.execution import (
    ExecutionReport,
    ExecutionStatus,
    TestCaseResultItem,
    TestStatus,
)
from testpilot.models.repair import (
    FailureCategory,
    RepairReport,
    RepairStatus,
)
from testpilot.session_context import PipelineStep, SessionContext


# ---------------------------------------------------------------------------
# Test Fakes
# ---------------------------------------------------------------------------

class FakeRepairLLM(BaseLLMClient):
    """Controllable fake LLM for failure analysis and repair tests."""

    def __init__(
        self,
        analysis_content: str = "",
        repair_content: str = "",
        raises_exc: Exception | None = None,
    ) -> None:
        self._analysis_content = analysis_content
        self._repair_content = repair_content
        self._raises = raises_exc
        self.call_count = 0
        self.calls: list[list[LLMMessage]] = []

    @property
    def provider_name(self) -> str:
        return "fake-repair"

    @property
    def model_name(self) -> str:
        return "fake-repair-model"

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

        # Distinguish between analysis requests and repair requests
        sys_msg = messages[0].content if messages else ""
        if "diagnostician" in sys_msg:
            content = self._analysis_content or (
                '{"category": "incorrect_expectation", "is_repairable_at_test_level": true, '
                '"explanation": "Assertion value mismatch", "suggested_fix": "Fix expected number"}'
            )
        else:
            content = self._repair_content or "```python\ndef test_ok(): assert True\n```"

        return LLMResponse(
            content=content,
            model=self.model_name,
            prompt_tokens=120,
            completion_tokens=60,
            total_tokens=180,
        )


@pytest.fixture
def benchmark_repo() -> Path:
    return (Path(__file__).parent.parent / "benchmarks" / "repositories" / "python_simple").resolve()


# ---------------------------------------------------------------------------
# Heuristic & LLM Failure Classification
# ---------------------------------------------------------------------------

class TestFailureClassification:
    def test_heuristic_missing_import(self):
        cat, exp, rep = classify_failure_heuristically("NameError", "name 'calculator' is not defined", "")
        assert cat == FailureCategory.MISSING_FIXTURE_IMPORT_SETUP
        assert rep is True

    def test_heuristic_syntax_error(self):
        cat, exp, rep = classify_failure_heuristically("SyntaxError", "invalid syntax", "line 4")
        assert cat == FailureCategory.GENERATED_TEST_ISSUE
        assert rep is True

    def test_heuristic_assertion_error(self):
        cat, exp, rep = classify_failure_heuristically("AssertionError", "assert 4 == 5", "assert 4 == 5")
        assert cat == FailureCategory.INCORRECT_EXPECTATION
        assert rep is True

    def test_heuristic_unhandled_exception(self):
        cat, exp, rep = classify_failure_heuristically("ZeroDivisionError", "division by zero", "return a / b")
        assert cat == FailureCategory.INCORRECT_EXPECTATION
        assert rep is True

    def test_heuristic_environment_issue(self):
        cat, exp, rep = classify_failure_heuristically("OSError", "Permission denied: '/etc/shadow'", "")
        assert cat == FailureCategory.ENVIRONMENT_DEPENDENCY_ISSUE
        assert rep is False

    def test_llm_classification_success(self):
        item = TestCaseResultItem(
            nodeid="tests/test_demo.py::test_math",
            failure_type="AssertionError",
            failure_message="assert 1 == 2",
        )
        fake_llm = FakeRepairLLM(
            analysis_content=(
                '{"category": "incorrect_expectation", "is_repairable_at_test_level": true, '
                '"explanation": "Wrong expected number", "suggested_fix": "Change 2 to 1"}'
            )
        )
        analysis = analyze_failure_with_llm(
            test_item=item,
            test_code="def test_math(): assert 1 == 2",
            source_code="",
            llm_client=fake_llm,
        )
        assert analysis.category == FailureCategory.INCORRECT_EXPECTATION
        assert analysis.is_repairable_at_test_level is True
        assert "Wrong expected number" in analysis.explanation
        assert "Change 2 to 1" in analysis.suggested_fix

    def test_llm_classification_fallback_on_error(self):
        item = TestCaseResultItem(
            nodeid="tests/test_demo.py::test_missing",
            failure_type="NameError",
            failure_message="name 'xyz' is not defined",
        )
        fake_llm = FakeRepairLLM(raises_exc=RuntimeError("Provider timeout"))
        analysis = analyze_failure_with_llm(
            test_item=item,
            test_code="def test_missing(): xyz()",
            source_code="",
            llm_client=fake_llm,
        )
        # Should gracefully fall back to heuristic
        assert analysis.category == FailureCategory.MISSING_FIXTURE_IMPORT_SETUP
        assert analysis.is_repairable_at_test_level is True


# ---------------------------------------------------------------------------
# Diffs & Prompts
# ---------------------------------------------------------------------------

class TestDiffAndPrompt:
    def test_generate_unified_diff(self):
        orig = "def test_a():\n    assert 1 == 2\n"
        repaired = "def test_a():\n    assert 1 == 1\n"
        diff = generate_unified_diff(orig, repaired, "tests/test_a.py")
        assert "--- a/tests/test_a.py" in diff
        assert "+++ b/tests/test_a.py" in diff
        assert "-    assert 1 == 2" in diff
        assert "+    assert 1 == 1" in diff

    def test_build_repair_prompt(self):
        from testpilot.models.repair import FailureAnalysis

        analyses = [
            FailureAnalysis(
                test_nodeid="test_foo",
                category=FailureCategory.INCORRECT_EXPECTATION,
                explanation="Expectation is wrong",
                suggested_fix="Fix it",
            )
        ]
        messages = build_repair_prompt(
            test_code="def test_foo(): pass",
            source_code="def foo(): return 1",
            analyses=analyses,
            test_file_rel="tests/test_foo.py",
        )
        assert len(messages) == 2
        assert "test_foo" in messages[1].content
        assert "Expectation is wrong" in messages[1].content


# ---------------------------------------------------------------------------
# Bounded Repair Loop Execution
# ---------------------------------------------------------------------------

class TestBoundedRepairLoop:
    def test_repair_loop_no_failures(self, benchmark_repo):
        # Benchmark repository tests already pass 100%
        fake_llm = FakeRepairLLM()
        report = run_repair_loop(
            repo_path=benchmark_repo,
            llm_client=fake_llm,
        )
        assert report.status == RepairStatus.NO_FAILURES
        assert report.resolved is True
        assert report.iterations_run == 0
        assert fake_llm.call_count == 0  # No LLM calls needed when tests pass!

    def test_repair_loop_successful_repair(self, tmp_path):
        # Create a self-contained repo with a passing source and broken test
        src_dir = tmp_path / "src" / "math_pkg"
        src_dir.mkdir(parents=True)
        (src_dir / "__init__.py").write_text("", encoding="utf-8")
        (src_dir / "calculator.py").write_text(
            "def add(a, b):\n    return a + b\n",
            encoding="utf-8",
        )

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("", encoding="utf-8")
        test_file = tests_dir / "test_calculator.py"
        test_file.write_text(
            "from math_pkg.calculator import add\n\n"
            "def test_add_failing():\n"
            "    assert add(2, 3) == 999\n",
            encoding="utf-8",
        )

        # Repaired test code
        repaired_code = (
            "from math_pkg.calculator import add\n\n"
            "def test_add_failing():\n"
            "    assert add(2, 3) == 5\n"
        )
        fake_llm = FakeRepairLLM(
            repair_content=f"```python\n{repaired_code}\n```"
        )

        report = run_repair_loop(
            repo_path=tmp_path,
            test_file="tests/test_calculator.py",
            llm_client=fake_llm,
            max_iterations=2,
            write_to_disk=True,
        )

        assert report.status == RepairStatus.SUCCESS
        assert report.resolved is True
        assert report.iterations_run == 1
        assert len(report.initial_failures) == 1
        assert len(report.final_failures) == 0
        assert report.failures_fixed_count == 1
        assert len(report.repaired_files) == 1

        # Check disk was updated
        updated_content = test_file.read_text(encoding="utf-8")
        assert "assert add(2, 3) == 5" in updated_content

    def test_repair_loop_not_repairable_source_defect(self, tmp_path):
        # Setup repo with broken test
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir(parents=True)
        (tests_dir / "test_defect.py").write_text("def test_x(): assert False\n", encoding="utf-8")

        # Fake LLM classifies as genuine source defect
        fake_llm = FakeRepairLLM(
            analysis_content=(
                '{"category": "source_code_defect", "is_repairable_at_test_level": false, '
                '"explanation": "Source logic has a bug"}'
            )
        )
        report = run_repair_loop(
            repo_path=tmp_path,
            test_file="tests/test_defect.py",
            llm_client=fake_llm,
            max_iterations=2,
        )

        assert report.status == RepairStatus.NOT_REPAIRABLE
        assert report.resolved is False
        assert report.has_source_code_defects is True

    def test_repair_loop_validation_failure(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir(parents=True)
        (tests_dir / "test_broken.py").write_text("def test_fail(): assert 1 == 2\n", encoding="utf-8")

        # Fake LLM returns invalid Python syntax
        fake_llm = FakeRepairLLM(repair_content="```python\ndef test_bad_syntax(: pass\n```")

        report = run_repair_loop(
            repo_path=tmp_path,
            test_file="tests/test_broken.py",
            llm_client=fake_llm,
            max_iterations=1,
            write_to_disk=True,
        )

        assert report.status == RepairStatus.VALIDATION_FAILED
        assert report.resolved is False
        assert len(report.attempts) == 1
        assert report.attempts[0].is_ast_valid is False
        assert "Syntax error" in report.attempts[0].validation_error

    def test_repair_loop_max_iterations_bound(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir(parents=True)
        (tests_dir / "test_stubborn.py").write_text("def test_never_passes(): assert 1 == 0\n", encoding="utf-8")

        # Fake LLM returns valid python that still fails
        still_failing = "def test_never_passes(): assert 2 == 0\n"
        fake_llm = FakeRepairLLM(repair_content=f"```python\n{still_failing}\n```")

        report = run_repair_loop(
            repo_path=tmp_path,
            test_file="tests/test_stubborn.py",
            llm_client=fake_llm,
            max_iterations=2,
            write_to_disk=True,
        )

        assert report.status == RepairStatus.MAX_ITERATIONS_EXCEEDED
        assert report.resolved is False
        assert report.iterations_run == 2


# ---------------------------------------------------------------------------
# Agents & SessionContext Integration
# ---------------------------------------------------------------------------

class TestAgentSessionContextIntegration:
    def test_failure_analysis_agent_run(self, tmp_path):
        ctx = SessionContext(repo_path=tmp_path)
        ctx.execution_report = ExecutionReport(
            repository_path=str(tmp_path),
            status=ExecutionStatus.TEST_FAILURES,
            tests=[
                TestCaseResultItem(
                    nodeid="tests/test_foo.py::test_fail",
                    file="tests/test_foo.py",
                    status=TestStatus.FAILED,
                    failure_type="AssertionError",
                    failure_message="assert False",
                )
            ],
        )

        fake_llm = FakeRepairLLM()
        agent = FailureAnalysisAgent(llm_client=fake_llm, settings=Settings())

        result = agent.run(ctx)
        assert result.success is True
        assert ctx.current_step == PipelineStep.FAILURE_ANALYSIS
        assert ctx.repair_report is not None
        assert len(ctx.repair_report.analyses) == 1

    def test_repair_agent_run_updates_context(self, benchmark_repo):
        ctx = SessionContext(repo_path=benchmark_repo)
        fake_llm = FakeRepairLLM()
        agent = RepairAgent(llm_client=fake_llm, settings=Settings())

        result = agent.run(ctx)
        assert result.success is True
        assert ctx.current_step == PipelineStep.COMPLETE
        assert ctx.repair_report is not None
        assert ctx.repair_report.status == RepairStatus.NO_FAILURES

    def test_session_context_save_and_load_with_repair_report(self, tmp_path):
        ctx = SessionContext(repo_path=tmp_path)
        ctx.repair_report = RepairReport(
            repository_path=str(tmp_path),
            status=RepairStatus.SUCCESS,
            iterations_run=1,
            initial_failures=["test_one"],
            final_failures=[],
        )
        save_path = tmp_path / "ctx_repair.json"
        ctx.save(save_path)
        assert save_path.exists()

        loaded = SessionContext.load(save_path)
        assert loaded.repair_report is not None
        assert loaded.repair_report.status == RepairStatus.SUCCESS
        assert loaded.repair_report.resolved is True
