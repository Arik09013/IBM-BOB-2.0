"""
CLI tests for the `testpilot analyze` command.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from testpilot.cli import app

runner = CliRunner()

BENCHMARK = Path(__file__).parent.parent / "benchmarks" / "repositories" / "python_simple"


class TestAnalyzeHelp:
    def test_help_exits_zero(self):
        result = runner.invoke(app, ["analyze", "--help"])
        assert result.exit_code == 0

    def test_help_mentions_repo(self):
        result = runner.invoke(app, ["analyze", "--help"])
        assert "--repo" in result.output


class TestAnalyzeInvalidPath:
    def test_nonexistent_path_exits_nonzero(self, tmp_path):
        bad = str(tmp_path / "no_such_dir_xyz")
        result = runner.invoke(app, ["analyze", "--repo", bad])
        assert result.exit_code != 0

    def test_error_message_shown(self, tmp_path):
        bad = str(tmp_path / "missing")
        result = runner.invoke(app, ["analyze", "--repo", bad])
        assert "Error" in result.output or "error" in result.output.lower()

    def test_file_path_rejected(self, tmp_path):
        f = tmp_path / "file.py"
        f.write_text("x=1\n", encoding="utf-8")
        result = runner.invoke(app, ["analyze", "--repo", str(f)])
        assert result.exit_code != 0


class TestAnalyzeValidPath:
    def test_valid_path_exits_zero(self, tmp_path):
        (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")
        result = runner.invoke(app, ["analyze", "--repo", str(tmp_path), "--no-coverage"])
        assert result.exit_code == 0

    def test_output_contains_language(self, tmp_path):
        (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")
        result = runner.invoke(app, ["analyze", "--repo", str(tmp_path), "--no-coverage"])
        assert "Python" in result.output or "python" in result.output.lower()

    def test_output_contains_source_files(self, tmp_path):
        (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")
        result = runner.invoke(app, ["analyze", "--repo", str(tmp_path), "--no-coverage"])
        assert "Source files" in result.output

    def test_no_coverage_flag_skips_coverage(self, tmp_path):
        (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")
        result = runner.invoke(app, ["analyze", "--repo", str(tmp_path), "--no-coverage"])
        assert "not_attempted" in result.output.lower() or "coverage" in result.output.lower()


class TestAnalyzeJsonOutput:
    def _extract_json(self, output: str) -> dict:
        """Extract the first complete JSON object from combined output."""
        import json
        decoder = json.JSONDecoder()
        start = output.find("{")
        if start == -1:
            raise ValueError(f"No JSON found in output: {output!r}")
        obj, _ = decoder.raw_decode(output, start)
        return obj

    def test_json_flag_produces_json(self, tmp_path):
        (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")
        result = runner.invoke(app, ["analyze", "--repo", str(tmp_path), "--no-coverage", "--json"])
        assert result.exit_code == 0
        parsed = self._extract_json(result.output)
        assert "repository_path" in parsed
        assert "symbols" in parsed

    def test_json_output_has_coverage_summary(self, tmp_path):
        (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")
        result = runner.invoke(app, ["analyze", "--repo", str(tmp_path), "--no-coverage", "--json"])
        assert result.exit_code == 0
        parsed = self._extract_json(result.output)
        assert "coverage_summary" in parsed


class TestAnalyzeBenchmark:
    def test_benchmark_exits_zero(self):
        if not BENCHMARK.exists():
            pytest.skip("Benchmark repository not found")
        result = runner.invoke(app, ["analyze", "--repo", str(BENCHMARK), "--no-coverage"])
        assert result.exit_code == 0

    def test_benchmark_shows_pytest(self):
        if not BENCHMARK.exists():
            pytest.skip("Benchmark repository not found")
        result = runner.invoke(app, ["analyze", "--repo", str(BENCHMARK), "--no-coverage"])
        assert "pytest" in result.output.lower()

    def test_benchmark_shows_source_count(self):
        if not BENCHMARK.exists():
            pytest.skip("Benchmark repository not found")
        result = runner.invoke(app, ["analyze", "--repo", str(BENCHMARK), "--no-coverage"])
        assert "Source files" in result.output
