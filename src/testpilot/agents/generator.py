"""
Test Generation Agent for TestPilot AI.

Analyzes a target Python source file/module along with repository context
and uses an LLM to generate valid, idiomatic pytest test code.

Design rules:
  - Reuses BaseAgent and SessionContext abstractions.
  - Reuses BaseLLMClient and LLMClientFactory for provider-agnostic inference.
  - Distinguishes generated test code from conversational/explanatory text.
  - AST-parses all generated code before declaring success (catches syntax errors
    and verifies that actual test_* functions or Test* classes are present).
  - Protects against overwriting human-written tests by default.
  - Never makes unauthorized external network calls (respects provider configuration).
"""

from __future__ import annotations

import ast
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from testpilot.agents.base import AgentResult, BaseAgent
from testpilot.models.generation import (
    GeneratedTestCase,
    GeneratedTestFile,
    GenerationReport,
    GenerationStatus,
)
from testpilot.session_context import PipelineStep
from testpilot.utils.logging import get_logger

if TYPE_CHECKING:
    from testpilot.config import Settings
    from testpilot.llm.client import BaseLLMClient, LLMMessage
    from testpilot.models.repository import RepositoryAnalysis
    from testpilot.session_context import SessionContext

_log = get_logger("testpilot.agents.generator")

# Maximum size (bytes) of source code included in LLM prompt context
_MAX_PROMPT_SOURCE_BYTES = 16384

# Maximum size (bytes) of existing test sample included in LLM prompt context
_MAX_TEST_SAMPLE_BYTES = 4096


# ---------------------------------------------------------------------------
# Code extraction & AST validation helpers
# ---------------------------------------------------------------------------

def extract_test_code_and_explanation(response_text: str) -> tuple[str, str]:
    """
    Separate executable Python test code from markdown explanations.

    Extracts code enclosed in ```python ... ``` or ``` ... ``` fences.
    If multiple code blocks are found, prefers the one containing test definitions.
    If no fences are found, attempts to determine whether the whole response
    is raw Python code or explanatory text.

    Returns
    -------
    tuple[str, str]
        (clean_code, explanation)
    """
    if not response_text or not response_text.strip():
        return "", ""

    # 1. Match all fenced code blocks: ```[python]?\n...\n```
    fenced_blocks = re.findall(
        r"```(?:python|py)?\s*\n(.*?)```",
        response_text,
        re.DOTALL | re.IGNORECASE,
    )

    if fenced_blocks:
        # If any block contains test definitions, choose the best one
        test_blocks = [b.strip() for b in fenced_blocks if "def test_" in b or "class Test" in b]
        if test_blocks:
            code = "\n\n".join(test_blocks)
        else:
            # Fall back to the longest block
            code = max(fenced_blocks, key=len).strip()

        # Explanation is text outside all fenced code blocks
        explanation = re.sub(
            r"```(?:python|py)?\s*\n.*?```",
            "",
            response_text,
            flags=re.DOTALL | re.IGNORECASE,
        ).strip()

        return code, explanation

    # 2. No code blocks found: check if entire response looks like raw Python test code
    stripped = response_text.strip()
    if "def test_" in stripped or "import pytest" in stripped:
        return stripped, ""

    # Otherwise treat the entire response as non-code explanation
    return "", stripped


