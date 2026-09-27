"""
Tests for arithmetic.py.

Coverage note:
  - divide() zero-division branch is INTENTIONALLY NOT TESTED.
  - Calculator.divide() is INTENTIONALLY NOT TESTED.
"""

import pytest

from calculator.arithmetic import (
    Calculator,
    absolute,
    add,
    divide,
    multiply,
    power,
    subtract,
)


class TestAdd:
    def test_positive(self):
        assert add(2, 3) == 5

    def test_negative(self):
        assert add(-1, -1) == -2

    def test_float(self):
        assert add(1.5, 2.5) == 4.0

    def test_zero(self):
        assert add(0, 0) == 0


class TestSubtract:
    def test_basic(self):
        assert subtract(10, 4) == 6

    def test_negative_result(self):
        assert subtract(3, 5) == -2


class TestMultiply:
    def test_basic(self):
        assert multiply(3, 4) == 12

    def test_by_zero(self):
        assert multiply(99, 0) == 0

    def test_negative(self):
        assert multiply(-2, 5) == -10


class TestDivide:
    def test_basic(self):
        assert divide(10, 2) == 5.0

    def test_float_result(self):
        assert divide(7, 2) == 3.5

    # NOTE: zero-division branch intentionally NOT tested — coverage gap


class TestPower:
    def test_square(self):
        assert power(3, 2) == 9

    def test_zero_exponent(self):
        assert power(5, 0) == 1


class TestAbsolute:
    def test_positive(self):
        assert absolute(5) == 5

    def test_negative(self):
        assert absolute(-3) == 3


class TestCalculator:
    def test_add(self):
        calc = Calculator()
        assert calc.add(2, 3) == 5.0
        assert calc.last_result == 5.0

    def test_subtract(self):
        calc = Calculator()
        assert calc.subtract(10, 3) == 7.0

    def test_multiply(self):
        calc = Calculator()
        assert calc.multiply(4, 5) == 20.0

    def test_history(self):
        calc = Calculator()
        calc.add(1, 2)
        calc.subtract(5, 1)
        assert calc.history() == [3.0, 4.0]

    def test_clear(self):
        calc = Calculator()
        calc.add(1, 1)
        calc.clear()
        assert calc.last_result == 0.0
        assert calc.history() == []
