"""
Tests for statistics.py.

Coverage note:
  - mean() and median() are tested.
  - mode() and std_dev() are INTENTIONALLY NOT TESTED — coverage gaps.
"""

import pytest

from calculator.statistics import mean, median


class TestMean:
    def test_basic(self):
        assert mean([1, 2, 3, 4, 5]) == 3.0

    def test_single_element(self):
        assert mean([42.0]) == 42.0

    def test_floats(self):
        assert mean([1.5, 2.5]) == 2.0

    def test_negative_values(self):
        assert mean([-2, -4]) == -3.0

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            mean([])


class TestMedian:
    def test_odd_count(self):
        assert median([3, 1, 4, 1, 5]) == 3

    def test_even_count(self):
        assert median([1, 2, 3, 4]) == 2.5

    def test_single(self):
        assert median([7]) == 7

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            median([])

    # NOTE: mode() and std_dev() intentionally NOT tested
