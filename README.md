# TestPilot AI

**Autonomous Multi-Agent Software Testing, Execution, Repair & Benchmarking Platform**

> An agentic Python testing platform that analyzes software repositories, detects untested coverage gaps, generates syntax-validated pytest tests, executes them safely in subprocesses, diagnoses failures with LLMs, repairs failing tests in bounded feedback loops, and benchmarks real coverage improvements — all protected by workspace isolation and source-defect safety gates.

---

## Current Status: Phase 1B–5 Fully Implemented & Verified

| Phase | Component | Implementation Status | Verified Output |
|---|---|---|---|
| **Phase 1B** | Repository Analysis & Doctor | ✅ Complete | AST parsing, symbol extraction, gap detection |
| **Phase 2** | Test Execution Agent | ✅ Complete | Subprocess pytest runner, JUnit XML parsing, real coverage |
| **Phase 3** | Test Generation Agent | ✅ Complete | Contextual prompt builder, AST validation, safe disk writing |
| **Phase 4** | Failure Analysis & Repair | ✅ Complete | Heuristic/LLM diagnosis, unified diffs, bounded repair loop, safety gate |
| **Phase 5** | Evaluation & Benchmarking | ✅ Complete | Full Analyze→Generate→Execute→Repair workflow, workspace isolation, metrics.jsonl |

- **Test Suite**: **342 passed**, 0 failures
- **Static Type Checking**: **Mypy clean** (0 issues across all 27 source files)
- **Code Quality**: Strict Pydantic models, no external paid API requirement for tests, zero repo mutation during benchmark runs.

---

## The Problem TestPilot Solves

Writing and maintaining high-quality test suites is one of the most time-consuming parts of software engineering:
1. **Uncovered Gaps**: Developers miss edge cases, branches, and untested modules.
2. **Brittle AI Test Code**: Naive LLM generation frequently hallucinates non-existent imports, invalid syntax, or wrong function signatures.
3. **Flaky & Broken Tests**: Generated tests often fail on first run due to off-by-one assertions or missing fixtures.
4. **Hiding Real Bugs**: Unsafe AI repair tools often modify test assertions to force tests to pass even when the application code has a genuine bug.
5. **Dirty Repositories**: Automated tools pollute source trees with throwaway test files and cache artifacts.

**How TestPilot AI addresses these:**
- **AST Gatekeeper**: Validates all generated and repaired Python code using `ast.parse` before writing to disk. Broken syntax is never executed.
- **Closed-Loop Repair**: Automatically detects test failures, diagnoses root causes, proposes minimal unified diffs, and re-executes tests in a bounded loop (default: 2 iterations, max: 5).
- **Source Code Defect Safety Gate**: If a failure is diagnosed as a genuine bug in application code (`source_code_defect`), TestPilot halts with `not_repairable` instead of weakening assertions to fake a passing test.
- **Workspace Isolation**: Clones benchmark repositories into isolated temporary workspaces during evaluation (`--isolate`), ensuring the original repository remains 100% clean and reproducible.

---

## End-to-End Pipeline Architecture

```
                             [Target Repository]
                                      │
                         (Optional Workspace Isolation)
                                      │
                                      ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ 1. Phase 1B: Repository Analysis       ──> Discovers language, framework, │
│    (analyze_repository)                    public symbols, coverage gaps  │
│                                                                           │
│ 2. Phase 2:  Baseline Test Execution   ──> Runs pytest, captures baseline │
│    (execute_tests)                         passing tests & cov_before     │
│                                                                           │
│ 3. Phase 3:  Targeted Test Generation  ──> Contextual prompt, LLM call,   │
│    (generate_tests)                        AST syntax & structure check   │
│                                                                           │
│ 4. Phase 2:  Post-Generation Execution ──> Executes suite with new tests   │
│    (execute_tests)                         to detect initial failures     │
│                                                                           │
│ 5. Phase 4:  Failure Analysis & Repair ──> Diagnoses root cause:          │
│    (run_repair_loop)                       • If test issue -> repair loop │
│                                            • If source bug -> SAFETY GATE │
│                                                                           │
│ 6. Phase 2:  Final Test Verification   ──> Measures final pass count,     │
│    (execute_tests)                         coverage_after & cov_delta     │
└───────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                      [BenchmarkEvaluationResult]
                         │                   │
            ┌────────────┘                   └────────────┐
            ▼                                             ▼
  [Rich Human Summary Table]                   [metrics.jsonl Log]
```

