"""
Safe test execution utilities for TestPilot AI.

Provides a subprocess-based test runner with:
  - environment detection (layout, venv, packaging)
  - safe command construction (no shell injection)
  - timeout enforcement
  - structured result capture

Design rules:
  - NEVER modifies the target repository.
  - NEVER installs dependencies automatically.
  - NEVER executes arbitrary LLM-generated shell commands.
  - Uses subprocess.run with explicit argument lists (no shell=True).
  - All return values are Pydantic models for serialisability.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from testpilot.utils.logging import get_logger

_log = get_logger("testpilot.utils.execution")

# Maximum bytes captured from stdout/stderr
_MAX_OUTPUT_BYTES = 8192

# Default subprocess timeout (seconds)
DEFAULT_TIMEOUT = 60.0


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ExecutionEnvironment(BaseModel):
    """
    Detected runtime characteristics of a Python repository.

    Populated by detect_environment().  All fields have safe defaults so
    a partial result is always valid.
    """

    repo_path: str
    """Absolute path to the repository root."""

    # ------------------------------------------------------------------
    # Project layout
    # ------------------------------------------------------------------
    layout: Literal["src", "flat", "unknown"] = "unknown"
    """
    'src'   — source lives under src/<package>/
    'flat'  — source lives directly under the repo root
    'unknown' — could not determine
    """

    has_pyproject_toml: bool = False
    has_setup_cfg: bool = False
    has_setup_py: bool = False
    has_conftest: bool = False

    # ------------------------------------------------------------------
    # Package discovery
    # ------------------------------------------------------------------
    detected_packages: list[str] = Field(default_factory=list)
    """Top-level Python package names found in the repository."""

    src_dir: str = ""
    """Relative path to the src directory if layout == 'src'."""

    # ------------------------------------------------------------------
    # Virtual environment
    # ------------------------------------------------------------------
    has_local_venv: bool = False
    local_venv_path: str = ""
    """Relative path to a local virtual environment (.venv / venv / env)."""

    # ------------------------------------------------------------------
    # Python / pytest availability
    # ------------------------------------------------------------------
    python_executable: str = ""
    """Absolute path to the Python executable that should be used."""

    pytest_available: bool = False
    coverage_available: bool = False

    # ------------------------------------------------------------------
    # Import check
    # ------------------------------------------------------------------
    package_importable: bool = False
    """True if at least one detected package can be imported in the env."""

    import_error: str = ""

    # ------------------------------------------------------------------
    # Sys.path additions needed
    # ------------------------------------------------------------------
    extra_pythonpath: list[str] = Field(default_factory=list)
    """
    Directories that should be added to PYTHONPATH / sys.path so the
    repository's packages can be imported during test execution.
    """

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ExecutionResult(BaseModel):
    """
    Result of a single subprocess execution.

    Returned by run_command() and run_pytest().
    """

    command: list[str]
    """The exact command that was executed (no secrets)."""

    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    combined_output: str = ""
    """stdout + stderr concatenated (trimmed to _MAX_OUTPUT_BYTES)."""

    duration_seconds: float = 0.0

    timed_out: bool = False
    """True when the subprocess was killed due to timeout."""

    success: bool = False
    """True when exit_code == 0 and timed_out == False."""

    error_detail: str = ""
    """Human-readable explanation when success is False."""

    # ------------------------------------------------------------------
    # Convenience computed fields (not serialised separately)
    # ------------------------------------------------------------------
    @property
    def has_output(self) -> bool:
        return bool(self.stdout.strip() or self.stderr.strip() or self.combined_output.strip())


# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------

def detect_environment(repo_path: Path) -> ExecutionEnvironment:
    """
    Inspect *repo_path* and return a structured ExecutionEnvironment.

    Does not modify the repository or install anything.
    """
    repo_path = repo_path.resolve()
    env = ExecutionEnvironment(repo_path=str(repo_path))

    if not repo_path.exists() or not repo_path.is_dir():
        env.errors.append(f"Repository path does not exist or is not a directory: {repo_path}")
        return env

    # ------------------------------------------------------------------
    # Detect packaging files
    # ------------------------------------------------------------------
    env.has_pyproject_toml = (repo_path / "pyproject.toml").exists()
    env.has_setup_cfg = (repo_path / "setup.cfg").exists()
    env.has_setup_py = (repo_path / "setup.py").exists()
    env.has_conftest = (repo_path / "conftest.py").exists()

    # ------------------------------------------------------------------
    # Detect project layout
    # ------------------------------------------------------------------
    src_dir = repo_path / "src"
    if src_dir.is_dir():
        env.layout = "src"
        env.src_dir = "src"
        # Packages are immediate subdirectories of src/ that contain __init__.py
        env.detected_packages = [
            d.name for d in src_dir.iterdir()
            if d.is_dir() and (d / "__init__.py").exists()
        ]
        env.extra_pythonpath = [str(src_dir)]
    else:
        env.layout = "flat"
        # Packages are immediate subdirectories of repo_root that contain __init__.py
        env.detected_packages = [
            d.name for d in repo_path.iterdir()
            if d.is_dir() and (d / "__init__.py").exists()
            and d.name not in ("tests", "test", ".venv", "venv", "__pycache__")
        ]
        if not env.detected_packages:
            env.warnings.append("No Python packages detected in repository root.")

    # ------------------------------------------------------------------
    # Detect local virtual environment
    # ------------------------------------------------------------------
    for venv_name in (".venv", "venv", "env", ".env"):
        candidate = repo_path / venv_name
        if candidate.is_dir() and (
            (candidate / "pyvenv.cfg").exists()
            or (candidate / "Scripts" / "python.exe").exists()
            or (candidate / "bin" / "python").exists()
        ):
            env.has_local_venv = True
            env.local_venv_path = venv_name
            # Prefer the repo's own venv Python
            for python_path in (
                candidate / "Scripts" / "python.exe",
                candidate / "bin" / "python",
                candidate / "bin" / "python3",
            ):
                if python_path.exists():
                    env.python_executable = str(python_path)
                    break
            break

    # Fall back to the currently running Python
    if not env.python_executable:
        env.python_executable = sys.executable

    # ------------------------------------------------------------------
    # Check pytest / coverage availability
    # ------------------------------------------------------------------
    env.pytest_available = _tool_available(env.python_executable, "pytest")
    env.coverage_available = _tool_available(env.python_executable, "coverage")

    # ------------------------------------------------------------------
    # Check package importability
    # ------------------------------------------------------------------
    if env.detected_packages:
        pkg = env.detected_packages[0]
        importable, err = _check_importable(
            env.python_executable, pkg, extra_path=env.extra_pythonpath
        )
        env.package_importable = importable
        if not importable:
            env.import_error = err
            env.warnings.append(
                f"Package '{pkg}' cannot be imported: {err}. "
                "Tests may fail with ImportError."
            )
    else:
        env.package_importable = False

    return env


def _tool_available(python: str, tool: str) -> bool:
    """Return True if *tool* is runnable as `python -m <tool>`."""
    try:
        result = subprocess.run(
            [python, "-m", tool, "--version"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _check_importable(
    python: str, package: str, extra_path: list[str]
) -> tuple[bool, str]:
    """
    Check whether *package* is importable by running a tiny subprocess.
    Returns (True, "") on success or (False, error_message) on failure.
    """
    env_additions = ":".join(extra_path) if extra_path else ""
    code = f"import sys; sys.path[:0]={extra_path!r}; import {package}"
    try:
        result = subprocess.run(
            [python, "-c", code],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout or "unknown error").strip()[:200]
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


# ---------------------------------------------------------------------------
# Command runner
# ---------------------------------------------------------------------------

def run_command(
    command: list[str],
    *,
    cwd: Path,
    timeout: float = DEFAULT_TIMEOUT,
    extra_env: dict[str, str] | None = None,
) -> ExecutionResult:
    """
    Execute *command* in *cwd* and return a structured ExecutionResult.

    Parameters
    ----------
    command:
        Argument list (no shell=True).
    cwd:
        Working directory for the subprocess.
    timeout:
        Seconds before the subprocess is killed.
    extra_env:
        Extra environment variables merged into the current environment.
        Never pass secrets in extra_env.

    Notes
    -----
    stdout and stderr are captured and trimmed to _MAX_OUTPUT_BYTES each.
    The subprocess is NOT run with shell=True to prevent injection.
    """
    import os

    result = ExecutionResult(command=command)
    start = time.monotonic()

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        result.timed_out = True
        result.duration_seconds = round(time.monotonic() - start, 3)
        result.error_detail = f"Command timed out after {timeout}s."
        _log.warning("Command timed out: %s", command[0])
        return result
    except FileNotFoundError as exc:
        result.duration_seconds = round(time.monotonic() - start, 3)
        result.error_detail = f"Executable not found: {exc}"
        return result
    except Exception as exc:  # noqa: BLE001
        result.duration_seconds = round(time.monotonic() - start, 3)
        result.error_detail = f"Unexpected execution error: {exc}"
        return result

    result.duration_seconds = round(time.monotonic() - start, 3)
    result.exit_code = proc.returncode
    result.stdout = (proc.stdout or "")[:_MAX_OUTPUT_BYTES]
    result.stderr = (proc.stderr or "")[:_MAX_OUTPUT_BYTES]
    combined = result.stdout + result.stderr
    result.combined_output = combined[:_MAX_OUTPUT_BYTES]
    result.success = proc.returncode == 0
    if not result.success:
        result.error_detail = f"Exit code {proc.returncode}."
    return result


# ---------------------------------------------------------------------------
# Pytest-specific runner
# ---------------------------------------------------------------------------

def run_pytest(
    repo_path: Path,
    env: ExecutionEnvironment | None = None,
    *,
    extra_args: list[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    with_coverage: bool = False,
    coverage_source: str | None = None,
) -> ExecutionResult:
    """
    Run pytest against *repo_path* using the detected environment.

    Parameters
    ----------
    repo_path:
        Repository root (tests/ is discovered from here).
    env:
        Pre-detected ExecutionEnvironment.  If None, detect_environment() is
        called automatically.
    extra_args:
        Additional pytest arguments (e.g. ['-k', 'test_add']).
    timeout:
        Subprocess timeout in seconds.
    with_coverage:
        Add --cov arguments for coverage collection.
    coverage_source:
        Coverage source path (passed to --cov=<source>).

    Returns
    -------
    ExecutionResult
    """
    if env is None:
        env = detect_environment(repo_path)

    python = env.python_executable or sys.executable

    cmd = [python, "-m", "pytest", "--tb=short", "--no-header", "-q"]

    if with_coverage:
        src = coverage_source or (env.src_dir if env.src_dir else ".")
        cmd += [f"--cov={src}", "--cov-report=term-missing"]

    if extra_args:
        cmd.extend(extra_args)

    # Build PYTHONPATH so repo packages are importable
    extra_path_str = _build_pythonpath(env, repo_path)

    import os
    extra_env: dict[str, str] = {}
    if extra_path_str:
        existing = os.environ.get("PYTHONPATH", "")
        extra_env["PYTHONPATH"] = (
            f"{extra_path_str}{os.pathsep}{existing}" if existing else extra_path_str
        )

    return run_command(cmd, cwd=repo_path, timeout=timeout, extra_env=extra_env)


def _build_pythonpath(env: ExecutionEnvironment, repo_path: Path) -> str:
    """Build a PYTHONPATH string from extra_pythonpath entries."""
    import os
    parts: list[str] = []
    for rel in env.extra_pythonpath:
        abs_path = repo_path / rel if not Path(rel).is_absolute() else Path(rel)
        parts.append(str(abs_path.resolve()))
    return os.pathsep.join(parts)
