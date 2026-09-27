"""
Tests for TestExecutionAgent and execute_tests() (testpilot.agents.executor).

Verifies:
- Successful test execution on benchmark repository with real coverage.
- Handling of failing tests with structured failure information.
- Handling of skipped, xfail, and xpass tests.
- Handling of collection errors (syntax error in test file).
- Handling of timeout.
- Handling of invalid repository paths.
- Handling of missing pytest in environment.
- Coverage collection and coverage disabled.
- Full SessionContext integration and roundtrip serialization.
"""

from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest

from testpilot.agents.executor import (
    TestExecutionAgent,
    _extract_failure_info,
    _parse_junit_xml,
    _parse_stdout_tests,
    execute_tests,
)
from testpilot.config import Settings
from testpilot.llm.client import LLMClientFactory
from testpilot.models.execution import (
    ExecutionReport,
    ExecutionStatus,
    TestStatus,
)
from testpilot.models.repository import CoverageStatus
from testpilot.session_context import SessionContext
from testpilot.utils.execution import ExecutionEnvironment, ExecutionResult


@pytest.fixture
def benchmark_repo() -> pathlib.Path:
    return (pathlib.Path(__file__).parent.parent / "benchmarks" / "repositories" / "python_simple").resolve()


@pytest.fixture
def stub_agent() -> TestExecutionAgent:
    settings = Settings()
    client = LLMClientFactory.create("stub")
    return TestExecutionAgent(llm_client=client, settings=settings)


class TestBenchmarkExecution:
    def test_benchmark_executes_successfully(self, benchmark_repo, stub_agent):
        ctx = SessionContext(repo_path=benchmark_repo)
        result = stub_agent.run(ctx)

        assert result.success is True
        assert ctx.execution_report is not None
        report = ctx.execution_report
        assert isinstance(report, ExecutionReport)
        assert report.status == ExecutionStatus.PASSED
        assert report.total_tests > 0
        assert report.passed_count == report.total_tests
        assert report.failed_count == 0
        assert report.pass_rate == 1.0
        assert report.has_failures is False
        assert report.duration_seconds > 0

    def test_benchmark_coverage_collected(self, benchmark_repo, stub_agent):
        ctx = SessionContext(repo_path=benchmark_repo)
        result = stub_agent.run(ctx)

        assert result.success is True
        report = ctx.execution_report
        assert report.coverage.status == CoverageStatus.COLLECTED
        assert report.coverage.coverage_pct is not None
        assert 0.0 < report.coverage.coverage_pct <= 100.0
        assert report.coverage.lines_covered is not None
        assert report.coverage.lines_total is not None
        assert ctx.coverage_after == report.coverage.coverage_pct

    def test_benchmark_session_context_integration(self, benchmark_repo, stub_agent):
        ctx = SessionContext(repo_path=benchmark_repo)
        result = stub_agent.run(ctx)

        report_total = result.context.execution_report.summary.passed
        assert result.context.tests_passed == report_total
        assert report_total > 0
        assert result.context.tests_failed == 0
        assert len(result.context.test_results) == report_total

        assert result.context.timing.execution_started_at is not None

    def test_session_context_save_and_load_with_report(self, benchmark_repo, stub_agent, tmp_path):
        ctx = SessionContext(repo_path=benchmark_repo)
        stub_agent.run(ctx)

        save_path = tmp_path / "saved_context.json"
        ctx.save(save_path)
        assert save_path.exists()

        loaded = SessionContext.load(save_path)
        assert loaded.execution_report is not None
        assert isinstance(loaded.execution_report, ExecutionReport)
        assert loaded.execution_report.status == ExecutionStatus.PASSED
        assert loaded.execution_report.total_tests == ctx.execution_report.total_tests
        assert loaded.tests_passed == ctx.tests_passed


