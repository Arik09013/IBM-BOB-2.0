# TestPilot AI — Architecture & Design Document

> **Status key:**
> - ✅ **Implemented** — code exists and tests pass
> - 🔲 **Planned** — designed but not yet coded
> - 🔬 **Experimental** — research feature, subject to change

---

## 1. Problem Definition

Writing, maintaining, and validating software tests is one of the most time-consuming and neglected parts of the development lifecycle. Developers who encounter an unfamiliar codebase face compounding friction:

- **Repository comprehension overhead** — understanding structure, language, and coverage before a single test can be written.
- **Gap blindness** — without tooling, it is difficult to tell which logic paths have zero test coverage.
- **Repetitive test boilerplate** — generating standard test patterns (CRUD, error paths, edge cases) is tedious.
- **Slow failure triage** — mapping test failures back to root causes requires reading stack traces and locating defects.
- **No synthesis** — no automated layer aggregates coverage data, test results, and fix suggestions into a single quality report.

**Core thesis:** An agentic pipeline that wraps a repository, reasons about it, generates targeted tests, executes them, diagnoses failures, proposes fixes, and produces a quality report will measurably reduce the time-to-confident-merge.

---

## 2. Target Users

| Persona | Need | Benefit |
|---|---|---|
| Solo developer / hobbyist | Fast, low-friction test generation | Immediate coverage with minimal config |
| Developer joining a new team | Understand what is and is not tested | Orientation report + gap analysis in minutes |
| Engineer in a time-boxed sprint | Validate a feature branch without hand-writing all tests | Auto-generated tests + failure triage |
| Researcher / student | Compare manual, single-agent, and multi-agent approaches | Reproducible experiments with structured metrics |

---

## 3. MVP Features ✅ (Phase 0 + 1–4)

1. Repository ingestion (local path or GitHub URL)
2. Coverage gap analysis (untested functions)
3. Test generation (pytest / Jest)
4. Test execution (subprocess)
5. Failure analysis (root cause + location)
6. Repair suggestion (unified diff patch)
7. Re-validation loop (bounded, configurable)
8. Quality report (Markdown + JSON)
9. CLI (`testpilot run --repo <path>`)
10. Session logging (JSONL)

## Non-MVP (out of scope)

- Web UI / dashboard
- CI/CD integration or GitHub Actions
- Auto-apply repair patches to source
- Multi-language in same run (>2)
- Distributed / cloud test execution
- Authentication or multi-user support
- Integration or E2E testing
- LLM fine-tuning

---

## 4. Agent Architecture

### Component Overview

```
┌──────────────────────────────────────────────────────────────┐
│                       Pipeline Orchestrator                   │
│  (pure control-flow; no LLM calls; manages SessionContext)   │
└──────────────────────┬───────────────────────────────────────┘
                       │ passes SessionContext
          ┌────────────┼────────────┐
          ▼            ▼            ▼  ...
    ┌──────────┐ ┌──────────┐ ┌──────────┐
    │ Analyzer │ │Generator │ │ Executor │  ...
    └──────────┘ └──────────┘ └──────────┘
```

### Agent Descriptions

| Agent | Status | Receives | Produces |
|---|---|---|---|
| **Repository Analyzer** | 🔲 Phase 1 | Repo path | RepoContext (language, framework, gap list, coverage_before) |
| **Test Generation** | 🔲 Phase 1 | RepoContext + gap targets | Generated test files |
| **Execution** | 🔲 Phase 2 | Test file paths | ExecutionResult (pass/fail/error per test) |
| **Failure Analysis** | 🔲 Phase 3 | Failed ExecutionResults + source | FailureReport (root cause, location) |
| **Repair** | 🔲 Phase 3 | FailureReport + source | RepairPatch (unified diff + rationale) |
| **Report** | 🔲 Phase 4 | All prior artifacts | report.md + report.json |

### Pipeline Orchestrator ✅ (Phase 0 placeholder)

- Thin control-flow Python class (no LLM)
- Drives the pipeline sequence
- Manages `SessionContext` (single shared state object)
- Enforces repair loop limit (`MAX_ITERATIONS`, default 2)
- No-improvement early exit
- Always produces a `PipelineResult`, even on failure

### Inter-agent Communication

All agents receive and return a `SessionContext` object. The orchestrator persists the context to disk after each step. This makes the pipeline resumable and provides a complete audit trail for research.

### Parallelism Opportunities 🔬

| Opportunity | When useful |
|---|---|
| Test generation for multiple files | When gap list has >3 independent files |
| Failure analysis per test | When >5 tests fail (each is independent) |
| Repair suggestions per failure | Independent failures → independent patches |

---

## 5. Session Context ✅

`SessionContext` (Pydantic model) is the single source of truth for a run:

- Run ID, repo path, approach
- Pipeline step tracking
- Analysis outputs (language, framework, gap list, coverage_before)
- Generation outputs (generated file paths, count)
- Execution results (per-test pass/fail/error, coverage_after)
- Repair attempts (patches proposed, patches resolved)
- Timing information
- LLM usage counters
- Artefact paths
- Errors and warnings

---

## 6. End-to-End Workflow

