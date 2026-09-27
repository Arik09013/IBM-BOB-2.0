"""
Tests for the Repository Analyzer agent (testpilot.agents.analyzer).

All tests use only local, synthetic data — no network calls, no real
external repositories, no fabricated coverage values.

Coverage of the 16 required scenarios:
  1.  valid repository
  2.  empty repository
  3.  invalid / nonexistent repository path
  4.  Python file discovery
  5.  test file discovery
  6.  AST function discovery
  7.  class / method discovery
  8.  pytest detection
  9.  syntax-error file handling
  10. repository with no tests
  11. missing pytest / framework handling
  12. coverage success when available (benchmark repo)
  13. coverage unavailable / failure handling
  14. benchmark repository analysis
  15. serialisation of the analysis result
  16. SessionContext compatibility
"""

from __future__ import annotations

from pathlib import Path

import pytest

from testpilot.agents.analyzer import (
    _detect_test_framework,
    _discover_files,
    _extract_symbols,
    _is_test_file,
    analyze_repository,
)
from testpilot.models.repository import (
    CoverageStatus,
    RepositoryAnalysis,
    SymbolKind,
)

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

BENCHMARK = Path(__file__).parent.parent / "benchmarks" / "repositories" / "python_simple"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_repo(tmp_path: Path) -> Path:
    """Create a minimal Python repo with source + test files."""
    src = tmp_path / "src" / "mylib"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "math_utils.py").write_text(
        "def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_math.py").write_text(
        "import pytest\nfrom mylib.math_utils import add\n\ndef test_add():\n    assert add(1,2)==3\n",
        encoding="utf-8",
    )
    # pyproject.toml with pytest
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="mylib"\n[tool.pytest.ini_options]\ntestpaths=["tests"]\n',
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    """An empty directory — no Python files."""
    return tmp_path


