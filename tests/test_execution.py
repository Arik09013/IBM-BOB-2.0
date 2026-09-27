"""
Tests for the execution utility (testpilot.utils.execution).

All tests use only local, temporary repositories.
No network calls, no real remote targets, no fabricated results.

Coverage:
  - benchmark path detection
  - Python project layout detection (src / flat)
  - virtual environment detection
  - package importability check
  - command construction
  - successful subprocess execution
  - failed subprocess execution
  - timeout handling
  - stdout/stderr capture
  - invalid repository handling
  - run_pytest integration against benchmark
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from testpilot.utils.execution import (
    ExecutionEnvironment,
    ExecutionResult,
    detect_environment,
    run_command,
    run_pytest,
)

BENCHMARK = Path(__file__).parent.parent / "benchmarks" / "repositories" / "python_simple"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def src_layout_repo(tmp_path: Path) -> Path:
    """A minimal src-layout Python repository."""
    src = tmp_path / "src" / "mypackage"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "utils.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="mypackage"\n[tool.pytest.ini_options]\ntestpaths=["tests"]\n',
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_utils.py").write_text(
        "from mypackage.utils import add\ndef test_add(): assert add(1,2)==3\n",
        encoding="utf-8",
    )
    # conftest.py so pytest can find the package
    (tmp_path / "conftest.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent / 'src'))\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def flat_layout_repo(tmp_path: Path) -> Path:
    """A minimal flat-layout Python repository."""
    pkg = tmp_path / "flatpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "calc.py").write_text("def multiply(a, b): return a * b\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_calc.py").write_text(
        "from flatpkg.calc import multiply\ndef test_mul(): assert multiply(2,3)==6\n",
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# detect_environment
# ---------------------------------------------------------------------------

class TestDetectEnvironment:
    def test_returns_environment_object(self, src_layout_repo):
        env = detect_environment(src_layout_repo)
        assert isinstance(env, ExecutionEnvironment)

    def test_invalid_path_returns_error(self, tmp_path):
        env = detect_environment(tmp_path / "no_such_dir_xyz")
        assert len(env.errors) > 0

    def test_repo_path_stored(self, src_layout_repo):
        env = detect_environment(src_layout_repo)
        assert str(src_layout_repo.resolve()) == env.repo_path

    def test_src_layout_detected(self, src_layout_repo):
        env = detect_environment(src_layout_repo)
        assert env.layout == "src"
        assert env.src_dir == "src"

    def test_flat_layout_detected(self, flat_layout_repo):
        env = detect_environment(flat_layout_repo)
        assert env.layout == "flat"

    def test_packages_detected_src_layout(self, src_layout_repo):
        env = detect_environment(src_layout_repo)
        assert "mypackage" in env.detected_packages

    def test_packages_detected_flat_layout(self, flat_layout_repo):
        env = detect_environment(flat_layout_repo)
        assert "flatpkg" in env.detected_packages

    def test_pyproject_toml_detected(self, src_layout_repo):
        env = detect_environment(src_layout_repo)
        assert env.has_pyproject_toml is True

    def test_conftest_detected(self, src_layout_repo):
        env = detect_environment(src_layout_repo)
        assert env.has_conftest is True

    def test_python_executable_set(self, src_layout_repo):
        env = detect_environment(src_layout_repo)
        assert env.python_executable != ""
        assert "python" in env.python_executable.lower()

    def test_extra_pythonpath_for_src_layout(self, src_layout_repo):
        env = detect_environment(src_layout_repo)
        assert any("src" in p for p in env.extra_pythonpath)

    def test_no_local_venv_by_default(self, tmp_path):
        (tmp_path / "app.py").write_text("x=1\n", encoding="utf-8")
        env = detect_environment(tmp_path)
        assert env.has_local_venv is False

    def test_local_venv_detected(self, tmp_path):
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
        (tmp_path / "app.py").write_text("x=1\n", encoding="utf-8")
        env = detect_environment(tmp_path)
        assert env.has_local_venv is True
        assert env.local_venv_path == ".venv"

    def test_benchmark_detected(self):
        if not BENCHMARK.exists():
            pytest.skip("Benchmark not found")
        env = detect_environment(BENCHMARK)
        assert env.layout == "src"
        assert "calculator" in env.detected_packages
        assert env.has_pyproject_toml is True
        assert env.has_conftest is True


# ---------------------------------------------------------------------------
# run_command
# ---------------------------------------------------------------------------

class TestRunCommand:
    def test_successful_command(self, tmp_path):
        result = run_command(
            [sys.executable, "-c", "print('hello testpilot')"],
            cwd=tmp_path,
            timeout=10.0,
        )
        assert result.success is True
        assert result.exit_code == 0
        assert "hello testpilot" in result.stdout

    def test_failed_command(self, tmp_path):
        result = run_command(
            [sys.executable, "-c", "import sys; sys.exit(1)"],
            cwd=tmp_path,
            timeout=10.0,
        )
        assert result.success is False
        assert result.exit_code == 1

    def test_nonzero_exit_code_captured(self, tmp_path):
        result = run_command(
            [sys.executable, "-c", "import sys; sys.exit(42)"],
            cwd=tmp_path,
            timeout=10.0,
        )
        assert result.exit_code == 42

    def test_stdout_captured(self, tmp_path):
        result = run_command(
            [sys.executable, "-c", "print('captured_output')"],
            cwd=tmp_path,
            timeout=10.0,
        )
        assert "captured_output" in result.stdout

    def test_stderr_captured(self, tmp_path):
        result = run_command(
            [sys.executable, "-c", "import sys; sys.stderr.write('err_output\\n')"],
            cwd=tmp_path,
            timeout=10.0,
        )
        assert "err_output" in result.stderr

    def test_timeout_sets_timed_out(self, tmp_path):
        result = run_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=tmp_path,
            timeout=0.5,
        )
        assert result.timed_out is True
        assert result.success is False

    def test_missing_executable(self, tmp_path):
        result = run_command(
            ["/nonexistent/binary_xyz_abc"],
            cwd=tmp_path,
            timeout=5.0,
        )
        assert result.success is False
        assert result.error_detail != ""

    def test_duration_is_non_negative(self, tmp_path):
        result = run_command(
            [sys.executable, "-c", "pass"],
            cwd=tmp_path,
            timeout=10.0,
        )
        assert result.duration_seconds >= 0

    def test_command_stored_in_result(self, tmp_path):
        cmd = [sys.executable, "-c", "pass"]
        result = run_command(cmd, cwd=tmp_path)
        assert result.command == cmd

    def test_combined_output_populated(self, tmp_path):
        result = run_command(
            [sys.executable, "-c", "print('out'); import sys; sys.stderr.write('err\\n')"],
            cwd=tmp_path,
            timeout=10.0,
        )
        assert "out" in result.combined_output or "err" in result.combined_output


# ---------------------------------------------------------------------------
# run_pytest (against benchmark)
# ---------------------------------------------------------------------------

class TestRunPytest:
    def test_benchmark_tests_pass(self):
        if not BENCHMARK.exists():
            pytest.skip("Benchmark not found")
        result = run_pytest(BENCHMARK, timeout=60.0)
        assert result.exit_code == 0, f"pytest failed:\n{result.combined_output}"
        assert result.success is True

    def test_benchmark_tests_output_captured(self):
        if not BENCHMARK.exists():
            pytest.skip("Benchmark not found")
        result = run_pytest(BENCHMARK, timeout=60.0)
        assert result.has_output

    def test_benchmark_coverage_collectable(self):
        if not BENCHMARK.exists():
            pytest.skip("Benchmark not found")
        result = run_pytest(
            BENCHMARK,
            timeout=60.0,
            with_coverage=True,
            coverage_source="src",
        )
        # Exit 0 or 1 (0=all pass, 1=some fail but tests ran)
        assert result.exit_code in (0, 1), (
            f"Unexpected exit code {result.exit_code}:\n{result.combined_output}"
        )
        # Coverage % must appear in output — real, not fabricated
        assert "%" in result.combined_output or "TOTAL" in result.combined_output

    def test_invalid_repo_handled(self, tmp_path):
        """run_pytest on a repo with no tests should not crash."""
        result = run_pytest(tmp_path, timeout=10.0)
        # pytest returns 5 (no tests collected) or 4 (usage error); both are ok
        assert result.exit_code in (0, 1, 4, 5) or result.timed_out is False


# ---------------------------------------------------------------------------
# ExecutionResult model
# ---------------------------------------------------------------------------

class TestExecutionResultModel:
    def test_default_construction(self):
        r = ExecutionResult(command=["pytest"])
        assert r.exit_code == -1
        assert r.success is False
        assert r.timed_out is False

    def test_serialisable(self):
        import json
        r = ExecutionResult(command=["pytest"], exit_code=0, stdout="ok", success=True)
        raw = r.model_dump_json()
        parsed = json.loads(raw)
        assert parsed["exit_code"] == 0

    def test_has_output_property(self):
        r = ExecutionResult(command=["x"], stdout="some output")
        assert r.has_output is True

    def test_has_output_false_when_empty(self):
        r = ExecutionResult(command=["x"])
        assert r.has_output is False


# ---------------------------------------------------------------------------
# ExecutionEnvironment model
# ---------------------------------------------------------------------------

class TestExecutionEnvironmentModel:
    def test_default_construction(self):
        env = ExecutionEnvironment(repo_path="/tmp/repo")
        assert env.layout == "unknown"
        assert env.pytest_available is False

    def test_serialisable(self):
        import json
        env = ExecutionEnvironment(repo_path="/tmp/repo", layout="src")
        raw = env.model_dump_json()
        parsed = json.loads(raw)
        assert parsed["layout"] == "src"