def validate_generated_code(code: str) -> tuple[bool, list[GeneratedTestCase], str | None]:
    """
    Validate Python syntax and verify the presence of pytest test functions.

    Uses ast.parse() to guarantee syntax validity and extracts metadata for
    each discovered test case.

    Returns
    -------
    tuple[bool, list[GeneratedTestCase], str | None]
        (is_valid, test_cases, validation_error)
    """
    if not code or not code.strip():
        return False, [], "Generated code is empty."

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, [], f"Syntax error at line {exc.lineno}: {exc.msg}"
    except Exception as exc:  # noqa: BLE001
        return False, [], f"AST parse error: {exc}"

    test_cases: list[GeneratedTestCase] = []

    for node in tree.body:
        # Top-level test functions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_") or node.name.endswith("_test"):
                target = node.name.removeprefix("test_").removesuffix("_test")
                has_doc = (
                    bool(node.body)
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                )
                test_cases.append(
                    GeneratedTestCase(
                        name=node.name,
                        target_function=target,
                        line=node.lineno,
                        is_async=isinstance(node, ast.AsyncFunctionDef),
                        has_docstring=has_doc,
                    )
                )

        # Test classes (e.g. class TestCalculator)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith("test_") or item.name.endswith("_test"):
                        target = item.name.removeprefix("test_").removesuffix("_test")
                        has_doc = (
                            bool(item.body)
                            and isinstance(item.body[0], ast.Expr)
                            and isinstance(item.body[0].value, ast.Constant)
                            and isinstance(item.body[0].value.value, str)
                        )
                        test_cases.append(
                            GeneratedTestCase(
                                name=f"{node.name}.{item.name}",
                                target_function=target,
                                line=item.lineno,
                                is_async=isinstance(item, ast.AsyncFunctionDef),
                                has_docstring=has_doc,
                            )
                        )

    if not test_cases:
        return False, [], "No test functions (e.g. 'def test_*') or Test classes found in generated code."

    return True, test_cases, None


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def build_generation_prompt(
    target_source: str,
    target_file_rel: str,
    *,
    repo_analysis: RepositoryAnalysis | None = None,
    existing_test_sample: str | None = None,
    target_symbols: list[str] | None = None,
) -> list[LLMMessage]:
    """
    Construct structured system and user prompts for the LLM.

    Includes target source code, import hints, and existing testing style
    to produce accurate, runnable pytest code.
    """
    from testpilot.llm.client import LLMMessage

    framework = "pytest"
    python_ver = "3.11"
    if repo_analysis:
        framework = repo_analysis.test_framework or "pytest"
        python_ver = repo_analysis.python_version or "3.11"

    system_content = (
        "You are an expert Python test engineer and software testing specialist.\n"
        "Your task is to write high-quality, comprehensive, and runnable pytest test suites "
        "for the provided Python module.\n\n"
        "Guidelines:\n"
        f"1. Use {framework} with Python {python_ver}+ standards.\n"
        "2. Generate complete, valid, executable Python code with no placeholders or ellipses (...).\n"
        "3. Import the functions and classes under test accurately using the module's structure.\n"
        "4. Cover normal use cases, edge cases, boundaries, and error conditions (e.g. pytest.raises).\n"
        "5. Use descriptive test function names starting with 'test_'.\n"
        "6. Keep tests independent and deterministic.\n"
        "7. Format your entire test code strictly inside a single ```python ... ``` block.\n"
        "8. You may include a brief explanation before or after the code block."
    )

    # Compute import hint from relative target file path
    # e.g. src/calculator/converter.py -> from calculator.converter import ...
    path_obj = Path(target_file_rel)
    parts = list(path_obj.with_suffix("").parts)
    if parts and parts[0] in ("src", "lib"):
        parts = parts[1:]
    import_module = ".".join(parts)

    user_lines = [
        f"Please write a pytest test suite for `{target_file_rel}`.",
        f"Import module path hint: `{import_module}`",
    ]

    if target_symbols:
        symbols_str = ", ".join(f"`{s}`" for s in target_symbols)
        user_lines.append(f"Priority functions/classes to test: {symbols_str}")

    if existing_test_sample:
        user_lines.append("\nExisting test style reference from this repository:")
        user_lines.append("```python")
        user_lines.append(existing_test_sample[:_MAX_TEST_SAMPLE_BYTES].strip())
        user_lines.append("```")

    user_lines.append("\nSource code to test:")
    user_lines.append("```python")
    user_lines.append(target_source[:_MAX_PROMPT_SOURCE_BYTES].strip())
    user_lines.append("```")

    user_lines.append(
        "\nGenerate the complete pytest test file enclosed in a ```python ... ``` block."
    )

    return [
        LLMMessage(role="system", content=system_content),
        LLMMessage(role="user", content="\n".join(user_lines)),
    ]


# ---------------------------------------------------------------------------
# Path determination
# ---------------------------------------------------------------------------

def determine_test_file_path(
    repo_path: Path,
    target_source: Path,
    custom_output: Path | None = None,
) -> Path:
    """
    Determine where the generated test file should be saved.

    Prefixes with 'test_testpilot_' by default so existing human tests
    are never overwritten.
    """
    if custom_output is not None:
        if custom_output.is_absolute():
            return custom_output
        return repo_path / custom_output

    stem = target_source.stem
    tests_dir = repo_path / "tests"
    if not tests_dir.exists():
        # Fall back to root or source tests dir
        tests_dir = repo_path / "tests"

    return tests_dir / f"test_testpilot_{stem}.py"