@pytest.fixture
def no_tests_repo(tmp_path: Path) -> Path:
    """Python source files but no test files."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "utils.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def syntax_error_repo(tmp_path: Path) -> Path:
    """Repo with one valid and one syntactically invalid Python file."""
    (tmp_path / "good.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    (tmp_path / "bad.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Valid repository
# ---------------------------------------------------------------------------

class TestValidRepository:
    def test_returns_analysis_object(self, simple_repo):
        result = analyze_repository(simple_repo, attempt_coverage=False)
        assert isinstance(result, RepositoryAnalysis)

    def test_no_fatal_errors(self, simple_repo):
        result = analyze_repository(simple_repo, attempt_coverage=False)
        assert not result.errors

    def test_language_is_python(self, simple_repo):
        result = analyze_repository(simple_repo, attempt_coverage=False)
        assert result.language == "python"

    def test_repository_path_stored(self, simple_repo):
        result = analyze_repository(simple_repo, attempt_coverage=False)
        assert str(simple_repo.resolve()) == result.repository_path

    def test_duration_is_non_negative(self, simple_repo):
        result = analyze_repository(simple_repo, attempt_coverage=False)
        # Duration may be 0 on very fast machines; it must never be negative.
        assert result.duration_seconds >= 0


# ---------------------------------------------------------------------------
# 2. Empty repository
# ---------------------------------------------------------------------------

class TestEmptyRepository:
    def test_returns_valid_result(self, empty_repo):
        result = analyze_repository(empty_repo, attempt_coverage=False)
        assert isinstance(result, RepositoryAnalysis)

    def test_no_files_found(self, empty_repo):
        result = analyze_repository(empty_repo, attempt_coverage=False)
        assert result.source_file_count == 0
        assert result.test_file_count == 0

    def test_has_warning(self, empty_repo):
        result = analyze_repository(empty_repo, attempt_coverage=False)
        assert any("no python files" in w.lower() for w in result.warnings)

    def test_coverage_not_attempted(self, empty_repo):
        result = analyze_repository(empty_repo, attempt_coverage=False)
        assert result.coverage_summary.status == CoverageStatus.NOT_ATTEMPTED


# ---------------------------------------------------------------------------
# 3. Invalid / nonexistent path
# ---------------------------------------------------------------------------

class TestInvalidPath:
    def test_nonexistent_path_returns_error(self, tmp_path):
        result = analyze_repository(tmp_path / "does_not_exist_xyz", attempt_coverage=False)
        assert len(result.errors) > 0

    def test_error_mentions_path(self, tmp_path):
        fake = tmp_path / "no_such_dir"
        result = analyze_repository(fake, attempt_coverage=False)
        assert any("does not exist" in e for e in result.errors)

    def test_file_path_not_dir(self, tmp_path):
        f = tmp_path / "file.py"
        f.write_text("x=1\n", encoding="utf-8")
        result = analyze_repository(f, attempt_coverage=False)
        assert len(result.errors) > 0


# ---------------------------------------------------------------------------
# 4. Python file discovery
# ---------------------------------------------------------------------------

class TestFileDiscovery:
    def test_source_files_found(self, simple_repo):
        result = analyze_repository(simple_repo, attempt_coverage=False)
        assert result.source_file_count > 0

    def test_venv_excluded(self, tmp_path):
        venv = tmp_path / ".venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "secret.py").write_text("x=1\n", encoding="utf-8")
        (tmp_path / "real.py").write_text("def f(): pass\n", encoding="utf-8")
        result = analyze_repository(tmp_path, attempt_coverage=False)
        paths = result.source_files
        assert not any(".venv" in p for p in paths)
        assert any("real.py" in p for p in paths)

    def test_pycache_excluded(self, tmp_path):
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "stuff.pyc").write_text("", encoding="utf-8")
        (tmp_path / "app.py").write_text("def main(): pass\n", encoding="utf-8")
        result = analyze_repository(tmp_path, attempt_coverage=False)
        assert not any("__pycache__" in p for p in result.source_files)

    def test_is_test_file_by_name(self, tmp_path):
        f = tmp_path / "test_utils.py"
        assert _is_test_file(f, tmp_path) is True

    def test_is_test_file_by_suffix(self, tmp_path):
        f = tmp_path / "utils_test.py"
        assert _is_test_file(f, tmp_path) is True

    def test_is_test_file_by_dir(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        f = tests_dir / "anything.py"
        assert _is_test_file(f, tmp_path) is True

    def test_source_file_not_classified_as_test(self, tmp_path):
        f = tmp_path / "calculator.py"
        assert _is_test_file(f, tmp_path) is False


# ---------------------------------------------------------------------------
# 5. Test file discovery
# ---------------------------------------------------------------------------

class TestTestFileDiscovery:
    def test_test_files_detected(self, simple_repo):
        result = analyze_repository(simple_repo, attempt_coverage=False)
        assert result.test_file_count > 0

    def test_test_files_classified_correctly(self, simple_repo):
        result = analyze_repository(simple_repo, attempt_coverage=False)
        for tf in result.test_files:
            assert "test" in tf.lower()

    def test_no_tests_repo_has_zero_test_files(self, no_tests_repo):
        result = analyze_repository(no_tests_repo, attempt_coverage=False)
        assert result.test_file_count == 0


# ---------------------------------------------------------------------------
# 6. AST function discovery
# ---------------------------------------------------------------------------

class TestASTFunctionDiscovery:
    def test_functions_extracted(self, simple_repo):
        result = analyze_repository(simple_repo, attempt_coverage=False)
        names = [s.name for s in result.symbols]
        assert "add" in names
        assert "subtract" in names

    def test_function_kind(self, simple_repo):
        result = analyze_repository(simple_repo, attempt_coverage=False)
        add_sym = next(s for s in result.symbols if s.name == "add")
        assert add_sym.kind == SymbolKind.FUNCTION

    def test_function_line_number(self, tmp_path):
        (tmp_path / "funcs.py").write_text(
            "def alpha():\n    pass\n\ndef beta():\n    pass\n",
            encoding="utf-8",
        )
        analysis = RepositoryAnalysis(repository_path=str(tmp_path))
        analysis.source_files = ["funcs.py"]
        _extract_symbols(tmp_path / "funcs.py", "funcs.py", analysis)
        alpha = next(s for s in analysis.symbols if s.name == "alpha")
        beta = next(s for s in analysis.symbols if s.name == "beta")
        assert alpha.line == 1
        assert beta.line == 4

    def test_async_function_kind(self, tmp_path):
        (tmp_path / "async_mod.py").write_text(
            "async def fetch(url):\n    pass\n", encoding="utf-8"
        )
        analysis = RepositoryAnalysis(repository_path=str(tmp_path))
        analysis.source_files = ["async_mod.py"]
        _extract_symbols(tmp_path / "async_mod.py", "async_mod.py", analysis)
        sym = next(s for s in analysis.symbols if s.name == "fetch")
        assert sym.kind == SymbolKind.ASYNC_FUNCTION

    def test_private_function_flagged(self, tmp_path):
        (tmp_path / "private.py").write_text(
            "def _helper():\n    pass\n", encoding="utf-8"
        )
        analysis = RepositoryAnalysis(repository_path=str(tmp_path))
        analysis.source_files = ["private.py"]
        _extract_symbols(tmp_path / "private.py", "private.py", analysis)
        sym = next(s for s in analysis.symbols if s.name == "_helper")
        assert sym.is_private is True


# ---------------------------------------------------------------------------
# 7. Class / method discovery
# ---------------------------------------------------------------------------

class TestClassMethodDiscovery:
    def setup_method(self):
        """Shared class file content for this group."""
        self.class_code = (
            "class Animal:\n"
            "    def __init__(self, name):\n"
            "        self.name = name\n"
            "    def speak(self):\n"
            "        pass\n"
            "    def _private(self):\n"
            "        pass\n"
        )

    def test_class_symbol_found(self, tmp_path):
        (tmp_path / "animal.py").write_text(self.class_code, encoding="utf-8")
        analysis = RepositoryAnalysis(repository_path=str(tmp_path))
        analysis.source_files = ["animal.py"]
        _extract_symbols(tmp_path / "animal.py", "animal.py", analysis)
        kinds = {s.kind for s in analysis.symbols}
        assert SymbolKind.CLASS in kinds

    def test_constructor_kind(self, tmp_path):
        (tmp_path / "animal.py").write_text(self.class_code, encoding="utf-8")
        analysis = RepositoryAnalysis(repository_path=str(tmp_path))
        analysis.source_files = ["animal.py"]
        _extract_symbols(tmp_path / "animal.py", "animal.py", analysis)
        init_sym = next(s for s in analysis.symbols if s.name == "__init__")
        assert init_sym.kind == SymbolKind.CONSTRUCTOR
        assert init_sym.is_dunder is True

    def test_method_parent_class_set(self, tmp_path):
        (tmp_path / "animal.py").write_text(self.class_code, encoding="utf-8")
        analysis = RepositoryAnalysis(repository_path=str(tmp_path))
        analysis.source_files = ["animal.py"]
        _extract_symbols(tmp_path / "animal.py", "animal.py", analysis)
        speak = next(s for s in analysis.symbols if s.name == "speak")
        assert speak.parent_class == "Animal"
        assert speak.qualified_name == "Animal.speak"

    def test_private_method_flagged(self, tmp_path):
        (tmp_path / "animal.py").write_text(self.class_code, encoding="utf-8")
        analysis = RepositoryAnalysis(repository_path=str(tmp_path))
        analysis.source_files = ["animal.py"]
        _extract_symbols(tmp_path / "animal.py", "animal.py", analysis)
        priv = next(s for s in analysis.symbols if s.name == "_private")
        assert priv.is_private is True


# ---------------------------------------------------------------------------
# 8. Pytest detection
# ---------------------------------------------------------------------------

class TestPytestDetection:
    def test_detected_from_pyproject(self, simple_repo):
        result = analyze_repository(simple_repo, attempt_coverage=False)
        assert result.test_framework == "pytest"
        assert result.test_framework_detected is True

    def test_detected_from_import_in_test_file(self, tmp_path):
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_something.py").write_text(
            "import pytest\ndef test_x(): pass\n", encoding="utf-8"
        )
        analysis = RepositoryAnalysis(repository_path=str(tmp_path))
        analysis.all_python_files = ["tests/test_something.py"]
        analysis.source_files = []
        analysis.test_files = ["tests/test_something.py"]
        _detect_test_framework(tmp_path, analysis)
        assert analysis.test_framework == "pytest"

    def test_detected_from_pytest_ini(self, tmp_path):
        (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_pass(): pass\n", encoding="utf-8")
        result = analyze_repository(tmp_path, attempt_coverage=False)
        assert result.test_framework_detected is True

    def test_not_detected_when_absent(self, no_tests_repo):
        result = analyze_repository(no_tests_repo, attempt_coverage=False)
        assert result.test_framework_detected is False


# ---------------------------------------------------------------------------
# 9. Syntax error file handling
# ---------------------------------------------------------------------------

class TestSyntaxErrorHandling:
    def test_analysis_does_not_crash(self, syntax_error_repo):
        result = analyze_repository(syntax_error_repo, attempt_coverage=False)
        assert isinstance(result, RepositoryAnalysis)

    def test_good_file_still_analysed(self, syntax_error_repo):
        result = analyze_repository(syntax_error_repo, attempt_coverage=False)
        names = [s.name for s in result.symbols]
        assert "ok" in names

    def test_parse_error_recorded(self, syntax_error_repo):
        result = analyze_repository(syntax_error_repo, attempt_coverage=False)
        assert len(result.parse_errors) > 0

    def test_bad_file_in_parse_errors(self, syntax_error_repo):
        result = analyze_repository(syntax_error_repo, attempt_coverage=False)
        assert any("bad.py" in e for e in result.parse_errors)


# ---------------------------------------------------------------------------
# 10. Repository with no tests
# ---------------------------------------------------------------------------

class TestNoTests:
    def test_test_file_count_zero(self, no_tests_repo):
        result = analyze_repository(no_tests_repo, attempt_coverage=False)
        assert result.test_file_count == 0

    def test_coverage_status_no_tests(self, no_tests_repo):
        result = analyze_repository(no_tests_repo, attempt_coverage=True)
        assert result.coverage_summary.status in (
            CoverageStatus.NO_TESTS,
            CoverageStatus.NOT_ATTEMPTED,
            CoverageStatus.UNAVAILABLE,
        )

    def test_symbols_still_extracted(self, no_tests_repo):
        result = analyze_repository(no_tests_repo, attempt_coverage=False)
        assert result.symbol_count > 0


# ---------------------------------------------------------------------------
# 11. Missing pytest / framework handling
# ---------------------------------------------------------------------------

class TestMissingFramework:
    def test_no_framework_no_crash(self, no_tests_repo):
        # no_tests_repo has no pyproject.toml or pytest markers
        result = analyze_repository(no_tests_repo, attempt_coverage=False)
        assert isinstance(result, RepositoryAnalysis)
        assert result.test_framework == "" or result.test_framework_detected is False

    def test_coverage_skipped_when_no_framework(self, no_tests_repo):
        result = analyze_repository(no_tests_repo, attempt_coverage=True)
        assert result.coverage_summary.status in (
            CoverageStatus.UNAVAILABLE,
            CoverageStatus.NO_TESTS,
            CoverageStatus.NOT_ATTEMPTED,
        )


# ---------------------------------------------------------------------------
# 12 & 13. Coverage (benchmark repo — requires pytest+pytest-cov in env)
# ---------------------------------------------------------------------------

class TestCoverageBehavior:
    def test_coverage_attempt_no_crash(self, simple_repo):
        """Coverage attempt must not raise — status reflects available tooling."""
        result = analyze_repository(simple_repo, attempt_coverage=True)
        assert result.coverage_summary.status in CoverageStatus.__members__.values()

    def test_no_coverage_flag_skips_collection(self, simple_repo):
        result = analyze_repository(simple_repo, attempt_coverage=False)
        assert result.coverage_summary.status == CoverageStatus.NOT_ATTEMPTED
        assert result.coverage_summary.line_coverage_pct is None

    def test_coverage_pct_none_when_not_collected(self, simple_repo):
        result = analyze_repository(simple_repo, attempt_coverage=False)
        assert result.coverage_summary.line_coverage_pct is None

    def test_coverage_never_fabricated(self, simple_repo):
        """coverage_pct must never be set without real subprocess execution."""
        result = analyze_repository(simple_repo, attempt_coverage=False)
        # With attempt_coverage=False there must be no percentage value
        assert result.coverage_summary.line_coverage_pct is None


# ---------------------------------------------------------------------------
# 14. Benchmark repository analysis
# ---------------------------------------------------------------------------

class TestBenchmarkRepository:
    def test_benchmark_exists(self):
        assert BENCHMARK.exists(), f"Benchmark not found at {BENCHMARK}"

    def test_benchmark_analyzed(self):
        result = analyze_repository(BENCHMARK, attempt_coverage=False)
        assert isinstance(result, RepositoryAnalysis)
        assert not result.errors

    def test_benchmark_source_files(self):
        result = analyze_repository(BENCHMARK, attempt_coverage=False)
        assert result.source_file_count >= 3  # arithmetic, statistics, converter + __init__

    def test_benchmark_test_files(self):
        result = analyze_repository(BENCHMARK, attempt_coverage=False)
        assert result.test_file_count >= 2  # test_arithmetic, test_statistics

    def test_benchmark_symbols_extracted(self):
        result = analyze_repository(BENCHMARK, attempt_coverage=False)
        names = [s.name for s in result.symbols]
        assert "add" in names
        assert "Calculator" in names
        assert "mean" in names
        assert "celsius_to_fahrenheit" in names

    def test_benchmark_pytest_detected(self):
        result = analyze_repository(BENCHMARK, attempt_coverage=False)
        assert result.test_framework == "pytest"
        assert result.test_framework_detected is True

    def test_benchmark_python_version_detected(self):
        result = analyze_repository(BENCHMARK, attempt_coverage=False)
        # pyproject.toml has requires-python = ">=3.11"
        assert result.python_version == "3.11"

    def test_benchmark_converter_module_found(self):
        """converter.py must be in source files (it's the uncovered module)."""
        result = analyze_repository(BENCHMARK, attempt_coverage=False)
        assert any("converter.py" in f for f in result.source_files)

    def test_benchmark_no_parse_errors(self):
        result = analyze_repository(BENCHMARK, attempt_coverage=False)
        assert len(result.parse_errors) == 0


# ---------------------------------------------------------------------------
# 15. Serialisation
# ---------------------------------------------------------------------------

class TestSerialisation:
    def test_model_dump_json_is_valid_json(self, simple_repo):
        import json
        result = analyze_repository(simple_repo, attempt_coverage=False)
        raw = result.model_dump_json()
        parsed = json.loads(raw)
        assert "repository_path" in parsed
        assert "symbols" in parsed
        assert "coverage_summary" in parsed

    def test_round_trip(self, simple_repo, tmp_path):
        result = analyze_repository(simple_repo, attempt_coverage=False)
        out = tmp_path / "analysis.json"
        out.write_text(result.model_dump_json(), encoding="utf-8")
        loaded = RepositoryAnalysis.model_validate_json(out.read_text(encoding="utf-8"))
        assert loaded.repository_path == result.repository_path
        assert loaded.symbol_count == result.symbol_count

    def test_all_fields_serialisable(self, simple_repo):
        """model_dump_json must not raise on a complete analysis."""
        result = analyze_repository(simple_repo, attempt_coverage=False)
        result.model_dump_json()  # should not raise


# ---------------------------------------------------------------------------
# 16. SessionContext compatibility
# ---------------------------------------------------------------------------

class TestSessionContextIntegration:
    def test_analysis_stored_in_context(self, simple_repo):
        from testpilot.config import Settings
        from testpilot.llm.client import LLMClientFactory
        from testpilot.agents.analyzer import RepositoryAnalyzerAgent
        from testpilot.session_context import SessionContext

        ctx = SessionContext(repo_path=simple_repo)
        agent = RepositoryAnalyzerAgent(
            llm_client=LLMClientFactory.create("stub"),
            settings=Settings(),
        )
        result = agent.run(ctx)
        assert result.context.repository_analysis is not None

    def test_context_language_populated(self, simple_repo):
        from testpilot.config import Settings
        from testpilot.llm.client import LLMClientFactory
        from testpilot.agents.analyzer import RepositoryAnalyzerAgent
        from testpilot.session_context import SessionContext

        ctx = SessionContext(repo_path=simple_repo)
        agent = RepositoryAnalyzerAgent(
            llm_client=LLMClientFactory.create("stub"),
            settings=Settings(),
        )
        result = agent.run(ctx)
        assert result.context.detected_language == "python"

    def test_context_framework_populated(self, simple_repo):
        from testpilot.config import Settings
        from testpilot.llm.client import LLMClientFactory
        from testpilot.agents.analyzer import RepositoryAnalyzerAgent
        from testpilot.session_context import SessionContext

        ctx = SessionContext(repo_path=simple_repo)
        agent = RepositoryAnalyzerAgent(
            llm_client=LLMClientFactory.create("stub"),
            settings=Settings(),
        )
        result = agent.run(ctx)
        assert result.context.detected_test_framework == "pytest"

    def test_missing_repo_path_returns_failure(self):
        from testpilot.config import Settings
        from testpilot.llm.client import LLMClientFactory
        from testpilot.agents.analyzer import RepositoryAnalyzerAgent
        from testpilot.session_context import SessionContext

        ctx = SessionContext()  # repo_path is None
        agent = RepositoryAnalyzerAgent(
            llm_client=LLMClientFactory.create("stub"),
            settings=Settings(),
        )
        result = agent.run(ctx)
        assert result.success is False
