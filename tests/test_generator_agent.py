"""
Tests for TestGenerationAgent and generate_tests() (testpilot.agents.generator).

Verifies:
- Extraction of Python code and explanation from markdown fences and raw text.
- AST parsing and test case discovery (functions and Test classes).
- Rejection of invalid syntax or code lacking test functions.
- Successful generation using mocked LLM client.
- Handling of empty LLM responses, syntax errors, and LLM API exceptions.
- Repository path and target file validation.
- Dry-run vs write-to-disk behavior.
- Full SessionContext integration and roundtrip JSON persistence.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from testpilot.agents.generator import (
    TestGenerationAgent,
    build_generation_prompt,
    determine_test_file_path,
    extract_test_code_and_explanation,
    generate_tests,
    validate_generated_code,
)
from testpilot.config import Settings
from testpilot.llm.client import BaseLLMClient, LLMMessage, LLMResponse
from testpilot.models.generation import GenerationReport, GenerationStatus
from testpilot.session_context import PipelineStep, SessionContext


# ---------------------------------------------------------------------------
# Test Fixtures & Fakes
# ---------------------------------------------------------------------------

class FakeLLMClient(BaseLLMClient):
    """A controllable fake LLM client for generation tests."""

    def __init__(self, response_content: str = "", raises_exc: Exception | None = None) -> None:
        self._content = response_content
        self._raises = raises_exc
        self.call_count = 0
        self.last_messages: list[LLMMessage] = []

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "fake-generator-model"

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        self.call_count += 1
        self.last_messages = messages
        if self._raises:
            raise self._raises
        return LLMResponse(
            content=self._content,
            model=self.model_name,
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )


@pytest.fixture
def benchmark_repo() -> Path:
    return (Path(__file__).parent.parent / "benchmarks" / "repositories" / "python_simple").resolve()


# ---------------------------------------------------------------------------
# Code Extraction & Validation
# ---------------------------------------------------------------------------

class TestCodeExtractionAndValidation:
    def test_extract_fenced_python_code(self):
        text = (
            "Here is the test suite for the converter:\n\n"
            "```python\n"
            "import pytest\n\n"
            "def test_celsius():\n"
            "    assert True\n"
            "```\n\n"
            "This covers all basic conversions."
        )
        code, explanation = extract_test_code_and_explanation(text)
        assert "def test_celsius():" in code
        assert "import pytest" in code
        assert "```" not in code
        assert "Here is the test suite" in explanation
        assert "This covers all basic conversions" in explanation

    def test_extract_raw_python_code(self):
        text = (
            "import pytest\n\n"
            "def test_add():\n"
            "    assert 1 + 1 == 2\n"
        )
        code, explanation = extract_test_code_and_explanation(text)
        assert "def test_add():" in code
        assert explanation == ""

    def test_extract_explanation_only(self):
        text = "I cannot write tests for this module because it does not exist."
        code, explanation = extract_test_code_and_explanation(text)
        assert code == ""
        assert "I cannot write tests" in explanation

    def test_validate_valid_functions_and_classes(self):
        code = (
            "import pytest\n\n"
            "def test_standalone():\n"
            '    """Test standalone function."""\n'
            "    assert 1 == 1\n\n"
            "class TestSuite:\n"
            "    def test_method(self):\n"
            "        assert True\n"
        )
        is_valid, tests, err = validate_generated_code(code)
        assert is_valid is True
        assert err is None
        assert len(tests) == 2

        names = [t.name for t in tests]
        assert "test_standalone" in names
        assert "TestSuite.test_method" in names

        standalone = next(t for t in tests if t.name == "test_standalone")
        assert standalone.has_docstring is True
        assert standalone.is_async is False

    def test_validate_syntax_error(self):
        code = "def test_broken(: pass"
        is_valid, tests, err = validate_generated_code(code)
        assert is_valid is False
        assert tests == []
        assert err is not None
        assert "Syntax error" in err

    def test_validate_no_test_functions(self):
        code = "def regular_helper():\n    return 42\n"
        is_valid, tests, err = validate_generated_code(code)
        assert is_valid is False
        assert tests == []
        assert err is not None
        assert "No test functions" in err

    def test_validate_empty_code(self):
        is_valid, tests, err = validate_generated_code("   \n  ")
        assert is_valid is False
        assert tests == []
        assert err == "Generated code is empty."


# ---------------------------------------------------------------------------
# Prompt Building & Path Logic
# ---------------------------------------------------------------------------

class TestPromptBuildingAndPaths:
    def test_build_generation_prompt_structure(self):
        messages = build_generation_prompt(
            target_source="def celsius_to_fahrenheit(c): return c * 9/5 + 32",
            target_file_rel="src/calculator/converter.py",
            existing_test_sample="def test_add(): assert 1 == 1",
            target_symbols=["celsius_to_fahrenheit"],
        )
        assert len(messages) == 2
        assert messages[0].role == "system"
        assert messages[1].role == "user"
        assert "pytest" in messages[0].content
        assert "src/calculator/converter.py" in messages[1].content
        assert "celsius_to_fahrenheit" in messages[1].content
        assert "calculator.converter" in messages[1].content
        assert "test_add" in messages[1].content

    def test_determine_test_file_path_default(self, tmp_path):
        target = tmp_path / "src" / "pkg" / "converter.py"
        target.parent.mkdir(parents=True)
        target.touch()

        out = determine_test_file_path(tmp_path, target)
        assert out == tmp_path / "tests" / "test_testpilot_converter.py"

    def test_determine_test_file_path_custom(self, tmp_path):
        target = tmp_path / "src" / "calc.py"
        custom = Path("custom_tests/test_my_calc.py")
        out = determine_test_file_path(tmp_path, target, custom)
        assert out == tmp_path / "custom_tests" / "test_my_calc.py"


# ---------------------------------------------------------------------------
# Functional generate_tests() Execution
# ---------------------------------------------------------------------------

class TestGenerateTestsExecution:
    def test_successful_generation(self, tmp_path):
        # Create a mini target repository
        src_dir = tmp_path / "src" / "pkg"
        src_dir.mkdir(parents=True)
        target_file = src_dir / "math_ops.py"
        target_file.write_text("def multiply(a, b): return a * b\n", encoding="utf-8")

        test_code = (
            "import pytest\n"
            "from pkg.math_ops import multiply\n\n"
            "def test_multiply():\n"
            "    assert multiply(2, 3) == 6\n"
        )
        fake_llm = FakeLLMClient(response_content=f"```python\n{test_code}\n```")

        report = generate_tests(
            repo_path=tmp_path,
            target_file=target_file,
            llm_client=fake_llm,
            write_to_disk=True,
        )

        assert report.status == GenerationStatus.SUCCESS
        assert report.has_valid_tests is True
        assert report.total_tests_generated == 1
        assert "test_multiply" in report.all_test_names
        assert len(report.generated_files) == 1

        gf = report.generated_files[0]
        assert gf.is_valid is True
        assert gf.written_to_disk is True
        written_path = tmp_path / gf.file_path
        assert written_path.exists()
        assert "def test_multiply():" in written_path.read_text(encoding="utf-8")

    def test_dry_run_does_not_write_file(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)
        target_file = src_dir / "utils.py"
        target_file.write_text("def ping(): return 'pong'\n", encoding="utf-8")

        test_code = "def test_ping(): assert True\n"
        fake_llm = FakeLLMClient(response_content=f"```python\n{test_code}\n```")

        report = generate_tests(
            repo_path=tmp_path,
            target_file=target_file,
            llm_client=fake_llm,
            write_to_disk=False,
        )

        assert report.status == GenerationStatus.SUCCESS
        assert report.has_valid_tests is True
        gf = report.generated_files[0]
        assert gf.written_to_disk is False
        assert not (tmp_path / gf.file_path).exists()

    def test_empty_llm_response(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        target = src_dir / "mod.py"
        target.write_text("def f(): pass\n", encoding="utf-8")

        fake_llm = FakeLLMClient(response_content="   ")
        report = generate_tests(
            repo_path=tmp_path,
            target_file=target,
            llm_client=fake_llm,
        )

        assert report.status == GenerationStatus.EMPTY_RESPONSE
        assert report.has_valid_tests is False
        assert "empty response" in report.errors[0].lower()

    def test_syntax_error_response(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        target = src_dir / "mod.py"
        target.write_text("def f(): pass\n", encoding="utf-8")

        fake_llm = FakeLLMClient(response_content="```python\ndef test_bad(: pass\n```")
        report = generate_tests(
            repo_path=tmp_path,
            target_file=target,
            llm_client=fake_llm,
        )

        assert report.status == GenerationStatus.SYNTAX_ERROR
        assert report.has_valid_tests is False
        assert len(report.generated_files) == 1
        assert report.generated_files[0].is_valid is False
        assert "syntax error" in report.generated_files[0].validation_error.lower()

    def test_llm_exception_handled(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        target = src_dir / "mod.py"
        target.write_text("def f(): pass\n", encoding="utf-8")

        fake_llm = FakeLLMClient(raises_exc=RuntimeError("Rate limit exceeded"))
        report = generate_tests(
            repo_path=tmp_path,
            target_file=target,
            llm_client=fake_llm,
        )

        assert report.status == GenerationStatus.LLM_ERROR
        assert report.has_valid_tests is False
        assert "Rate limit exceeded" in report.errors[0]

    def test_nonexistent_repo_fails(self):
        fake_llm = FakeLLMClient(response_content="def test_x(): pass")
        report = generate_tests(
            repo_path=Path("/nonexistent/repo/path/12345"),
            llm_client=fake_llm,
        )
        assert report.status == GenerationStatus.VALIDATION_ERROR
        assert "does not exist" in report.errors[0]

    def test_nonexistent_target_file_fails(self, tmp_path):
        fake_llm = FakeLLMClient(response_content="def test_x(): pass")
        report = generate_tests(
            repo_path=tmp_path,
            target_file="src/nonexistent.py",
            llm_client=fake_llm,
        )
        assert report.status == GenerationStatus.VALIDATION_ERROR
        assert "does not exist" in report.errors[0]


# ---------------------------------------------------------------------------
# TestGenerationAgent & SessionContext Integration
# ---------------------------------------------------------------------------

class TestTestGenerationAgent:
    def test_agent_run_updates_context(self, tmp_path):
        # Create a repo with a source file
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "service.py").write_text("def execute_task(): return True\n", encoding="utf-8")

        test_code = (
            "import pytest\n\n"
            "def test_execute_task():\n"
            "    assert True\n"
        )
        fake_llm = FakeLLMClient(response_content=f"```python\n{test_code}\n```")
        settings = Settings()

        agent = TestGenerationAgent(llm_client=fake_llm, settings=settings)
        ctx = SessionContext(repo_path=tmp_path)

        result = agent.run(ctx)

        assert result.success is True
        assert ctx.current_step == PipelineStep.TEST_GENERATION
        assert ctx.generation_report is not None
        assert isinstance(ctx.generation_report, GenerationReport)
        assert ctx.generation_report.status == GenerationStatus.SUCCESS
        assert ctx.tests_generated_count == 1
        assert len(ctx.generated_test_files) == 1
        assert ctx.timing.generation_started_at is not None

    def test_agent_fails_when_repo_path_is_none(self):
        fake_llm = FakeLLMClient()
        agent = TestGenerationAgent(llm_client=fake_llm, settings=Settings())
        ctx = SessionContext()  # repo_path is None

        result = agent.run(ctx)
        assert result.success is False
        assert "repo_path is not set" in result.message
        assert ctx.generation_report is not None
        assert ctx.generation_report.status == GenerationStatus.VALIDATION_ERROR

    def test_session_context_save_and_load_with_generation_report(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "worker.py").write_text("def work(): pass\n", encoding="utf-8")

        test_code = "def test_work(): assert True\n"
        fake_llm = FakeLLMClient(response_content=f"```python\n{test_code}\n```")
        agent = TestGenerationAgent(llm_client=fake_llm, settings=Settings())
        ctx = SessionContext(repo_path=tmp_path)
        agent.run(ctx)

        save_path = tmp_path / "session_ctx.json"
        ctx.save(save_path)
        assert save_path.exists()

        loaded_ctx = SessionContext.load(save_path)
        assert loaded_ctx.generation_report is not None
        assert loaded_ctx.generation_report.status == GenerationStatus.SUCCESS
        assert loaded_ctx.tests_generated_count == 1
        assert loaded_ctx.generated_test_files == ctx.generated_test_files
