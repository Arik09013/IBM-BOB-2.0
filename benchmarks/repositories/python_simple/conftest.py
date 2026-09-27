"""
conftest.py for the python_simple benchmark.

Adds the benchmark's src/ directory to sys.path so that pytest can import
the calculator package without requiring it to be installed into the
calling Python environment.

This is the standard pytest solution for src-layout projects.
See: https://docs.pytest.org/en/stable/reference/fixtures.html#conftest-py-sharing-fixtures-across-files
"""

import sys
from pathlib import Path

# Insert src/ at the front of sys.path so `import calculator` works
sys.path.insert(0, str(Path(__file__).parent / "src"))
