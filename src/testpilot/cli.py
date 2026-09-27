"""
CLI for TestPilot AI — Agentic Software Testing & Validation Platform.

Entry point:  testpilot [OPTIONS] COMMAND [ARGS]...

Phase 0 commands:
  testpilot --help           Show this message and exit.
  testpilot info             Show version and configuration status.
  testpilot run --repo PATH  (placeholder) Validate path; pipeline not yet implemented.

Usage example:
  testpilot run --repo ./my-project
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from testpilot import __version__

app = typer.Typer(
    name="testpilot",
    help="TestPilot AI — Agentic Software Testing & Validation Platform.",
    add_completion=False,
    no_args_is_help=True,
)

console = Console(stderr=False)
err_console = Console(stderr=True, style="red")


# ---------------------------------------------------------------------------
# info command
# ---------------------------------------------------------------------------

@app.command("info")
def cmd_info(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable DEBUG logging.")] = False,
) -> None:
    """Show version information and current configuration status."""
    from testpilot.config import load_settings

    settings = load_settings()

    table = Table(title=f"TestPilot AI  v{__version__}", show_header=True, header_style="bold")
    table.add_column("Setting", style="cyan", no_wrap=True)
    table.add_column("Value")

    table.add_row("Version", __version__)
    table.add_row("Phase", "0 — Foundation (agents not yet implemented)")
    table.add_row("LLM provider", settings.llm_provider.value)
    table.add_row("LLM model", settings.effective_llm_model)
    table.add_row("Max repair iterations", str(settings.max_repair_iterations))
    table.add_row("Execution timeout (s)", str(settings.test_execution_timeout))
    table.add_row("Output directory", str(settings.output_dir))
    table.add_row("Log level", settings.log_level.value)
    table.add_row("Approach (experiment)", settings.approach)
    table.add_row(
        "OpenAI key configured",
        "yes" if settings.is_openai_configured() else "no (using Ollama or stub)",
    )

    console.print(table)


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------

@app.command("run")
def cmd_run(
    repo: Annotated[
        Path,
        typer.Option("--repo", "-r", help="Path to the repository to analyse and test."),
    ],
    approach: Annotated[
        Optional[str],
        typer.Option("--approach", help="Experiment approach: 'single' or 'multi' (default)."),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG logging."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Validate inputs only; do not run the pipeline."),
    ] = False,
) -> None:
    """
    Run the TestPilot AI pipeline against a repository.

    [Phase 0] Validates the repository path and configuration.
    The full agentic pipeline is not yet implemented.

    Example:

        testpilot run --repo ./my-project
    """
    from testpilot.config import load_settings
    from testpilot.utils.logging import configure_root_logging

    settings = load_settings()
    log_level = "DEBUG" if verbose else settings.log_level.value
    configure_root_logging(level=log_level)

    # Override approach from CLI flag if provided
    if approach is not None:
        if approach not in ("single", "multi"):
            err_console.print(
                f"[bold red]Error:[/] --approach must be 'single' or 'multi', got '{approach}'."
            )
            raise typer.Exit(code=1)
        settings.approach = approach  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Validate repository path
    # ------------------------------------------------------------------
    console.print(f"\n[bold]TestPilot AI[/bold]  v{__version__}  —  [dim]Phase 0 Foundation[/dim]\n")

    resolved = repo.resolve()

    if not resolved.exists():
        err_console.print(
            Panel(
                f"Repository path does not exist:\n  [bold]{resolved}[/bold]\n\n"
                "Please provide a valid local directory path.",
                title="[red]Path Error[/red]",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

    if not resolved.is_dir():
        err_console.print(
            Panel(
                f"Path exists but is not a directory:\n  [bold]{resolved}[/bold]\n\n"
                "TestPilot AI expects a repository root directory.",
                title="[red]Path Error[/red]",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

    console.print(f"  [green]OK[/green] Repository path validated:  [bold]{resolved}[/bold]")
    console.print(f"  [green]OK[/green] Approach:                   [bold]{settings.approach}[/bold]")
    console.print(f"  [green]OK[/green] LLM provider:               [bold]{settings.llm_provider.value}[/bold]")
    console.print(f"  [green]OK[/green] Model:                      [bold]{settings.effective_llm_model}[/bold]\n")

    if dry_run:
        console.print("[yellow]--dry-run flag set.  Skipping pipeline execution.[/yellow]")
        raise typer.Exit(code=0)

    # ------------------------------------------------------------------
    # Phase 0: pipeline not yet implemented
    # ------------------------------------------------------------------
    console.print(
        Panel(
            "[bold yellow]Phase 0 -- Pipeline Not Yet Implemented[/bold yellow]\n\n"
            "The repository path is valid and all configuration loaded successfully.\n\n"
            "The agentic pipeline (Analyzer > Generator > Executor\n"
            "> Failure Analysis > Repair > Report) is scheduled for Phase 1.\n\n"
            "Run  [bold]testpilot info[/bold]  to review the current configuration.\n"
            "See  [bold]README.md[/bold]  for the implementation roadmap.",
            title="TestPilot AI -- Status",
            border_style="yellow",
        )
    )
    raise typer.Exit(code=0)


# ---------------------------------------------------------------------------
# analyze command
# ---------------------------------------------------------------------------

@app.command("analyze")
def cmd_analyze(
    repo: Annotated[
        Path,
        typer.Option("--repo", "-r", help="Path to the repository to analyse."),
    ],
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG logging."),
    ] = False,
    no_coverage: Annotated[
        bool,
        typer.Option("--no-coverage", help="Skip coverage collection (faster, static only)."),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Print full analysis as JSON instead of summary."),
    ] = False,
) -> None:
    """
    Analyse a repository and print a structured summary.

    Runs the Repository Analyzer against the given path and reports:
    language, test framework, file counts, symbol counts, and coverage.

    Example:

        testpilot analyze --repo ./my-project
    """
    from testpilot.agents.analyzer import analyze_repository
    from testpilot.config import load_settings
    from testpilot.utils.logging import configure_root_logging

    settings = load_settings()
    log_level = "DEBUG" if verbose else settings.log_level.value
    configure_root_logging(level=log_level)

    resolved = repo.resolve()

    if not resolved.exists() or not resolved.is_dir():
        err_console.print(
            f"[bold red]Error:[/] Repository path not found or not a directory: {resolved}"
        )
        raise typer.Exit(code=1)

    analysis = analyze_repository(
        resolved,
        settings=settings,
        attempt_coverage=not no_coverage,
    )

    if json_out:
        # Pure JSON output — no header or decorative text
        typer.echo(analysis.model_dump_json(indent=2))
        raise typer.Exit(code=0)

    console.print(f"\n[bold]TestPilot AI[/bold]  v{__version__}  --  Analyzing repository...\n")

    # ------------------------------------------------------------------
    # Human-readable summary table
    # ------------------------------------------------------------------
    table = Table(
        title=f"Repository Analysis  --  {resolved.name}",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Property", style="cyan", no_wrap=True)
    table.add_column("Value")

    table.add_row("Repository", str(resolved))
    table.add_row("Language", analysis.language.capitalize())
    table.add_row(
        "Python version",
        analysis.python_version if analysis.python_version else "not detected",
    )
    table.add_row(
        "Test framework",
        f"{analysis.test_framework} (from {analysis.test_framework_config_source})"
        if analysis.test_framework_detected
        else "not detected",
    )
    table.add_row("Source files", str(analysis.source_file_count))
    table.add_row("Test files", str(analysis.test_file_count))
    table.add_row("Symbols extracted", str(analysis.symbol_count))
    table.add_row(
        "Public symbols",
        str(len(analysis.public_symbols)),
    )

    cov = analysis.coverage_summary
    if cov.line_coverage_pct is not None:
        cov_str = f"{cov.line_coverage_pct:.1f}%"
        if cov.tests_ran is not None:
            cov_str += f"  ({cov.tests_passed or 0} passed"
            if cov.tests_failed:
                cov_str += f", {cov.tests_failed} failed"
            cov_str += ")"
        table.add_row("Line coverage", cov_str)
    else:
        table.add_row("Line coverage", f"[yellow]{cov.status.value}[/yellow]")

    gap_count = len([g for g in analysis.coverage_gaps if g.gap_type == "symbol"])
    table.add_row("Coverage gaps (symbols)", str(gap_count) if gap_count else "none detected")
    table.add_row("Parse errors", str(len(analysis.parse_errors)) if analysis.parse_errors else "none")
    table.add_row("Analysis duration", f"{analysis.duration_seconds:.2f}s")

    console.print(table)

    if analysis.warnings:
        console.print("\n[yellow]Warnings:[/yellow]")
        for w in analysis.warnings:
            console.print(f"  [yellow]*[/yellow] {w}")

    if analysis.errors:
        console.print("\n[red]Errors:[/red]")
        for e in analysis.errors:
            console.print(f"  [red]![/red] {e}")

    if analysis.errors:
        raise typer.Exit(code=1)

    raise typer.Exit(code=0)


# ---------------------------------------------------------------------------
# doctor command
# ---------------------------------------------------------------------------

@app.command("doctor")
def cmd_doctor(
    repo: Annotated[
        Path,
        typer.Option("--repo", "-r", help="Path to the repository to diagnose."),
    ],
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG logging."),
    ] = False,
) -> None:
    """
    Diagnose the execution environment for a repository.

    Reports layout, virtual environment, package importability,
    and pytest/coverage availability.

    Example:

        testpilot doctor --repo ./my-project
    """
    from testpilot.config import load_settings
    from testpilot.utils.execution import detect_environment
    from testpilot.utils.logging import configure_root_logging

    settings = load_settings()
    configure_root_logging(level="DEBUG" if verbose else settings.log_level.value)

    resolved = repo.resolve()
    if not resolved.exists() or not resolved.is_dir():
        err_console.print(
            f"[bold red]Error:[/] Path not found or not a directory: {resolved}"
        )
        raise typer.Exit(code=1)

    env = detect_environment(resolved)

    table = Table(
        title=f"Execution Environment  --  {resolved.name}",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Property", style="cyan", no_wrap=True)
    table.add_column("Value")

    def yn(v: bool) -> str:
        return "[green]yes[/green]" if v else "[red]no[/red]"

    table.add_row("Repository", str(resolved))
    table.add_row("Layout", env.layout)
    table.add_row("Source dir", env.src_dir or "(root)")
    table.add_row("Detected packages", ", ".join(env.detected_packages) or "none")
    table.add_row("Has pyproject.toml", yn(env.has_pyproject_toml))
    table.add_row("Has conftest.py", yn(env.has_conftest))
    table.add_row("Local venv found", yn(env.has_local_venv))
    table.add_row("Local venv path", env.local_venv_path or "N/A")
    table.add_row("Python executable", env.python_executable)
    table.add_row("pytest available", yn(env.pytest_available))
    table.add_row("coverage available", yn(env.coverage_available))
    table.add_row("Package importable", yn(env.package_importable))
    if env.import_error:
        table.add_row("Import error", f"[yellow]{env.import_error[:80]}[/yellow]")
    table.add_row("Extra PYTHONPATH", ", ".join(env.extra_pythonpath) or "none")

    console.print(table)

    if env.warnings:
        console.print("\n[yellow]Warnings:[/yellow]")
        for w in env.warnings:
            console.print(f"  [yellow]*[/yellow] {w}")

    if env.errors:
        console.print("\n[red]Errors:[/red]")
        for e in env.errors:
            console.print(f"  [red]![/red] {e}")
        raise typer.Exit(code=1)

# ---------------------------------------------------------------------------
# execute command
# ---------------------------------------------------------------------------

@app.command("execute")
def cmd_execute(
    repo: Annotated[
        Path,
        typer.Option("--repo", "-r", help="Path to the repository to execute tests in."),
    ],
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG logging."),
    ] = False,
    no_coverage: Annotated[
        bool,
        typer.Option("--no-coverage", help="Skip coverage collection."),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Print full execution report as JSON instead of summary."),
    ] = False,
    timeout: Annotated[
        Optional[float],
        typer.Option("--timeout", help="Subprocess execution timeout in seconds."),
    ] = None,
) -> None:
    """
    Execute tests in a repository and print a concise structured summary.

    Runs the TestExecutionAgent against the repository and reports:
    framework, test counts (passed, failed, skipped, errors), coverage,
    duration, and failed test identifiers.

    Example:

        testpilot execute --repo ./my-project
    """
    from testpilot.agents.executor import TestExecutionAgent, execute_tests
    from testpilot.config import load_settings
    from testpilot.llm.client import LLMClientFactory
    from testpilot.models.execution import ExecutionStatus
    from testpilot.session_context import SessionContext
    from testpilot.utils.logging import configure_root_logging

    settings = load_settings()
    log_level = "DEBUG" if verbose else settings.log_level.value
    configure_root_logging(level=log_level)

    resolved = repo.resolve()
    if not resolved.exists() or not resolved.is_dir():
        err_console.print(
            f"[bold red]Error:[/] Repository path not found or not a directory: {resolved}"
        )
        raise typer.Exit(code=1)

    if timeout is not None:
        settings.test_execution_timeout = timeout

    ctx = SessionContext(repo_path=resolved)
    llm_client = LLMClientFactory.from_settings(settings)
    agent = TestExecutionAgent(llm_client=llm_client, settings=settings)

    if no_coverage:
        # Run execute_tests with coverage disabled
        ctx.execution_report = execute_tests(
            resolved,
            settings=settings,
            with_coverage=False,
            timeout=timeout,
        )
    else:
        result = agent.run(ctx)

    report = ctx.execution_report

    if report is None:
        err_console.print("[bold red]Error:[/] Execution failed to produce an execution report.")
        raise typer.Exit(code=1)

    if json_out:
        typer.echo(report.model_dump_json(indent=2))
        if report.has_failures or report.status in (
            ExecutionStatus.VALIDATION_ERROR,
            ExecutionStatus.ENVIRONMENT_ERROR,
            ExecutionStatus.TIMEOUT,
            ExecutionStatus.COLLECTION_ERROR,
            ExecutionStatus.ERROR,
        ):
            raise typer.Exit(code=1)
        raise typer.Exit(code=0)

    # Concise human-readable summary table
    table = Table(
        title=f"Test Execution  --  {resolved.name}",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Property", style="cyan", no_wrap=True)
    table.add_column("Value")

    table.add_row("Repository", str(resolved))
    framework = "pytest"
    if ctx.repository_analysis and getattr(ctx.repository_analysis, "test_framework", ""):
        framework = ctx.repository_analysis.test_framework
    table.add_row("Framework", framework)
    table.add_row("Tests", str(report.summary.total))
    table.add_row("Passed", f"[green]{report.summary.passed}[/green]")
    if report.summary.failed > 0:
        table.add_row("Failed", f"[red]{report.summary.failed}[/red]")
    else:
        table.add_row("Failed", "0")
    if report.summary.errors > 0:
        table.add_row("Errors", f"[red]{report.summary.errors}[/red]")
    table.add_row("Skipped", str(report.summary.skipped))
    if report.summary.xfailed > 0:
        table.add_row("XFailed", str(report.summary.xfailed))
    if report.summary.xpassed > 0:
        table.add_row("XPassed", str(report.summary.xpassed))

    cov = report.coverage
    if cov.coverage_pct is not None:
        table.add_row("Coverage", f"[cyan]{cov.coverage_pct:.1f}%[/cyan]")
    else:
        table.add_row("Coverage", f"[yellow]{cov.status.value}[/yellow]")

    table.add_row("Duration", f"{report.duration_seconds:.2f}s")

    console.print(f"\n[bold]TestPilot AI[/bold]  v{__version__}  --  Executing tests...\n")
    console.print(table)

    if report.failed_tests:
        console.print("\n[bold red]Failed tests:[/bold red]")
        for ft in report.failed_tests:
            console.print(f"  [red]*[/red] {ft}")
        console.print("")


    if report.warnings:
        console.print("[yellow]Warnings:[/yellow]")
        for w in report.warnings:
            console.print(f"  [yellow]*[/yellow] {w}")

    if report.errors:
        console.print("[red]Errors:[/red]")
        for e in report.errors:
            console.print(f"  [red]![/red] {e}")

    if report.has_failures or report.status in (
        ExecutionStatus.VALIDATION_ERROR,
        ExecutionStatus.ENVIRONMENT_ERROR,
        ExecutionStatus.TIMEOUT,
        ExecutionStatus.COLLECTION_ERROR,
        ExecutionStatus.ERROR,
    ):
        raise typer.Exit(code=1)

    raise typer.Exit(code=0)


# ---------------------------------------------------------------------------
# generate command
# ---------------------------------------------------------------------------

@app.command("generate")
def cmd_generate(
    repo: Annotated[
        Path,
        typer.Option("--repo", "-r", help="Path to the repository to generate tests for."),
    ],
    target: Annotated[
        Optional[Path],
        typer.Option("--target", "-t", help="Target source file to generate tests for."),
    ] = None,
    output: Annotated[
        Optional[Path],
        typer.Option("--output", "-o", help="Custom output path for the generated test file."),
    ] = None,
    write: Annotated[
        bool,
        typer.Option("--write/--dry-run", help="Whether to write generated test files to disk."),
    ] = True,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Print full generation report as JSON instead of summary."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG logging."),
    ] = False,
) -> None:
    """
    Generate pytest tests for a target module in a repository using LLM.

    Analyzes the target source file and repository context, prompts the
    configured LLM, extracts and validates the generated test suite,
    and optionally writes it to the tests directory.

    Example:

        testpilot generate --repo ./my-project --target src/my_pkg/module.py
    """
    from testpilot.agents.generator import generate_tests
    from testpilot.config import load_settings
    from testpilot.llm.client import LLMClientFactory
    from testpilot.models.generation import GenerationStatus
    from testpilot.utils.logging import configure_root_logging

    settings = load_settings()
    log_level = "DEBUG" if verbose else settings.log_level.value
    configure_root_logging(level=log_level)

    resolved = repo.resolve()
    if not resolved.exists() or not resolved.is_dir():
        err_console.print(
            f"[bold red]Error:[/] Repository path not found or not a directory: {resolved}"
        )
        raise typer.Exit(code=1)

    llm_client = LLMClientFactory.from_settings(settings)

    report = generate_tests(
        repo_path=resolved,
        target_file=target,
        output_file=output,
        llm_client=llm_client,
        settings=settings,
        write_to_disk=write,
    )

    if json_out:
        typer.echo(report.model_dump_json(indent=2))
        if not report.has_valid_tests or report.status != GenerationStatus.SUCCESS:
            raise typer.Exit(code=1)
        raise typer.Exit(code=0)

    # Concise human-readable summary table
    table = Table(
        title=f"Test Generation  --  {resolved.name}",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Property", style="cyan", no_wrap=True)
    table.add_column("Value")

    table.add_row("Repository", str(resolved))
    target_str = ", ".join(report.target_files) if report.target_files else "Auto-detected"
    table.add_row("Target", target_str)
    table.add_row(
        "Status",
        f"[green]{report.status.value}[/green]"
        if report.has_valid_tests
        else f"[red]{report.status.value}[/red]",
    )
    table.add_row("Model", report.model or settings.effective_llm_model)
    table.add_row("Tests generated", str(report.total_tests_generated))
    table.add_row("Duration", f"{report.duration_seconds:.2f}s")

    for gf in report.generated_files:
        dest_display = (
            f"{gf.file_path} [green](written)[/green]"
            if gf.written_to_disk
            else f"{gf.file_path} [yellow](dry-run)[/yellow]"
        )
        table.add_row("Output file", dest_display)
        table.add_row(
            "Valid syntax",
            "[green]Yes[/green]"
            if gf.is_valid
            else f"[red]No: {gf.validation_error}[/red]",
        )
        if gf.test_cases:
            names = ", ".join(gf.test_names)
            table.add_row("Discovered tests", names)

    console.print(f"\n[bold]TestPilot AI[/bold]  v{__version__}  --  Generating tests...\n")
    console.print(table)

    if report.explanation:
        console.print("\n[bold]Model explanation:[/bold]")
        console.print(f"  {report.explanation[:500]}")

    if report.warnings:
        console.print("\n[yellow]Warnings:[/yellow]")
        for w in report.warnings:
            console.print(f"  [yellow]*[/yellow] {w}")

    if report.errors:
        console.print("\n[red]Errors:[/red]")
        for e in report.errors:
            console.print(f"  [red]![/red] {e}")

    if not report.has_valid_tests or report.status != GenerationStatus.SUCCESS:
        raise typer.Exit(code=1)

    raise typer.Exit(code=0)


# ---------------------------------------------------------------------------
# repair command
# ---------------------------------------------------------------------------

@app.command("repair")
def cmd_repair(
    repo: Annotated[
        Path,
        typer.Option("--repo", "-r", help="Path to the repository to repair tests for."),
    ],
    test_file: Annotated[
        Optional[Path],
        typer.Option("--test", "-t", help="Specific test file to repair."),
    ] = None,
    max_attempts: Annotated[
        Optional[int],
        typer.Option("--max-attempts", help="Maximum repair iterations (default from config, e.g. 2)."),
    ] = None,
    write: Annotated[
        bool,
        typer.Option("--write/--dry-run", help="Whether to apply repaired test files to disk."),
    ] = True,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Print full repair report as JSON instead of summary."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG logging."),
    ] = False,
) -> None:
    """
    Diagnose failing tests and run an automated iterative repair loop.

    Executes the test suite, analyzes root causes with the FailureAnalysisAgent,
    generates targeted test repairs with the RepairAgent, validates syntax via AST,
    and re-executes tests to verify the fix in a bounded loop.

    Example:

        testpilot repair --repo ./my-project --test tests/test_calc.py
    """
    from testpilot.agents.repair import run_repair_loop
    from testpilot.config import load_settings
    from testpilot.llm.client import LLMClientFactory
    from testpilot.models.repair import RepairStatus
    from testpilot.utils.logging import configure_root_logging

    settings = load_settings()
    log_level = "DEBUG" if verbose else settings.log_level.value
    configure_root_logging(level=log_level)

    resolved = repo.resolve()
    if not resolved.exists() or not resolved.is_dir():
        err_console.print(
            f"[bold red]Error:[/] Repository path not found or not a directory: {resolved}"
        )
        raise typer.Exit(code=1)

    llm_client = LLMClientFactory.from_settings(settings)

    report = run_repair_loop(
        repo_path=resolved,
        test_file=test_file,
        llm_client=llm_client,
        settings=settings,
        max_iterations=max_attempts,
        write_to_disk=write,
    )

    if json_out:
        typer.echo(report.model_dump_json(indent=2))
        if not report.resolved and report.status != RepairStatus.NO_FAILURES:
            raise typer.Exit(code=1)
        raise typer.Exit(code=0)

    # Concise human-readable summary table
    table = Table(
        title=f"Failure Analysis & Repair  --  {resolved.name}",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Property", style="cyan", no_wrap=True)
    table.add_column("Value")

    table.add_row("Repository", str(resolved))
    if report.test_file:
        table.add_row("Test file", report.test_file)

    status_style = (
        "green"
        if (report.resolved or report.status == RepairStatus.NO_FAILURES)
        else "red"
    )
    table.add_row("Status", f"[{status_style}]{report.status.value}[/{status_style}]")
    table.add_row("Iterations run", f"{report.iterations_run} / {report.max_iterations}")
    table.add_row("Initial failures", str(len(report.initial_failures)))
    table.add_row("Final failures", str(len(report.final_failures)))
    table.add_row("Failures fixed", str(report.failures_fixed_count))
    table.add_row("Duration", f"{report.duration_seconds:.2f}s")

    console.print(f"\n[bold]TestPilot AI[/bold]  v{__version__}  --  Repairing tests...\n")
    console.print(table)

    if report.analyses:
        console.print("\n[bold]Failure Diagnoses:[/bold]")
        for a in report.analyses:
            console.print(f"  * [bold cyan]{a.test_nodeid}[/bold cyan]")
            console.print(f"    Category: [yellow]{a.category.value}[/yellow]")
            console.print(f"    Explanation: {a.explanation}")
            if a.suggested_fix:
                console.print(f"    Suggested fix: {a.suggested_fix}")

    if report.attempts:
        console.print("\n[bold]Repair Attempts:[/bold]")
        for att in report.attempts:
            outcome = (
                "[green]Passed[/green]"
                if att.re_execution_passed
                else "[red]Failed[/red]"
            )
            console.print(
                f"  Iteration {att.iteration}: AST valid={att.is_ast_valid} -> Re-execution: {outcome}"
            )

    if report.warnings:
        console.print("\n[yellow]Warnings:[/yellow]")
        for w in report.warnings:
            console.print(f"  [yellow]*[/yellow] {w}")

    if report.errors:
        console.print("\n[red]Errors:[/red]")
        for e in report.errors:
            console.print(f"  [red]![/red] {e}")

    if not report.resolved and report.status != RepairStatus.NO_FAILURES:
        raise typer.Exit(code=1)

    raise typer.Exit(code=0)


# ---------------------------------------------------------------------------
# evaluate / benchmark command
# ---------------------------------------------------------------------------

@app.command("evaluate")
def cmd_evaluate(
    repo: Annotated[
        Path,
        typer.Option("--repo", "-r", help="Path to the repository to evaluate."),
    ],
    target: Annotated[
        Optional[str],
        typer.Option("--target", "-t", help="Specific module or file to evaluate (e.g. src/pkg/mod.py)."),
    ] = None,
    isolate: Annotated[
        bool,
        typer.Option(
            "--isolate/--no-isolate",
            help="Run evaluation in an isolated workspace copy to leave repo untouched.",
        ),
    ] = True,
    max_repair_attempts: Annotated[
        Optional[int],
        typer.Option("--max-repair-attempts", help="Maximum repair iterations if failures occur."),
    ] = None,
    save_metrics: Annotated[
        bool,
        typer.Option("--save-metrics", help="Append RunMetrics to benchmarks/results/metrics.jsonl."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print full evaluation result as JSON."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG logging."),
    ] = False,
) -> None:
    """
    Run an end-to-end benchmark evaluation through the TestPilot pipeline:
    Analyze -> Generate -> Execute -> Repair -> Re-execute -> Metrics.
    """
    from testpilot.config import load_settings
    from testpilot.evaluation.runner import run_benchmark_evaluation
    from testpilot.models.evaluation import BenchmarkEvaluationStatus, append_metrics
    from testpilot.utils.logging import configure_root_logging

    repo = repo.resolve()
    if not repo.exists() or not repo.is_dir():
        err_console.print(
            f"[bold red]Error:[/bold red] Repository path does not exist or is not a directory: {repo}"
        )
        raise typer.Exit(code=1)

    settings = load_settings()
    log_level = "DEBUG" if verbose else settings.log_level.value
    configure_root_logging(level=log_level)

    result = run_benchmark_evaluation(
        repo_path=repo,
        target_module=target,
        settings=settings,
        isolate=isolate,
        max_repair_attempts=max_repair_attempts,
        run_id="cli_eval",
    )

    if save_metrics:
        results_dir = Path("benchmarks/results")
        append_metrics(result.to_run_metrics(), results_dir)

    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        if result.status in (
            BenchmarkEvaluationStatus.VALIDATION_ERROR,
            BenchmarkEvaluationStatus.ERROR,
        ):
            raise typer.Exit(code=1)
        raise typer.Exit(code=0)

    # Human-readable summary table
    table = Table(
        title=f"Benchmark Evaluation  --  {result.benchmark_name}",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Pipeline Metric", style="bold")
    table.add_column("Value")

    table.add_row("Benchmark Name", result.benchmark_name)
    table.add_row("Target Module", result.target_module or "(auto-detected)")
    table.add_row("Overall Status", result.status.value)
    table.add_row("Total Duration", f"{result.total_duration_seconds:.2f}s")
    table.add_row(
        "Generation",
        f"{result.tests_generated} tests ({result.valid_generated_tests} valid) in {result.generation_duration_seconds:.2f}s",
    )
    table.add_row(
        "Initial Execution",
        f"{result.initial_passed} passed, {result.initial_failed} failed ({result.initial_execution_duration_seconds:.2f}s)",
    )
    table.add_row("Repair Required", "Yes" if result.repair_required else "No")
    table.add_row(
        "Repair Outcome",
        f"Status: {result.repair_status} | Attempts: {result.repair_attempts} | Resolved: {result.failures_resolved}",
    )
    table.add_row(
        "Final Execution",
        f"{result.final_passed} passed, {result.final_failed} failed ({result.final_execution_duration_seconds:.2f}s)",
    )

    cov_before_str = f"{result.coverage_before:.1f}%" if result.coverage_before is not None else "N/A"
    cov_after_str = f"{result.coverage_after:.1f}%" if result.coverage_after is not None else "N/A"
    cov_delta_str = f"{result.coverage_delta:+.1f}%" if result.coverage_delta is not None else "N/A"
    table.add_row("Coverage Baseline", cov_before_str)
    table.add_row("Coverage Final", cov_after_str)
    table.add_row("Coverage Delta", cov_delta_str)

    console.print(f"\n[bold]TestPilot AI[/bold]  v{__version__}  --  Evaluation & Benchmarking\n")
    console.print(table)

    if result.has_source_code_defects:
        console.print(
            "\n[bold yellow]Safety Gate Triggered:[/bold yellow] Real source-code defect detected. "
            "Repair Agent refused to alter tests to conceal genuine application bugs."
        )

    if result.warnings:
        console.print("\n[yellow]Warnings:[/yellow]")
        for w in result.warnings:
            console.print(f"  [yellow]*[/yellow] {w}")

    if result.errors:
        console.print("\n[red]Errors:[/red]")
        for e in result.errors:
            console.print(f"  [red]![/red] {e}")

    if result.status in (
        BenchmarkEvaluationStatus.VALIDATION_ERROR,
        BenchmarkEvaluationStatus.ERROR,
    ):
        raise typer.Exit(code=1)

    raise typer.Exit(code=0)


@app.command("benchmark")
def cmd_benchmark(
    repo: Annotated[
        Path,
        typer.Option("--repo", "-r", help="Path to the repository to benchmark."),
    ],
    target: Annotated[
        Optional[str],
        typer.Option("--target", "-t", help="Specific module or file to benchmark."),
    ] = None,
    isolate: Annotated[
        bool,
        typer.Option(
            "--isolate/--no-isolate",
            help="Run benchmark in an isolated workspace copy.",
        ),
    ] = True,
    max_repair_attempts: Annotated[
        Optional[int],
        typer.Option("--max-repair-attempts", help="Maximum repair iterations."),
    ] = None,
    save_metrics: Annotated[
        bool,
        typer.Option("--save-metrics", help="Append RunMetrics to metrics.jsonl."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print full evaluation result as JSON."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG logging."),
    ] = False,
) -> None:
    """Benchmark an end-to-end TestPilot pipeline run against a repository."""
    cmd_evaluate(
        repo=repo,
        target=target,
        isolate=isolate,
        max_repair_attempts=max_repair_attempts,
        save_metrics=save_metrics,
        json_output=json_output,
        verbose=verbose,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Package entry point used by the installed ``testpilot`` command."""
    app()


if __name__ == "__main__":
    main()
