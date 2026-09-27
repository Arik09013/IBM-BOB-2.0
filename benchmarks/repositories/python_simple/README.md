# python_simple — TestPilot AI Benchmark Repository

A small, self-contained Python project used as a reproducible benchmark
for the TestPilot AI Repository Analyzer and future Test Generation Agent.

## Structure

```
python_simple/
├── src/
│   └── calculator/
│       ├── __init__.py
│       ├── arithmetic.py   # basic math operations
│       ├── statistics.py   # statistical helpers
│       └── converter.py    # unit conversion (INTENTIONALLY UNCOVERED)
├── tests/
│   ├── __init__.py
│   ├── test_arithmetic.py
│   └── test_statistics.py
├── pyproject.toml
└── README.md
```

## Intentional coverage gaps

`src/calculator/converter.py` — **no tests exist for this module**.
This gap is intentional so the analyzer can detect it.

Within `arithmetic.py`, the `divide` function's zero-division branch
is intentionally untested.

## Running the tests

```bash
cd benchmarks/repositories/python_simple
pip install pytest pytest-cov
pytest --cov=src --cov-report=term-missing
```

## Expected output (approximate)

```
TOTAL   ~60 statements   ~15 missing   ~75% coverage
```

Exact numbers depend on the Python version and pytest-cov version.
