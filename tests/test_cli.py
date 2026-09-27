"""
Tests for the Typer CLI (testpilot.cli).

Verifies:
- CLI starts successfully (--help returns exit code 0).
- 'info' command works.
- 'run' command with an invalid path exits with code 1.
- 'run' command with a valid path exits with code 0 (pipeline placeholder).
- '--dry-run' flag works.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from testpilot.cli import app

runner = CliRunner()


class TestHelp:
    def test_help_exits_zero(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_help_contains_project_name(self):
        result = runner.invoke(app, ["--help"])
        assert "TestPilot" in result.output

    def test_run_help(self):
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--repo" in result.output


class TestInfoCommand:
    def test_info_exits_zero(self):
        result = runner.invoke(app, ["info"])
        assert result.exit_code == 0

    def test_info_shows_version(self):
        result = runner.invoke(app, ["info"])
        assert "0.1.0" in result.output

    def test_info_shows_phase(self):
        result = runner.invoke(app, ["info"])
        assert "Phase" in result.output


class TestRunCommand:
    def test_invalid_path_exits_nonzero(self, tmp_path):
        nonexistent = str(tmp_path / "does_not_exist_abc123")
        result = runner.invoke(app, ["run", "--repo", nonexistent])
        assert result.exit_code != 0

    def test_valid_path_exits_zero(self, tmp_path):
        """With a valid directory, Phase 0 should exit 0 (placeholder message)."""
        result = runner.invoke(app, ["run", "--repo", str(tmp_path)])
        assert result.exit_code == 0

    def test_valid_path_shows_placeholder_message(self, tmp_path):
        result = runner.invoke(app, ["run", "--repo", str(tmp_path)])
        assert "Phase 0" in result.output or "Not Yet Implemented" in result.output

    def test_file_path_exits_nonzero(self, tmp_path):
        """Passing a file (not a dir) should fail with a clear message."""
        a_file = tmp_path / "something.py"
        a_file.write_text("x = 1\n")
        result = runner.invoke(app, ["run", "--repo", str(a_file)])
        assert result.exit_code != 0

    def test_dry_run_flag(self, tmp_path):
        result = runner.invoke(app, ["run", "--repo", str(tmp_path), "--dry-run"])
        assert result.exit_code == 0

    def test_invalid_approach_exits_nonzero(self, tmp_path):
        result = runner.invoke(app, ["run", "--repo", str(tmp_path), "--approach", "invalid"])
        assert result.exit_code != 0

    def test_valid_approach_single(self, tmp_path):
        result = runner.invoke(app, ["run", "--repo", str(tmp_path), "--approach", "single"])
        assert result.exit_code == 0

    def test_valid_approach_multi(self, tmp_path):
        result = runner.invoke(app, ["run", "--repo", str(tmp_path), "--approach", "multi"])
        assert result.exit_code == 0


class TestExecuteCommand:
    def test_execute_help(self):
        result = runner.invoke(app, ["execute", "--help"])
        assert result.exit_code == 0
        assert "--repo" in result.output
        assert "--no-coverage" in result.output
        assert "--json" in result.output

    def test_execute_invalid_path_fails(self, tmp_path):
        nonexistent = str(tmp_path / "does_not_exist_987")
        result = runner.invoke(app, ["execute", "--repo", nonexistent])
        assert result.exit_code != 0

    def test_execute_benchmark_repo(self):
        benchmark = Path(__file__).parent.parent / "benchmarks" / "repositories" / "python_simple"
        result = runner.invoke(app, ["execute", "--repo", str(benchmark)])
        assert result.exit_code == 0
        assert "Test Execution" in result.output
        assert "Passed" in result.output

    def test_execute_benchmark_json(self):
        import json
        benchmark = Path(__file__).parent.parent / "benchmarks" / "repositories" / "python_simple"
        result = runner.invoke(app, ["execute", "--repo", str(benchmark), "--json"])
        assert result.exit_code == 0
        start = result.output.find("{")
        assert start != -1
        decoder = json.JSONDecoder()
        data, _ = decoder.raw_decode(result.output, start)
        assert data["status"] == "passed"
        assert data["summary"]["passed"] > 0


    def test_execute_no_coverage(self):
        benchmark = Path(__file__).parent.parent / "benchmarks" / "repositories" / "python_simple"
        result = runner.invoke(app, ["execute", "--repo", str(benchmark), "--no-coverage"])
        assert result.exit_code == 0
        assert "not_attempted" in result.output.lower() or "0" in result.output


class TestGenerateCommand:
    def test_generate_help(self):
        result = runner.invoke(app, ["generate", "--help"])
        assert result.exit_code == 0
        assert "generate" in result.output.lower()
        assert "--repo" in result.output

    def test_generate_invalid_path_fails(self, tmp_path):
        nonexistent = tmp_path / "does_not_exist"
        result = runner.invoke(app, ["generate", "--repo", str(nonexistent)])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_generate_dry_run_with_mocked_llm(self, tmp_path, monkeypatch):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        target = src_dir / "calc.py"
        target.write_text("def add(a, b): return a + b\n", encoding="utf-8")

        from testpilot.llm.client import BaseLLMClient, LLMClientFactory, LLMResponse

        class FakeClient(BaseLLMClient):
            @property
            def provider_name(self) -> str:
                return "fake"

            @property
            def model_name(self) -> str:
                return "fake-model"

            def chat(self, messages, **kwargs):
                return LLMResponse(content="```python\ndef test_add(): assert 1 + 1 == 2\n```")

        monkeypatch.setattr(LLMClientFactory, "from_settings", lambda s: FakeClient())

        result = runner.invoke(app, ["generate", "--repo", str(tmp_path), "--dry-run"])
        assert result.exit_code == 0
        assert "test_add" in result.output
        assert "dry-run" in result.output.lower()

    def test_generate_json_output(self, tmp_path, monkeypatch):
        import json

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        target = src_dir / "calc.py"
        target.write_text("def add(a, b): return a + b\n", encoding="utf-8")

        from testpilot.llm.client import BaseLLMClient, LLMClientFactory, LLMResponse

        class FakeClient(BaseLLMClient):
            @property
            def provider_name(self) -> str:
                return "fake"

            @property
            def model_name(self) -> str:
                return "fake-model"

            def chat(self, messages, **kwargs):
                return LLMResponse(content="```python\ndef test_add(): assert 1 + 1 == 2\n```")

        monkeypatch.setattr(LLMClientFactory, "from_settings", lambda s: FakeClient())

        result = runner.invoke(app, ["generate", "--repo", str(tmp_path), "--json", "--dry-run"])
        assert result.exit_code == 0
        start = result.output.find("{")
        assert start != -1
        decoder = json.JSONDecoder()
        data, _ = decoder.raw_decode(result.output, start)
        assert data["status"] == "success"
        assert len(data["generated_files"]) == 1


class TestRepairCommand:
    def test_repair_help(self):
        result = runner.invoke(app, ["repair", "--help"])
        assert result.exit_code == 0
        assert "repair" in result.output.lower()
        assert "--repo" in result.output

    def test_repair_invalid_path_fails(self, tmp_path):
        nonexistent = tmp_path / "does_not_exist"
        result = runner.invoke(app, ["repair", "--repo", str(nonexistent)])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_repair_benchmark_no_failures(self):
        benchmark = Path(__file__).parent.parent / "benchmarks" / "repositories" / "python_simple"
        result = runner.invoke(app, ["repair", "--repo", str(benchmark)])
        assert result.exit_code == 0
        assert "no_failures" in result.output.lower()

    def test_repair_json_output(self):
        import json
        benchmark = Path(__file__).parent.parent / "benchmarks" / "repositories" / "python_simple"
        result = runner.invoke(app, ["repair", "--repo", str(benchmark), "--json"])
        assert result.exit_code == 0
        start = result.output.find("{")
        assert start != -1
        decoder = json.JSONDecoder()
        data, _ = decoder.raw_decode(result.output, start)
        assert data["status"] == "no_failures"
        assert data["iterations_run"] == 0


class TestEvaluateCommand:
    def test_evaluate_help(self):
        result = runner.invoke(app, ["evaluate", "--help"])
        assert result.exit_code == 0
        assert "evaluate" in result.output.lower()
        assert "--repo" in result.output
        assert "--isolate" in result.output

    def test_benchmark_help_alias(self):
        result = runner.invoke(app, ["benchmark", "--help"])
        assert result.exit_code == 0
        assert "benchmark" in result.output.lower()
        assert "--repo" in result.output

    def test_evaluate_invalid_path_fails(self, tmp_path):
        nonexistent = tmp_path / "does_not_exist"
        result = runner.invoke(app, ["evaluate", "--repo", str(nonexistent)])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_evaluate_benchmark_json_output(self, monkeypatch):
        import json
        from testpilot.llm.client import BaseLLMClient, LLMClientFactory, LLMResponse

        class FakeClient(BaseLLMClient):
            @property
            def provider_name(self): return "fake"
            @property
            def model_name(self): return "fake-model"
            def chat(self, messages, **kwargs):
                return LLMResponse(
                    content=(
                        "```python\n"
                        "from calculator.converter import celsius_to_fahrenheit\n\n"
                        "def test_celsius():\n"
                        "    assert celsius_to_fahrenheit(0) == 32.0\n"
                        "```"
                    )
                )

        monkeypatch.setattr(LLMClientFactory, "from_settings", lambda s: FakeClient())

        benchmark = Path(__file__).parent.parent / "benchmarks" / "repositories" / "python_simple"
        result = runner.invoke(app, [
            "evaluate",
            "--repo", str(benchmark),
            "--target", "src/calculator/converter.py",
            "--json",
        ])
        assert result.exit_code == 0
        start = result.output.find('{\n  "benchmark_name"')
        if start == -1:
            start = result.output.find('"benchmark_name"')
            if start != -1:
                start = result.output.rfind("{", 0, start)
        assert start != -1
        decoder = json.JSONDecoder(strict=False)
        data, _ = decoder.raw_decode(result.output, start)
        assert data["benchmark_name"] == "python_simple"
        assert data["status"] == "success"
        assert data["tests_generated"] >= 1
        assert data["final_failed"] == 0

    def test_evaluate_benchmark_human_output(self, monkeypatch):
        from testpilot.llm.client import BaseLLMClient, LLMClientFactory, LLMResponse

        class FakeClient(BaseLLMClient):
            @property
            def provider_name(self): return "fake"
            @property
            def model_name(self): return "fake-model"
            def chat(self, messages, **kwargs):
                return LLMResponse(
                    content=(
                        "```python\n"
                        "from calculator.converter import celsius_to_fahrenheit\n\n"
                        "def test_celsius():\n"
                        "    assert celsius_to_fahrenheit(0) == 32.0\n"
                        "```"
                    )
                )

        monkeypatch.setattr(LLMClientFactory, "from_settings", lambda s: FakeClient())

        benchmark = Path(__file__).parent.parent / "benchmarks" / "repositories" / "python_simple"
        result = runner.invoke(app, [
            "evaluate",
            "--repo", str(benchmark),
            "--target", "src/calculator/converter.py",
        ])
        assert result.exit_code == 0
        assert "Benchmark Evaluation" in result.output
        assert "Overall Status" in result.output


