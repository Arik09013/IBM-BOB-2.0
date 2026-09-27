"""Models package for TestPilot AI."""

from testpilot.models.evaluation import (
    BenchmarkConfig,
    BenchmarkEvaluationResult,
    BenchmarkEvaluationStatus,
    ConditionSummary,
    ExperimentApproach,
    RunMetrics,
    SuiteEvaluationResult,
    append_metrics,
)
from testpilot.models.execution import (
    ExecutionCoverage,
    ExecutionReport,
    ExecutionStatus,
    ExecutionSummary,
    TestCaseResultItem,
    TestStatus,
)
from testpilot.models.generation import (
    GeneratedTestCase,
    GeneratedTestFile,
    GenerationReport,
    GenerationStatus,
)
from testpilot.models.repair import (
    FailureAnalysis,
    FailureCategory,
    RepairAttemptRecord,
    RepairReport,
    RepairStatus,
)
from testpilot.models.repository import (
    CoverageGap,
    CoverageStatus,
    CoverageSummary,
    FileSummary,
    RepositoryAnalysis,
    SymbolInfo,
    SymbolKind,
)

__all__ = [
    # evaluation
    "BenchmarkConfig",
    "BenchmarkEvaluationResult",
    "BenchmarkEvaluationStatus",
    "ConditionSummary",
    "ExperimentApproach",
    "RunMetrics",
    "SuiteEvaluationResult",
    "append_metrics",
    # execution
    "ExecutionCoverage",
    "ExecutionReport",
    "ExecutionStatus",
    "ExecutionSummary",
    "TestCaseResultItem",
    "TestStatus",
    # generation
    "GeneratedTestCase",
    "GeneratedTestFile",
    "GenerationReport",
    "GenerationStatus",
    # repair
    "FailureAnalysis",
    "FailureCategory",
    "RepairAttemptRecord",
    "RepairReport",
    "RepairStatus",
    # repository
    "CoverageGap",
    "CoverageStatus",
    "CoverageSummary",
    "FileSummary",
    "RepositoryAnalysis",
    "SymbolInfo",
    "SymbolKind",
]