```
Repository Input
      │
      ▼ [Repository Analyzer]
   RepoContext
      │
      ▼ [Test Generation Agent]
   Generated Test Files
      │
      ▼ [Execution Agent]
   ExecutionResult
      │ failures?
      ├─ yes ──▶ [Failure Analysis Agent]
      │               │
      │          FailureReport
      │               │
      │          [Repair Agent]
      │               │
      │          RepairPatch
      │               │
      │          [Execution Agent — re-validation]
      │               │
      │          ◀────┘ (loop, max MAX_ITERATIONS)
      │
      ▼ [Report Agent]
   report.md + report.json
```

### Failure States & Recovery

| Step | Failure | Recovery |
|---|---|---|
| Ingest | Invalid path | Abort with message |
| Analysis | Unsupported language | Warn + skip |
| Analysis | No gaps found | Report "coverage appears complete" + exit |
| Generation | LLM returns invalid syntax | Retry once with stricter prompt; skip on repeat failure |
| Execution | Test runner not found | Prompt to install; fallback to dry-run |
| Execution | Timeout | Mark as error, continue |
| Repair | Patch fails syntax check | Discard + log |
| Repair | No improvement after iteration | Early exit |
| Report | Missing artefacts | Render "N/A" for missing fields |

---

## 7. Technology Stack

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | Best LLM tooling ecosystem |
| LLM | OpenAI API or Ollama (local) | Pluggable via `llm_client.py` |
| Orchestration | Custom Python pipeline | Transparent, no hidden abstractions |
| Static analysis | `ast` stdlib + `tree-sitter` | Free, offline, multi-language |
| Coverage | `coverage.py` / `jest --coverage` | Free, machine-readable output |
| Test frameworks | pytest (Python), Jest (JS/TS) | Most common; best LLM training overlap |
| CLI | `typer` | Typed, zero boilerplate |
| Config | `pydantic-settings` + YAML | Validated config, clear error messages |
| Secrets | `python-dotenv` + `.env` (gitignored) | Standard pattern, nothing committed |
| Logging | Python `logging` + JSONL session log | Machine-readable for research |
| Report rendering | Jinja2 → Markdown + JSON | No JS build chain needed |

---

## 8. Evaluation Metrics 🔬

Each run produces one `RunMetrics` record appended to `benchmarks/results/metrics.jsonl`.

| Metric | Definition |
|---|---|
| `coverage_delta` | Coverage % after − before |
| `tests_generated` | Total test functions produced |
| `tests_passed` | Tests passing on first run |
| `pass_rate` | tests_passed / tests_generated |
| `invalid_tests` | Tests with syntax/import errors |
| `logic_failures` | Tests revealing source defects |
| `repair_success_rate` | Repairs resolved / repairs attempted |
| `iteration_count` | Repair loop cycles used |
| `human_interventions` | Times user was prompted |
| `wall_clock_seconds` | Total runtime |
| `llm_calls` | Total LLM API calls |
| `token_usage` | Prompt + completion tokens |

---

## 9. Research Experiment Plan 🔬

Three experimental conditions on the same benchmark repositories:

| Condition | Description |
|---|---|
| `manual` | Developer writes tests by hand (baseline, recorded manually) |
| `single` | One LLM call per target, no repair loop |
| `multi` | Full multi-agent TestPilot pipeline |

**Protocol:**
1. Run all three conditions against each of ≥3 benchmark repos.
2. Record all metrics per run (no cherry-picking).
3. Use `evaluation/compare.py` to produce a comparison table.
4. Report effect sizes without claiming statistical significance (small N).

---

## 10. Repository Structure

```
testpilot-ai/
├── src/testpilot/           ✅ Application source
│   ├── agents/base.py       ✅ Agent base interface
│   ├── llm/client.py        ✅ LLM abstraction (stub + factory)
│   ├── models/evaluation.py ✅ Research metrics schemas
│   ├── orchestration/       ✅ Pipeline orchestrator (placeholder)
│   ├── utils/logging.py     ✅ Structured logging + JSONL session writer
│   ├── cli.py               ✅ Typer CLI
│   ├── config.py            ✅ pydantic-settings configuration
│   └── session_context.py   ✅ Shared pipeline state
├── tests/                   ✅ Test suite (config, CLI, models, agents, LLM)
├── benchmarks/              🔲 Sample repos added in Phase 1
├── docs/                    ✅ This file
├── evidence/bob-sessions/   🔲 IBM Bob session logs (added during development)
├── prompts/                 🔲 LLM prompt templates (Phase 1)
└── pyproject.toml           ✅
```

---

## 11. IBM Bob 2.0 Usage

IBM Bob 2.0 is used as the primary AI development assistant throughout all phases:

| Phase | Bob contribution |
|---|---|
| 0 | Architecture design, scaffolding, all foundational code |
| 1 | Repository Analyzer implementation, prompt engineering |
| 2 | Execution Agent, pytest/jest runner wrappers |
| 3 | Failure Analysis and Repair Agent implementation |
| 4 | Report templates, CLI polish, benchmark evaluation |

Session logs and screenshots stored in `evidence/bob-sessions/`.

---

*Last updated: Phase 0 — Foundation*
