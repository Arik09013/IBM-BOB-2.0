from __future__ import annotations

from buggy_pkg.validator import is_positive


def test_is_positive():
    assert is_positive(5) is True
    assert is_positive(-2) is False
