"""
Tests for failure analysis and repair data models (testpilot.models.repair).

Verifies:
- Default and custom construction of models.
- Enum values and categories.
- Computed properties (resolved, failures_fixed_count, has_source_code_defects).
- JSON serialization and deserialization roundtrip.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from testpilot.models.repair import (
    FailureAnalysis,
    FailureCategory,
    RepairAttemptRecord,
    RepairReport,
    RepairStatus,
)


class TestRepairEnums:
    def test_failure_category_values(self):
        assert FailureCategory.GENERATED_TEST_ISSUE == "generated_test_issue"
        assert FailureCategory.INCORRECT_EXPECTATION == "incorrect_expectation"
        assert FailureCategory.MISSING_FIXTURE_IMPORT_SETUP == "missing_fixture_import_setup"
        assert FailureCategory.SOURCE_CODE_DEFECT == "source_code_defect"
        assert FailureCategory.ENVIRONMENT_DEPENDENCY_ISSUE == "environment_dependency_issue"
        assert FailureCategory.UNKNOWN == "unknown"

    def test_repair_status_values(self):
        assert RepairStatus.SUCCESS == "success"
        assert RepairStatus.PARTIAL == "partial"
        assert RepairStatus.NOT_REPAIRABLE == "not_repairable"
        assert RepairStatus.VALIDATION_FAILED == "validation_failed"
        assert RepairStatus.MAX_ITERATIONS_EXCEEDED == "max_iterations_exceeded"
        assert RepairStatus.NO_FAILURES == "no_failures"
        assert RepairStatus.LLM_ERROR == "llm_error"
        assert RepairStatus.VALIDATION_ERROR == "validation_error"
        assert RepairStatus.ERROR == "error"


class TestFailureAnalysis:
    def test_minimal_construction(self):
        fa = FailureAnalysis(test_nodeid="tests/test_foo.py::test_bar")
        assert fa.test_nodeid == "tests/test_foo.py::test_bar"
        assert fa.category == FailureCategory.UNKNOWN
        assert fa.confidence == 1.0
        assert fa.is_repairable_at_test_level is True
        assert fa.explanation == ""
        assert fa.suggested_fix == ""

    def test_custom_fields(self):
        fa = FailureAnalysis(
            test_nodeid="tests/test_math.py::test_div_zero",
            category=FailureCategory.INCORRECT_EXPECTATION,
            confidence=0.95,
            is_repairable_at_test_level=True,
            explanation="Test should use pytest.raises(ZeroDivisionError)",
            suggested_fix="with pytest.raises(ZeroDivisionError): divide(1, 0)",
            root_cause="ZeroDivisionError not caught",
            failure_type="ZeroDivisionError",
            failure_message="division by zero",
        )
        assert fa.category == FailureCategory.INCORRECT_EXPECTATION
        assert fa.confidence == 0.95
        assert fa.failure_type == "ZeroDivisionError"
        assert "pytest.raises" in fa.suggested_fix


class TestRepairAttemptRecord:
    def test_construction(self):
        rec = RepairAttemptRecord(
            iteration=1,
            test_file="tests/test_calc.py",
            original_failures=["tests/test_calc.py::test_one"],
            repaired_code="def test_one(): assert 1 == 1",
            patch_diff="--- a/test.py\n+++ b/test.py",
            is_ast_valid=True,
            re_execution_passed=True,
            remaining_failures=[],
            duration_seconds=1.2,
        )
        assert rec.iteration == 1
        assert rec.test_file == "tests/test_calc.py"
        assert rec.is_ast_valid is True
        assert rec.re_execution_passed is True
        assert rec.remaining_failures == []


class TestRepairReport:
    def test_minimal_construction(self):
        rep = RepairReport(repository_path="/workspace/repo")
        assert rep.repository_path == "/workspace/repo"
        assert rep.status == RepairStatus.ERROR
        assert rep.iterations_run == 0
        assert rep.max_iterations == 2
        assert rep.resolved is False
        assert rep.failures_fixed_count == 0
        assert rep.has_source_code_defects is False

    def test_resolved_and_counts(self):
        rep = RepairReport(
            repository_path="/workspace/repo",
            status=RepairStatus.SUCCESS,
            iterations_run=1,
            initial_failures=["test_a", "test_b"],
            final_failures=[],
        )
        assert rep.resolved is True
        assert rep.failures_fixed_count == 2

    def test_source_code_defects_detection(self):
        rep = RepairReport(
            repository_path="/workspace/repo",
            analyses=[
                FailureAnalysis(
                    test_nodeid="test_x",
                    category=FailureCategory.SOURCE_CODE_DEFECT,
                )
            ],
        )
        assert rep.has_source_code_defects is True

    def test_json_serialization_roundtrip(self):
        analysis = FailureAnalysis(
            test_nodeid="tests/test_math.py::test_add",
            category=FailureCategory.INCORRECT_EXPECTATION,
            explanation="Expected 4 but got 5",
        )
        rep = RepairReport(
            repository_path="/repo",
            test_file="tests/test_math.py",
            status=RepairStatus.SUCCESS,
            iterations_run=1,
            initial_failures=["tests/test_math.py::test_add"],
            final_failures=[],
            analyses=[analysis],
            repaired_files=["tests/test_math.py"],
            duration_seconds=2.45,
        )

        json_str = rep.model_dump_json()
        assert isinstance(json_str, str)

        data = json.loads(json_str)
        assert data["repository_path"] == "/repo"
        assert data["status"] == "success"
        assert data["analyses"][0]["category"] == "incorrect_expectation"

        restored = RepairReport.model_validate_json(json_str)
        assert restored.repository_path == rep.repository_path
        assert restored.status == rep.status
        assert restored.resolved is True
        assert restored.failures_fixed_count == 1
        assert restored.analyses[0].category == FailureCategory.INCORRECT_EXPECTATION

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            RepairReport()  # type: ignore[call-arg]