# ---------------------------------------------------------------------------
# Public functional API
# ---------------------------------------------------------------------------

def generate_tests(
    repo_path: Path,
    *,
    target_file: Path | str | None = None,
    output_file: Path | str | None = None,
    llm_client: BaseLLMClient | None = None,
    settings: Settings | None = None,
    analysis: RepositoryAnalysis | None = None,
    write_to_disk: bool = True,
    run_id: str = "cli",
) -> GenerationReport:
    """
    Analyze repository context and generate pytest tests for a target module.

    Parameters
    ----------
    repo_path:
        Path to the repository root.
    target_file:
        Path (relative to repo or absolute) of the Python file to generate tests for.
        If None, automatically selected using analysis coverage gaps or source files.
    output_file:
        Destination path for the generated test file. If None, chosen safely.
    llm_client:
        Configured BaseLLMClient instance. If None, instantiated from settings.
    settings:
        Settings instance for configuration.
    analysis:
        Optional pre-existing RepositoryAnalysis.
    write_to_disk:
        Whether to write the generated test file to disk if validation passes.
    run_id:
        Identifier for logging.

    Returns
    -------
    GenerationReport
        Structured report containing generated files, test cases, and status.
    """
    start_time = time.monotonic()
    repo_path = repo_path.resolve()

    report = GenerationReport(
        repository_path=str(repo_path),
        started_at=datetime.now(tz=UTC),
    )

    # 1. Validate repository path
    if not repo_path.exists() or not repo_path.is_dir():
        msg = f"Repository path does not exist or is not a directory: {repo_path}"
        report.errors.append(msg)
        report.status = GenerationStatus.VALIDATION_ERROR
        report.duration_seconds = round(time.monotonic() - start_time, 3)
        report.completed_at = datetime.now(tz=UTC)
        return report

    # 2. Resolve target file
    resolved_target: Path | None = None
    target_rel: str = ""

    if target_file is not None:
        tf = Path(target_file)
        if tf.is_absolute():
            resolved_target = tf
        else:
            resolved_target = (repo_path / tf).resolve()

        if not resolved_target.exists() or not resolved_target.is_file():
            msg = f"Target file does not exist: {resolved_target}"
            report.errors.append(msg)
            report.status = GenerationStatus.VALIDATION_ERROR
            report.duration_seconds = round(time.monotonic() - start_time, 3)
            report.completed_at = datetime.now(tz=UTC)
            return report
        try:
            target_rel = str(resolved_target.relative_to(repo_path)).replace("\\", "/")
        except ValueError:
            target_rel = str(resolved_target).replace("\\", "/")
    else:
        # Automatically choose best target from analysis or filesystem
        resolved_target, target_rel = _select_default_target(repo_path, analysis)
        if resolved_target is None:
            msg = "No suitable Python source files found in repository to generate tests for."
            report.errors.append(msg)
            report.status = GenerationStatus.VALIDATION_ERROR
            report.duration_seconds = round(time.monotonic() - start_time, 3)
            report.completed_at = datetime.now(tz=UTC)
            return report

    report.target_files = [target_rel]

    # 3. Read target source code
    try:
        target_source = resolved_target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        msg = f"Failed to read target source file '{resolved_target}': {exc}"
        report.errors.append(msg)
        report.status = GenerationStatus.ERROR
        report.duration_seconds = round(time.monotonic() - start_time, 3)
        report.completed_at = datetime.now(tz=UTC)
        return report

    # 4. Extract existing test sample for reference
    existing_test_sample = _find_existing_test_sample(repo_path, analysis)

    # 5. Extract priority symbols from analysis gaps if matching target
    target_symbols: list[str] = []
    if analysis:
        for gap in analysis.coverage_gaps:
            if gap.file == target_rel and gap.symbol_name:
                target_symbols.append(gap.symbol_name)

    # 6. Ensure LLM client
    if llm_client is None:
        from testpilot.llm.client import LLMClientFactory

        llm_client = LLMClientFactory.from_settings(settings)

    report.model = llm_client.model_name

    # 7. Build prompt messages
    messages = build_generation_prompt(
        target_source=target_source,
        target_file_rel=target_rel,
        repo_analysis=analysis,
        existing_test_sample=existing_test_sample,
        target_symbols=target_symbols or None,
    )

    # 8. Call LLM
    temp = settings.llm_temperature if settings else 0.2
    max_tok = settings.llm_max_tokens if settings else 4096

    _log.info(
        "Requesting test generation from %s (%s) for %s",
        llm_client.provider_name,
        llm_client.model_name,
        target_rel,
    )

    try:
        llm_resp = llm_client.chat(messages, temperature=temp, max_tokens=max_tok)
    except Exception as exc:  # noqa: BLE001
        msg = f"LLM provider error during test generation: {exc}"
        report.errors.append(msg)
        report.status = GenerationStatus.LLM_ERROR
        report.duration_seconds = round(time.monotonic() - start_time, 3)
        report.completed_at = datetime.now(tz=UTC)
        return report

    report.raw_response = llm_resp.content
    report.prompt_tokens = llm_resp.prompt_tokens
    report.completion_tokens = llm_resp.completion_tokens
    report.total_tokens = llm_resp.total_tokens

    # 9. Check for empty response
    if not llm_resp.content or not llm_resp.content.strip():
        msg = "LLM returned an empty response."
        report.errors.append(msg)
        report.status = GenerationStatus.EMPTY_RESPONSE
        report.duration_seconds = round(time.monotonic() - start_time, 3)
        report.completed_at = datetime.now(tz=UTC)
        return report

    # 10. Extract code and explanation
    code, explanation = extract_test_code_and_explanation(llm_resp.content)
    report.explanation = explanation

    # 11. Validate generated code
    is_valid, test_cases, val_error = validate_generated_code(code)

    # Determine destination path
    custom_out = Path(output_file) if output_file else None
    dest_path = determine_test_file_path(repo_path, resolved_target, custom_out)
    try:
        dest_rel = str(dest_path.relative_to(repo_path)).replace("\\", "/")
    except ValueError:
        dest_rel = str(dest_path).replace("\\", "/")

    gen_file = GeneratedTestFile(
        file_path=dest_rel,
        target_source_file=target_rel,
        code=code,
        test_cases=test_cases,
        is_valid=is_valid,
        validation_error=val_error,
        written_to_disk=False,
    )

    # 12. Write to disk if requested and valid
    if is_valid:
        report.status = GenerationStatus.SUCCESS
        if write_to_disk:
            try:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_text(code, encoding="utf-8")
                gen_file.written_to_disk = True
                _log.info("Wrote generated test file to %s (%d test cases)", dest_path, len(test_cases))
            except Exception as exc:  # noqa: BLE001
                warn = f"Failed to write generated test file to disk: {exc}"
                report.warnings.append(warn)
    else:
        if val_error and "Syntax error" in val_error:
            report.status = GenerationStatus.SYNTAX_ERROR
        else:
            report.status = GenerationStatus.NO_TESTS_FOUND
        report.errors.append(val_error or "Generated code validation failed.")

    report.generated_files = [gen_file]
    report.duration_seconds = round(time.monotonic() - start_time, 3)
    report.completed_at = datetime.now(tz=UTC)

    return report