class TestFailureScenariosOnFixtures:
    def test_failing_test_reported(self, tmp_path, stub_agent):
        test_file = tmp_path / "test_failures.py"
        test_file.write_text(
            "def test_passing():\n"
            "    assert True\n\n"
            "def test_assertion_failure():\n"
            "    assert 1 == 2, 'custom math mismatch'\n\n"
            "def test_exception_failure():\n"
            "    raise ValueError('unexpected value')\n",
            encoding="utf-8",
        )

        ctx = SessionContext(repo_path=tmp_path)
        result = stub_agent.run(ctx)

        # Target test failure is a successful test execution from the agent's standpoint
        assert result.success is True
        report = ctx.execution_report
        assert report.status == ExecutionStatus.TEST_FAILURES
        assert report.has_failures is True
        assert report.summary.total == 3
        assert report.summary.passed == 1
        assert report.summary.failed == 2
        assert len(report.failed_tests) == 2

        # Check structured failure information
        failed_items = report.failed_test_items
        assert len(failed_items) == 2
        types = {item.failure_type for item in failed_items}
        assert "AssertionError" in types
        assert "ValueError" in types
        messages = " ".join(item.failure_message for item in failed_items)
        assert "custom math mismatch" in messages or "1 == 2" in messages
        assert "unexpected value" in messages

    def test_skipped_and_xfail_tests(self, tmp_path, stub_agent):
        test_file = tmp_path / "test_marks.py"
        test_file.write_text(
            "import pytest\n\n"
            "@pytest.mark.skip(reason='work in progress')\n"
            "def test_skipped():\n"
            "    pass\n\n"
            "@pytest.mark.xfail(reason='known defect')\n"
            "def test_expected_failure():\n"
            "    assert False\n\n"
            "@pytest.mark.xfail(reason='unexpected pass')\n"
            "def test_unexpected_pass():\n"
            "    assert True\n\n"
            "def test_normal_pass():\n"
            "    assert True\n",
            encoding="utf-8",
        )

        ctx = SessionContext(repo_path=tmp_path)
        result = stub_agent.run(ctx)

        assert result.success is True
        report = ctx.execution_report
        assert report.status == ExecutionStatus.PASSED
        assert report.summary.total == 4
        assert report.summary.passed >= 1
        assert report.summary.skipped >= 1

    def test_collection_error_handling(self, tmp_path, stub_agent):
        test_file = tmp_path / "test_syntax_error.py"
        test_file.write_text("def def invalid syntax: ;", encoding="utf-8")

        ctx = SessionContext(repo_path=tmp_path)
        result = stub_agent.run(ctx)

        assert result.success is False
        report = ctx.execution_report
        assert report.status == ExecutionStatus.COLLECTION_ERROR
        assert report.has_failures is True

    def test_no_tests_collected(self, tmp_path, stub_agent):
        # Empty directory with no test files
        ctx = SessionContext(repo_path=tmp_path)
        result = stub_agent.run(ctx)

        assert result.success is True
        report = ctx.execution_report
        assert report.status == ExecutionStatus.NO_TESTS
        assert report.total_tests == 0


class TestEnvironmentAndValidationErrors:
    def test_none_repo_path_validation_error(self, stub_agent):
        ctx = SessionContext(repo_path=None)
        result = stub_agent.run(ctx)

        assert result.success is False
        assert ctx.execution_report is not None
        assert ctx.execution_report.status == ExecutionStatus.VALIDATION_ERROR
        assert "SessionContext.repo_path is not set" in result.message

    def test_nonexistent_repo_path_validation_error(self, tmp_path, stub_agent):
        nonexistent = tmp_path / "does_not_exist_xyz"
        ctx = SessionContext(repo_path=nonexistent)
        result = stub_agent.run(ctx)

        assert result.success is False
        assert ctx.execution_report.status == ExecutionStatus.VALIDATION_ERROR

    def test_file_instead_of_dir_validation_error(self, tmp_path, stub_agent):
        a_file = tmp_path / "some_file.txt"
        a_file.write_text("hello")
        ctx = SessionContext(repo_path=a_file)
        result = stub_agent.run(ctx)

        assert result.success is False
        assert ctx.execution_report.status == ExecutionStatus.VALIDATION_ERROR

    def test_missing_pytest_environment_error(self, tmp_path):
        env = ExecutionEnvironment(
            repo_path=str(tmp_path),
            python_executable="python",
            pytest_available=False,
        )
        report = execute_tests(tmp_path, env=env)
        assert report.status == ExecutionStatus.ENVIRONMENT_ERROR
        assert "pytest is not available" in report.errors[0]

    def test_timeout_handling(self, tmp_path):
        fake_result = ExecutionResult(
            command=["python", "-m", "pytest"],
            timed_out=True,
            duration_seconds=5.0,
            error_detail="Command timed out after 5.0s.",
        )
        with patch("testpilot.agents.executor.run_pytest", return_value=fake_result):
            env = ExecutionEnvironment(
                repo_path=str(tmp_path),
                python_executable="python",
                pytest_available=True,
            )
            report = execute_tests(tmp_path, env=env, timeout=5.0)
            assert report.status == ExecutionStatus.TIMEOUT
            assert report.timed_out is True
            assert report.success is False
            assert "timed out" in report.errors[0]


