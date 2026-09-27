"""
Tests for evaluation data models (testpilot.models.evaluation).

Verifies:
- RunMetrics can be instantiated and computed fields work.
- ConditionSummary and BenchmarkConfig instantiate cleanly.
- append_metrics writes a valid JSONL line.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from testpilot.models.evaluation import (
    BenchmarkConfig,
    ConditionSummary,
    ExperimentApproach,
    RunMetrics,
    append_metrics,
)


class TestRunMetrics:
    def test_minimal_construction(self):
        m = RunMetrics(run_id="abc123", repository="test-repo", approach=ExperimentApproach.MULTI)
        assert m.run_id == "abc123"
        assert m.approach == ExperimentApproach.MULTI

    def test_coverage_delta_none_when_missing(self):
        m = RunMetrics(run_id="x", repository="r", approach=ExperimentApproach.SINGLE)
        assert m.coverage_delta is None

    def test_coverage_delta_computed(self):
        m = RunMetrics(
            run_id="x", repository="r", approach=ExperimentApproach.MULTI,
            coverage_before=20.0, coverage_after=68.0
        )
        assert m.coverage_delta == pytest.approx(48.0, abs=0.01)

    def test_pass_rate_none_when_no_tests(self):
        m = RunMetrics(run_id="x", repository="r", approach=ExperimentApproach.MULTI)
        assert m.pass_rate is None

    def test_pass_rate_computed(self):
        m = RunMetrics(
            run_id="x", repository="r", approach=ExperimentApproach.MULTI,
            tests_generated=10, tests_passed=8
        )
        assert m.pass_rate == pytest.approx(0.8, abs=0.001)

    def test_repair_success_rate_none_when_no_repairs(self):
        m = RunMetrics(run_id="x", repository="r", approach=ExperimentApproach.MULTI)
        assert m.repair_success_rate is None

    def test_repair_success_rate_computed(self):
        m = RunMetrics(
            run_id="x", repository="r", approach=ExperimentApproach.MULTI,
            repair_attempts=4, successful_repairs=3
        )
        assert m.repair_success_rate == pytest.approx(0.75, abs=0.001)

    def test_all_approaches_valid(self):
        for approach in ExperimentApproach:
            m = RunMetrics(run_id="x", repository="r", approach=approach)
            assert m.approach == approach


class TestConditionSummary:
    def test_construction(self):
        s = ConditionSummary(repository="repo", approach=ExperimentApproach.MANUAL)
        assert s.run_count == 0
        assert s.mean_coverage_delta is None


class TestBenchmarkConfig:
    def test_construction(self):
        b = BenchmarkConfig(
            benchmark_id="bench-01",
            description="Simple Python calculator",
            repository_path="./benchmarks/repositories/python_simple",
            language="python",
            test_framework="pytest",
            llm_provider="ollama",
            llm_model="codellama",
            max_repair_iterations=2,
            approach=ExperimentApproach.MULTI,
        )
        assert b.testpilot_version == "0.1.0"


class TestAppendMetrics:
    def test_creates_jsonl_file(self, tmp_path):
        m = RunMetrics(
            run_id="test001",
            repository="my-repo",
            approach=ExperimentApproach.MULTI,
            tests_generated=5,
            tests_passed=4,
        )
        path = append_metrics(m, tmp_path)
        assert path.exists()
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

    def test_appends_multiple_rows(self, tmp_path):
        for i in range(3):
            m = RunMetrics(run_id=f"r{i}", repository="repo", approach=ExperimentApproach.SINGLE)
            append_metrics(m, tmp_path)

        path = tmp_path / "metrics.jsonl"
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3

    def test_jsonl_is_parseable(self, tmp_path):
        import json
        m = RunMetrics(run_id="parse-test", repository="r", approach=ExperimentApproach.MULTI, tests_generated=7)
        append_metrics(m, tmp_path)
        line = (tmp_path / "metrics.jsonl").read_text(encoding="utf-8").strip()
        parsed = json.loads(line)
        assert parsed["run_id"] == "parse-test"
        assert parsed["tests_generated"] == 7