def _select_default_target(
    repo_path: Path,
    analysis: RepositoryAnalysis | None,
) -> tuple[Path | None, str]:
    """Select the best candidate source file to test from analysis or directory scan."""
    # 1. From analysis: check untested public functions / coverage gaps
    if analysis:
        # Check gap targets
        for gap in analysis.coverage_gaps:
            target_path = (repo_path / gap.file).resolve()
            if target_path.exists() and target_path.is_file():
                return target_path, gap.file

        # Check source files
        for sf in analysis.source_files:
            target_path = (repo_path / sf).resolve()
            if target_path.exists() and target_path.is_file():
                return target_path, sf

    # 2. Filesystem scan fallback: find first non-test Python file
    for p in repo_path.rglob("*.py"):
        rel = str(p.relative_to(repo_path)).replace("\\", "/")
        # Skip virtualenvs, tests, caches, setup files
        parts = rel.lower().split("/")
        if any(ignored in parts for ignored in (".venv", "venv", "__pycache__", ".pytest_cache", ".git")):
            continue
        if parts[0] == "tests" or p.name.startswith("test_") or p.name.endswith("_test.py"):
            continue
        if p.name in ("conftest.py", "setup.py"):
            continue
        return p, rel

    return None, ""


def _find_existing_test_sample(
    repo_path: Path,
    analysis: RepositoryAnalysis | None,
) -> str | None:
    """Find a readable excerpt from an existing test file to serve as a style example."""
    candidates: list[Path] = []
    if analysis and analysis.test_files:
        for tf in analysis.test_files:
            p = (repo_path / tf).resolve()
            if p.exists() and p.is_file():
                candidates.append(p)

    if not candidates:
        tests_dir = repo_path / "tests"
        if tests_dir.exists():
            candidates = list(tests_dir.glob("test_*.py"))

    for c in candidates:
        try:
            content = c.read_text(encoding="utf-8", errors="replace")
            if len(content.strip()) > 50:
                return content[:_MAX_TEST_SAMPLE_BYTES]
        except Exception:  # noqa: BLE001
            continue

    return None


