"""
Tests for SessionContext (testpilot.session_context).

Verifies:
- SessionContext can be instantiated with valid data.
- Computed properties return correct values.
- Serialisation/deserialisation round-trip works.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from testpilot.session_context import (
    PipelineStep,
    RepairAttempt,
    SessionContext,
    TestCaseResult,
    TimingInfo,
)


class TestSessionContextInstantiation:
    def test_default_construction(self):
        ctx = SessionContext()
        assert ctx.run_id
        assert len(ctx.run_id) == 12
        assert ctx.current_step == PipelineStep.INIT
        assert ctx.iteration_count == 0

    def test_with_repo_path(self, tmp_path):
        ctx = SessionContext(repo_path=tmp_path, repo_identifier="test-repo")
        assert ctx.repo_path == tmp_path
        assert ctx.repo_identifier == "test-repo"

    def test_approach_defaults_to_multi(self):
        ctx = SessionContext()
        assert ctx.approach == "multi"

    def test_run_id_is_unique(self):
        ids = {SessionContext().run_id for _ in range(20)}
        assert len(ids) == 20


class TestComputedProperties:
    def _make_context_with_results(self) -> SessionContext:
        ctx = SessionContext()
        ctx.test_results = [
            TestCaseResult(test_id="t1", test_file="f.py", target_function="add", status="passed"),
            TestCaseResult(test_id="t2", test_file="f.py", target_function="sub", status="failed", is_logic_failure=True),
            TestCaseResult(test_id="t3", test_file="f.py", target_function="mul", status="error", is_invalid=True),
            TestCaseResult(test_id="t4", test_file="f.py", target_function="div", status="passed"),
        ]
        return ctx

    def test_tests_passed(self):
        ctx = self._make_context_with_results()
        assert ctx.tests_passed == 2

    def test_tests_failed(self):
        ctx = self._make_context_with_results()
        assert ctx.tests_failed == 2

    def test_invalid_tests(self):
        ctx = self._make_context_with_results()
        assert ctx.invalid_tests == 1

    def test_logic_failures(self):
        ctx = self._make_context_with_results()
        assert ctx.logic_failures == 1

    def test_successful_repairs(self):
        ctx = SessionContext()
        ctx.repair_attempts = [
            RepairAttempt(iteration=1, target_test_id="t2", resolved=True),
            RepairAttempt(iteration=1, target_test_id="t3", resolved=False),
        ]
        assert ctx.successful_repairs == 1


class TestSerialisationRoundTrip:
    def test_save_and_load(self, tmp_path):
        ctx = SessionContext(repo_identifier="my-repo", approach="single")
        ctx.output_dir = tmp_path
        ctx.gap_targets = ["module.add", "module.subtract"]
        ctx.warnings.append("test warning")

        saved_path = ctx.save(tmp_path / "ctx.json")
        assert saved_path.exists()

        loaded = SessionContext.load(saved_path)
        assert loaded.run_id == ctx.run_id
        assert loaded.repo_identifier == "my-repo"
        assert loaded.approach == "single"
        assert loaded.gap_targets == ["module.add", "module.subtract"]
        assert "test warning" in loaded.warnings

    def test_round_trip_preserves_test_results(self, tmp_path):
        ctx = SessionContext()
        ctx.test_results = [
            TestCaseResult(test_id="x", test_file="t.py", target_function="f", status="passed")
        ]
        path = ctx.save(tmp_path / "ctx2.json")
        loaded = SessionContext.load(path)
        assert len(loaded.test_results) == 1
        assert loaded.test_results[0].status == "passed"


class TestTimingInfo:
    def test_total_seconds_none_when_not_finished(self):
        t = TimingInfo()
        assert t.total_seconds is None

    def test_total_seconds_computed(self):
        from datetime import datetime, timedelta, timezone
        start = datetime.now(tz=timezone.utc)
        t = TimingInfo(run_started_at=start, run_finished_at=start + timedelta(seconds=42))
        assert t.total_seconds == pytest.approx(42.0, abs=0.1)
