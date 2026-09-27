"""
Tests for ExecutionReport and related models (testpilot.models.execution).

Verifies:
- Default and custom construction of models.
- JSON serialization and deserialization roundtrip.
- Computed properties (pass_rate, total_tests, has_failures, failed_tests).
- Validation and error handling.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from testpilot.models.execution import (
    ExecutionCoverage,
    ExecutionReport,
    ExecutionStatus,
    ExecutionSummary,
    TestCaseResultItem,
    TestStatus,
)
from testpilot.models.repository import CoverageStatus


class TestExecutionSummary:
    def test_default_construction(self):
        summary = ExecutionSummary()
        assert summary.total == 0
        assert summary.passed == 0
        assert summary.failed == 0
        assert summary.errors == 0
        assert summary.skipped == 0
        assert summary.xfailed == 0
        assert summary.xpassed == 0
        assert summary.pass_rate is None

    def test_pass_rate_computation(self):
        summary = ExecutionSummary(total=10, passed=8, failed=2)
        assert summary.pass_rate == 0.8

    def test_pass_rate_all_passed(self):
        summary = ExecutionSummary(total=5, passed=5)
        assert summary.pass_rate == 1.0

    def test_pass_rate_all_failed(self):
        summary = ExecutionSummary(total=5, passed=0, failed=5)
        assert summary.pass_rate == 0.0

    def test_pass_rate_zero_total(self):
        summary = ExecutionSummary(total=0, passed=0)
        assert summary.pass_rate is None


class TestTestCaseResultItem:
    def test_default_construction(self):
        item = TestCaseResultItem(nodeid="tests/test_math.py::test_add")
        assert item.nodeid == "tests/test_math.py::test_add"
        assert item.status == TestStatus.PASSED
        assert item.duration_seconds is None
        assert item.failure_message == ""
        assert item.failure_type == ""
        assert item.traceback == ""

    def test_failure_fields(self):
        item = TestCaseResultItem(
            nodeid="tests/test_math.py::test_fail",
            name="test_fail",
            file="tests/test_math.py",
            status=TestStatus.FAILED,
            duration_seconds=0.012,
            failure_type="AssertionError",
            failure_message="assert 1 == 2",
            traceback="Traceback:\n  assert 1 == 2",
        )
        assert item.status == TestStatus.FAILED
        assert item.failure_type == "AssertionError"
        assert item.duration_seconds == 0.012
        assert "assert 1 == 2" in item.failure_message

    def test_enum_statuses(self):
        for status in [
            TestStatus.PASSED,
            TestStatus.FAILED,
            TestStatus.ERROR,
            TestStatus.SKIPPED,
            TestStatus.XFAILED,
            TestStatus.XPASSED,
        ]:
            item = TestCaseResultItem(nodeid="t", status=status)
            assert item.status == status


class TestExecutionCoverage:
    def test_default_construction(self):
        cov = ExecutionCoverage()
        assert cov.status == CoverageStatus.NOT_ATTEMPTED
        assert cov.coverage_pct is None
        assert cov.lines_covered is None
        assert cov.lines_total is None
        assert cov.missing_lines_by_file == {}

    def test_with_data(self):
        cov = ExecutionCoverage(
            status=CoverageStatus.COLLECTED,
            coverage_pct=85.5,
            lines_covered=171,
            lines_total=200,
            missing_lines_by_file={"pkg/module.py": [10, 11, 12]},
        )
        assert cov.status == CoverageStatus.COLLECTED
        assert cov.coverage_pct == 85.5
        assert cov.lines_covered == 171
        assert cov.missing_lines_by_file["pkg/module.py"] == [10, 11, 12]


class TestExecutionReport:
    def test_minimal_construction(self):
        report = ExecutionReport(repository_path="/test/repo")
        assert report.repository_path == "/test/repo"
        assert report.status == ExecutionStatus.ERROR
        assert report.exit_code == -1
        assert report.duration_seconds == 0.0
        assert report.timed_out is False
        assert report.success is False
        assert report.total_tests == 0
        assert report.passed_count == 0
        assert report.failed_count == 0
        assert report.failed_tests == []
        assert report.has_failures is False

    def test_successful_run_properties(self):
        report = ExecutionReport(
            repository_path="/test/repo",
            status=ExecutionStatus.PASSED,
            exit_code=0,
            duration_seconds=1.23,
            success=True,
            summary=ExecutionSummary(total=10, passed=10),
            tests=[
                TestCaseResultItem(nodeid=f"tests/test_x.py::test_{i}", status=TestStatus.PASSED)
                for i in range(10)
            ],
        )
        assert report.total_tests == 10
        assert report.passed_count == 10
        assert report.failed_count == 0
        assert report.pass_rate == 1.0
        assert report.has_failures is False
        assert report.failed_tests == []
        assert report.failed_test_items == []

    def test_failed_run_properties(self):
        failed_item = TestCaseResultItem(
            nodeid="tests/test_x.py::test_broken",
            status=TestStatus.FAILED,
            failure_type="AssertionError",
            failure_message="assert False",
        )
        error_item = TestCaseResultItem(
            nodeid="tests/test_x.py::test_crash",
            status=TestStatus.ERROR,
            failure_type="RuntimeError",
            failure_message="boom",
        )
        passed_item = TestCaseResultItem(
            nodeid="tests/test_x.py::test_ok",
            status=TestStatus.PASSED,
        )
        report = ExecutionReport(
            repository_path="/test/repo",
            status=ExecutionStatus.TEST_FAILURES,
            exit_code=1,
            duration_seconds=0.85,
            success=True,
            summary=ExecutionSummary(total=3, passed=1, failed=1, errors=1),
            tests=[passed_item, failed_item, error_item],
        )
        assert report.total_tests == 3
        assert report.passed_count == 1
        assert report.failed_count == 1
        assert report.pass_rate == pytest.approx(0.3333, abs=0.001)
        assert report.has_failures is True
        assert report.failed_tests == [
            "tests/test_x.py::test_broken",
            "tests/test_x.py::test_crash",
        ]
        assert len(report.failed_test_items) == 2

    def test_json_serialization_roundtrip(self):
        report = ExecutionReport(
            repository_path="/my/project",
            command=["python", "-m", "pytest"],
            exit_code=0,
            status=ExecutionStatus.PASSED,
            duration_seconds=2.45,
            success=True,
            summary=ExecutionSummary(total=2, passed=2),
            tests=[
                TestCaseResultItem(
                    nodeid="tests/test_a.py::test_one",
                    name="test_one",
                    file="tests/test_a.py",
                    status=TestStatus.PASSED,
                    duration_seconds=0.015,
                ),
                TestCaseResultItem(
                    nodeid="tests/test_a.py::test_two",
                    name="test_two",
                    file="tests/test_a.py",
                    status=TestStatus.PASSED,
                    duration_seconds=0.020,
                ),
            ],
            coverage=ExecutionCoverage(
                status=CoverageStatus.COLLECTED,
                coverage_pct=92.5,
                lines_covered=37,
                lines_total=40,
                missing_lines_by_file={"src/lib.py": [4, 5, 6]},
            ),
            stdout="pytest output",
            stderr="",
        )

        json_str = report.model_dump_json(indent=2)
        assert "tests/test_a.py::test_one" in json_str
        assert "92.5" in json_str

        loaded = ExecutionReport.model_validate_json(json_str)
        assert loaded.repository_path == "/my/project"
        assert loaded.status == ExecutionStatus.PASSED
        assert loaded.total_tests == 2
        assert loaded.passed_count == 2
        assert loaded.coverage.coverage_pct == 92.5
        assert loaded.coverage.missing_lines_by_file == {"src/lib.py": [4, 5, 6]}
        assert len(loaded.tests) == 2
        assert loaded.tests[0].nodeid == "tests/test_a.py::test_one"
        assert loaded.tests[0].duration_seconds == 0.015

    def test_missing_required_repository_path_raises(self):
        with pytest.raises(ValidationError):
            ExecutionReport()  # repository_path is required
