"""
Tests for generation data models (testpilot.models.generation).

Verifies:
- Default and custom construction of models.
- JSON serialization and deserialization roundtrip.
- Computed properties (total_tests_generated, has_valid_tests, test_names, all_test_names).
- Validation and error handling.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from testpilot.models.generation import (
    GeneratedTestCase,
    GeneratedTestFile,
    GenerationReport,
    GenerationStatus,
)


class TestGeneratedTestCase:
    def test_construction_required_fields(self):
        tc = GeneratedTestCase(name="test_addition")
        assert tc.name == "test_addition"
        assert tc.target_function == ""
        assert tc.line is None
        assert tc.is_async is False
        assert tc.has_docstring is False

    def test_construction_custom_fields(self):
        tc = GeneratedTestCase(
            name="test_async_fetch",
            target_function="fetch",
            line=42,
            is_async=True,
            has_docstring=True,
        )
        assert tc.name == "test_async_fetch"
        assert tc.target_function == "fetch"
        assert tc.line == 42
        assert tc.is_async is True
        assert tc.has_docstring is True


class TestGeneratedTestFile:
    def test_default_construction(self):
        gtf = GeneratedTestFile(
            file_path="tests/test_sample.py",
            target_source_file="src/sample.py",
        )
        assert gtf.file_path == "tests/test_sample.py"
        assert gtf.target_source_file == "src/sample.py"
        assert gtf.code == ""
        assert gtf.test_cases == []
        assert gtf.is_valid is False
        assert gtf.validation_error is None
        assert gtf.written_to_disk is False
        assert gtf.test_count == 0
        assert gtf.test_names == []

    def test_test_count_and_names(self):
        gtf = GeneratedTestFile(
            file_path="tests/test_math.py",
            target_source_file="src/math.py",
            code="def test_a(): pass\ndef test_b(): pass",
            test_cases=[
                GeneratedTestCase(name="test_a"),
                GeneratedTestCase(name="test_b"),
            ],
            is_valid=True,
        )
        assert gtf.test_count == 2
        assert gtf.test_names == ["test_a", "test_b"]


class TestGenerationReport:
    def test_minimal_construction(self):
        report = GenerationReport(repository_path="/path/to/repo")
        assert report.repository_path == "/path/to/repo"
        assert report.status == GenerationStatus.ERROR
        assert report.target_files == []
        assert report.generated_files == []
        assert report.total_tests_generated == 0
        assert report.has_valid_tests is False
        assert report.valid_files == []
        assert report.all_test_names == []
        assert report.prompt_tokens == 0
        assert report.completion_tokens == 0

    def test_successful_report_properties(self):
        f1 = GeneratedTestFile(
            file_path="tests/test_a.py",
            target_source_file="src/a.py",
            code="def test_one(): pass",
            test_cases=[GeneratedTestCase(name="test_one")],
            is_valid=True,
            written_to_disk=True,
        )
        f2 = GeneratedTestFile(
            file_path="tests/test_b.py",
            target_source_file="src/b.py",
            code="def test_two(): pass\ndef test_three(): pass",
            test_cases=[
                GeneratedTestCase(name="test_two"),
                GeneratedTestCase(name="test_three"),
            ],
            is_valid=True,
            written_to_disk=True,
        )
        f3_invalid = GeneratedTestFile(
            file_path="tests/test_bad.py",
            target_source_file="src/bad.py",
            code="def bad syntax",
            is_valid=False,
            validation_error="Syntax error",
        )

        report = GenerationReport(
            repository_path="/repo",
            target_files=["src/a.py", "src/b.py", "src/bad.py"],
            status=GenerationStatus.SUCCESS,
            generated_files=[f1, f2, f3_invalid],
        )

        assert report.total_tests_generated == 3
        assert report.has_valid_tests is True
        assert len(report.valid_files) == 2
        assert report.all_test_names == ["test_one", "test_two", "test_three"]

    def test_json_serialization_roundtrip(self):
        f = GeneratedTestFile(
            file_path="tests/test_demo.py",
            target_source_file="src/demo.py",
            code="def test_ok(): assert True",
            test_cases=[GeneratedTestCase(name="test_ok", line=1)],
            is_valid=True,
            written_to_disk=True,
        )
        report = GenerationReport(
            repository_path="/workspace/demo",
            target_files=["src/demo.py"],
            status=GenerationStatus.SUCCESS,
            generated_files=[f],
            explanation="Generated one unit test for demo.",
            raw_response="```python\ndef test_ok(): assert True\n```",
            model="gpt-4o",
            prompt_tokens=150,
            completion_tokens=45,
            total_tokens=195,
            duration_seconds=1.23,
        )

        json_str = report.model_dump_json()
        assert isinstance(json_str, str)

        data = json.loads(json_str)
        assert data["repository_path"] == "/workspace/demo"
        assert data["status"] == "success"
        assert data["model"] == "gpt-4o"
        assert len(data["generated_files"]) == 1
        assert data["generated_files"][0]["test_cases"][0]["name"] == "test_ok"

        restored = GenerationReport.model_validate_json(json_str)
        assert restored.repository_path == report.repository_path
        assert restored.status == report.status
        assert restored.total_tests_generated == 1
        assert restored.has_valid_tests is True
        assert restored.generated_files[0].code == f.code

    def test_missing_required_repository_path_raises(self):
        with pytest.raises(ValidationError):
            GenerationReport()  # type: ignore[call-arg]

    def test_generation_status_enums(self):
        assert GenerationStatus.SUCCESS == "success"
        assert GenerationStatus.PARTIAL == "partial"
        assert GenerationStatus.SYNTAX_ERROR == "syntax_error"
        assert GenerationStatus.NO_TESTS_FOUND == "no_tests_found"
        assert GenerationStatus.EMPTY_RESPONSE == "empty_response"
        assert GenerationStatus.LLM_ERROR == "llm_error"
        assert GenerationStatus.VALIDATION_ERROR == "validation_error"
        assert GenerationStatus.ERROR == "error"
