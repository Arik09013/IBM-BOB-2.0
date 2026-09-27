"""
arithmetic.py — Basic arithmetic operations.

Part of the TestPilot AI python_simple benchmark.

Coverage note:
  - add, subtract, multiply are tested.
  - divide zero-division branch is INTENTIONALLY UNCOVERED.
"""

from __future__ import annotations


def add(a: float, b: float) -> float:
    """Return the sum of *a* and *b*."""
    return a + b


def subtract(a: float, b: float) -> float:
    """Return *a* minus *b*."""
    return a - b


def multiply(a: float, b: float) -> float:
    """Return the product of *a* and *b*."""
    return a * b


def divide(a: float, b: float) -> float:
    """
    Return *a* divided by *b*.

    Raises
    ------
    ZeroDivisionError
        When *b* is zero.  This branch is intentionally uncovered.
    """
    if b == 0:
        raise ZeroDivisionError("Cannot divide by zero.")
    return a / b


def power(base: float, exponent: int) -> float:
    """Return *base* raised to *exponent*."""
    return base ** exponent


def absolute(value: float) -> float:
    """Return the absolute value of *value*."""
    return abs(value)


class Calculator:
    """
    A stateful calculator that remembers the last result.

    Example
    -------
    >>> calc = Calculator()
    >>> calc.add(3, 4)
    7.0
    >>> calc.last_result
    7.0
    """

    def __init__(self) -> None:
        self.last_result: float = 0.0
        self._history: list[float] = []

    def add(self, a: float, b: float) -> float:
        """Add two numbers and store the result."""
        result = add(a, b)
        self._store(result)
        return result

    def subtract(self, a: float, b: float) -> float:
        """Subtract *b* from *a* and store the result."""
        result = subtract(a, b)
        self._store(result)
        return result

    def multiply(self, a: float, b: float) -> float:
        """Multiply two numbers and store the result."""
        result = multiply(a, b)
        self._store(result)
        return result

    def divide(self, a: float, b: float) -> float:
        """Divide *a* by *b* and store the result."""
        result = divide(a, b)
        self._store(result)
        return result

    def clear(self) -> None:
        """Reset the calculator state."""
        self.last_result = 0.0
        self._history.clear()

    def history(self) -> list[float]:
        """Return a copy of the result history."""
        return list(self._history)

    def _store(self, value: float) -> None:
        self.last_result = value
        self._history.append(value)