All pipeline agents share a serializable [`SessionContext`](src/testpilot/session_context.py) tracking `repository_analysis`, `generation_report`, `execution_report`, `repair_report`, timing, and coverage metrics.

---

## Installation & Setup

### Prerequisites
- Python 3.11 or higher
- Windows, macOS, or Linux
- (Optional) [Ollama](https://ollama.ai/) or an OpenAI API key for live LLM inference. (Mocks are included for offline/test use).

### Setup

```bash
# Clone the repository
git clone https://github.com/your-username/testpilot-ai.git
cd testpilot-ai

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate       # macOS / Linux
# .venv\Scripts\activate        # Windows PowerShell

# Install core dependencies in editable mode
pip install -e ".[dev]"
```

---

## Configuration

Configuration is managed via environment variables and optional `.env` files using Pydantic Settings:

| Variable | Default | Description |
|---|---|---|
| `TESTPILOT_LLM_PROVIDER` | `ollama` | LLM backend: `ollama` or `openai` |
| `TESTPILOT_LLM_MODEL` | `codellama` | Model name (e.g. `gpt-4o-mini`, `codellama`) |
| `OPENAI_API_KEY` | _(empty)_ | OpenAI API key (if using OpenAI provider) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama local daemon endpoint |
| `TESTPILOT_MAX_REPAIR_ITERATIONS` | `2` | Bounded iteration limit for repair loop |
| `TESTPILOT_TEST_EXECUTION_TIMEOUT`| `30.0` | Subprocess pytest execution timeout (seconds) |
| `TESTPILOT_LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `TESTPILOT_OUTPUT_DIR` | `./output` | Destination for session logs and reports |

---

## CLI Reference & Commands

The installed CLI entrypoint is `testpilot`:

### 1. System Information
```bash
testpilot info
```
Displays version, active LLM provider, model settings, and execution limits.

### 2. Repository Analysis (Phase 1B)
```bash
testpilot analyze --repo benchmarks/repositories/python_simple
```
Inspects project layout, packaging files, test framework (`pytest`), extracts public functions/classes via AST, and detects coverage gap targets. Supports `--json` for machine-readable output.

### 3. Environment Doctor (Phase 1B)
```bash
testpilot doctor --repo benchmarks/repositories/python_simple
```
Diagnoses whether pytest, pytest-cov, Python runtime, and package imports are properly configured in the repository environment.

### 4. Test Execution (Phase 2)
```bash
testpilot execute --repo benchmarks/repositories/python_simple
```
Executes pytest in a controlled subprocess with timeout bounds, parses JUnit XML and coverage reports, and outputs structured pass/fail summaries.

### 5. Test Generation (Phase 3)
```bash
# Automatically target uncovered modules
testpilot generate --repo benchmarks/repositories/python_simple

# Explicitly target a specific source module
testpilot generate --repo benchmarks/repositories/python_simple --target src/calculator/converter.py

# Dry-run validation mode (outputs generated code without writing to disk)
testpilot generate --repo benchmarks/repositories/python_simple --dry-run
```

### 6. Failure Analysis & Repair (Phase 4)
```bash
# Execute and automatically repair any failing tests
testpilot repair --repo benchmarks/repositories/python_simple

# Target a specific test file with up to 3 repair iterations
testpilot repair --repo benchmarks/repositories/python_simple --test tests/test_calc.py --max-attempts 3

# Dry-run repair without overwriting test files on disk
testpilot repair --repo benchmarks/repositories/python_simple --dry-run
```

### 7. End-to-End Evaluation & Benchmarking (Phase 5)
```bash
# Run full Analyze -> Generate -> Execute -> Repair pipeline with workspace isolation
testpilot evaluate --repo benchmarks/repositories/python_simple

# Target a specific module and append RunMetrics to benchmarks/results/metrics.jsonl
testpilot evaluate --repo benchmarks/repositories/python_simple --target src/calculator/converter.py --save-metrics

# Benchmark alias command
testpilot benchmark --repo benchmarks/repositories/python_simple

# Output full evaluation results as JSON
testpilot evaluate --repo benchmarks/repositories/python_simple --json
```

---

## Reproducible Demo Walkthrough

Follow these exact steps to demonstrate TestPilot AI on the included benchmarks:

### Step 1 — Analyze the Benchmark Repository
Run analysis on the `python_simple` benchmark:
```bash
testpilot analyze --repo benchmarks/repositories/python_simple
```
**Outcome**: Discovers 26 symbols and detects that `src/calculator/converter.py` is an **uncovered module gap**.

### Step 2 — Verify Baseline Test Execution
Run test execution on the existing test suite:
```bash
testpilot execute --repo benchmarks/repositories/python_simple
```
**Outcome**: 29 passed, 0 failed, line coverage at 65.12% (uncovered: `converter.py`).

### Step 3 — Run Full End-to-End Evaluation
Run the automated pipeline with isolated sandbox execution:
```bash
testpilot evaluate --repo benchmarks/repositories/python_simple --target src/calculator/converter.py
```
**Outcome**:
- Generates 2 syntax-validated pytest tests for `converter.py`.
- Executes tests in sandbox: total passing increases from 29 to 31.
- Line coverage increases from **65.1% to 76.7% (+11.6% delta)**.
- Original repository is untouched.

### Step 4 — Demonstrate the Source Code Defect Safety Gate
Run evaluation on `python_defect` (which has a genuine bug in `validator.py:is_even`):
```bash
testpilot evaluate --repo benchmarks/repositories/python_defect
```
**Outcome**:
- Generated test triggers the bug in `is_even`.
- `FailureAnalysisAgent` diagnoses `SOURCE_CODE_DEFECT`.
- TestPilot halts with `not_repairable`.
- Displays: `Safety Gate Triggered: Real source-code defect detected. Repair Agent refused to alter tests to conceal genuine application bugs.`

---

## Measured Benchmark Results

All metrics are gathered from real test executions and recorded in `benchmarks/results/metrics.jsonl`:

| Benchmark | Target Module | Baseline Tests | Final Tests | Baseline Coverage | Final Coverage | Coverage Delta | Pipeline Status |
|---|---|---|---|---|---|---|---|
| `python_simple` | `src/calculator/converter.py` | 29 | 31 | 65.12% | 76.74% | **+11.62%** | `success` |
| `python_defect` | `src/buggy_pkg/validator.py` | 1 | 1 | 80.00% | 80.00% | 0.00% | `not_repairable` (Safety Gate) |

---

## Verification & Project Health

Run the complete test suite and type checking:

```bash
# Run all 342 unit and integration tests
pytest -q

# Run static type verification across the codebase
mypy src tests/test_evaluation_runner.py
```

**Results**:
- `342 passed in ~97s`
- `Success: no issues found in 27 source files`

---

## Limitations & Future Work

- **Framework Focus**: Current implementation targets Python and `pytest`. Expansion to JavaScript/TypeScript (`jest` / `vitest`) is architected via the modular environment detector.
- **Complex Mocking**: Current test generation focuses on pure functions and classes; automated synthesis of complex external database/network mocks can be extended in future iterations.
- **Comparative Research**: The included `metrics.jsonl` framework supports ongoing research comparing `manual`, `single-prompt`, and `multi-agent` test generation workflows.

---

## IBM Bob 2.0 Hackathon Evidence

This project was developed with **IBM Bob 2.0** as a core pair-programming AI assistant across all implementation phases:
- **Phase 1B**: AST Repository Analyzer & Environment Doctor.
- **Phase 2**: Subprocess Execution Agent & JUnit XML parser.
- **Phase 3**: Test Generation Agent with AST syntax validation.
- **Phase 4**: Failure Analysis, Bounded Repair Loop, and Source Defect Safety Gate.
- **Phase 5**: Evaluation Runner, Workspace Isolation, and Benchmark Metrics.
- **Phase 6**: Final Polish, Documentation, and Demo Verification.

All session transcripts, task execution history, and test logs are archived in `evidence/bob-sessions/`.

---

## License

MIT License — see [LICENSE](LICENSE).