# ---------------------------------------------------------------------------
# Agent implementation
# ---------------------------------------------------------------------------

class TestGenerationAgent(BaseAgent):
    """
    Test generation agent in the TestPilot AI pipeline.

    Takes a SessionContext, identifies testing gaps in the repository,
    calls the configured LLM client to generate pytest tests, validates
    the output with AST parsing, writes tests to disk, and updates SessionContext.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        settings: Settings,
    ) -> None:
        super().__init__(llm_client, settings)
        self._log = get_logger("testpilot.agents.generator")

    @property
    def name(self) -> str:
        return "generator"

    def run(self, context: SessionContext) -> AgentResult:
        self._log_start(context)

        # 1. Validate repo_path in context
        if context.repo_path is None:
            msg = "SessionContext.repo_path is not set; cannot generate tests."
            context.errors.append(msg)
            report = GenerationReport(
                repository_path="",
                status=GenerationStatus.VALIDATION_ERROR,
                errors=[msg],
            )
            context.generation_report = report
            self._log_finish(context, AgentResult(success=False, context=context, message=msg, errors=[msg]))
            return AgentResult(success=False, context=context, message=msg, errors=[msg])

        repo_path = Path(context.repo_path).resolve()
        if not repo_path.exists() or not repo_path.is_dir():
            msg = f"Repository path does not exist or is not a directory: {repo_path}"
            context.errors.append(msg)
            report = GenerationReport(
                repository_path=str(repo_path),
                status=GenerationStatus.VALIDATION_ERROR,
                errors=[msg],
            )
            context.generation_report = report
            self._log_finish(context, AgentResult(success=False, context=context, message=msg, errors=[msg]))
            return AgentResult(success=False, context=context, message=msg, errors=[msg])

        # 2. Analyze repository if not already analyzed
        if getattr(context, "repository_analysis", None) is None:
            from testpilot.agents.analyzer import analyze_repository

            self._log.info("RepositoryAnalysis not found in context; running static analysis first.")
            analysis = analyze_repository(
                repo_path=repo_path,
                settings=self._settings,
                run_id=context.run_id,
                attempt_coverage=False,
            )
            context.repository_analysis = analysis
            context.detected_language = analysis.language
            context.detected_test_framework = analysis.test_framework

        # 3. Record generation start timing
        if context.timing.generation_started_at is None:
            context.timing.generation_started_at = datetime.now(tz=UTC)

        # 4. Generate tests
        report = generate_tests(
            repo_path=repo_path,
            llm_client=self._llm,
            settings=self._settings,
            analysis=context.repository_analysis,
            write_to_disk=True,
            run_id=context.run_id,
        )

        # 5. Populate SessionContext
        context.generation_report = report
        context.current_step = PipelineStep.TEST_GENERATION
        context.generated_test_files = [
            f.file_path for f in report.valid_files if f.written_to_disk
        ]
        context.tests_generated_count = report.total_tests_generated

        # 6. Build result message and status
        if report.has_valid_tests:
            msg = (
                f"Generated {report.total_tests_generated} test(s) across "
                f"{len(report.valid_files)} file(s). "
                f"Duration: {report.duration_seconds:.2f}s."
            )
            res = AgentResult(success=True, context=context, message=msg, errors=report.errors)
        else:
            msg = (
                f"Test generation failed ({report.status.value}): "
                f"{report.errors[0] if report.errors else 'No valid tests generated.'}"
            )
            context.errors.extend(report.errors)
            res = AgentResult(success=False, context=context, message=msg, errors=report.errors)

        self._log_finish(context, res)
        return res