class TestCoverageOptions:
    def test_coverage_disabled(self, benchmark_repo):
        report = execute_tests(benchmark_repo, with_coverage=False)
        assert report.status == ExecutionStatus.PASSED
        assert report.coverage.status == CoverageStatus.NOT_ATTEMPTED
        assert report.coverage.coverage_pct is None

    def test_coverage_tool_unavailable(self, tmp_path):
        env = ExecutionEnvironment(
            repo_path=str(tmp_path),
            python_executable="python",
            pytest_available=True,
            coverage_available=False,
        )
        report = execute_tests(tmp_path, env=env, with_coverage=True)
        assert report.coverage.status == CoverageStatus.UNAVAILABLE


class TestParsingUtilities:
    def test_extract_failure_info_assertion(self):
        msg = "AssertionError: expected 5 got 3\nassert 3 == 5"
        tb = "tests/test_x.py:10: in test_f\n    assert 3 == 5\nE   AssertionError: expected 5 got 3"
        ftype, fmsg, excerpt = _extract_failure_info(msg, tb)
        assert ftype == "AssertionError"
        assert "expected 5 got 3" in fmsg
        assert excerpt == tb

    def test_extract_failure_info_custom_exception(self):
        msg = "KeyError: 'missing_key'"
        tb = "dict[key]\nKeyError: 'missing_key'"
        ftype, fmsg, _ = _extract_failure_info(msg, tb)
        assert ftype == "KeyError"
        assert "missing_key" in fmsg

    def test_parse_junit_xml_empty(self, tmp_path):
        results = _parse_junit_xml("", tmp_path)
        assert results == []

    def test_parse_junit_xml_valid(self, tmp_path):
        xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<testsuites><testsuite name="pytest" tests="2">'
            '<testcase classname="tests.test_math.TestAdd" name="test_one" time="0.005" file="tests/test_math.py" />'
            '<testcase classname="tests.test_math.TestAdd" name="test_fail" time="0.002" file="tests/test_math.py">'
            '<failure message="AssertionError: boom">traceback text</failure>'
            '</testcase>'
            '</testsuite></testsuites>'
        )
        items = _parse_junit_xml(xml, tmp_path)
        assert len(items) == 2
        assert items[0].name == "test_one"
        assert items[0].status == TestStatus.PASSED
        assert items[0].duration_seconds == 0.005
        assert items[1].name == "test_fail"
        assert items[1].status == TestStatus.FAILED
        assert items[1].failure_type == "AssertionError"
        assert items[1].traceback == "traceback text"

    def test_parse_stdout_summary_info(self):
        output = (
            "=========================== short test summary info ===========================\n"
            "PASSED tests/test_calc.py::test_add\n"
            "FAILED tests/test_calc.py::test_sub - AssertionError: 1 != 2\n"
            "SKIPPED tests/test_calc.py::test_skip - skipped reason\n"
            "XFAIL tests/test_calc.py::test_xfail - reason\n"
            "XPASS tests/test_calc.py::test_xpass - reason\n"

            "======================== 1 failed, 1 passed in 0.20s ==========================\n"
        )
        tests, summary = _parse_stdout_tests(output)
        assert len(tests) == 5
        statuses = {t.status for t in tests}
        assert TestStatus.PASSED in statuses
        assert TestStatus.FAILED in statuses
        assert TestStatus.SKIPPED in statuses
        assert TestStatus.XFAILED in statuses
        assert TestStatus.XPASSED in statuses
        assert summary["failed"] == 1
        assert summary["passed"] == 1
