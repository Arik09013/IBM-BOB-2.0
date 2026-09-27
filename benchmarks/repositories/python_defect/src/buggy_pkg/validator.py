"""
validator.py — Simple input validation utilities with an intentional bug.

Part of TestPilot AI synthetic benchmark suite for Phase 5.
"""

from __future__ import annotations


def is_positive(n: int) -> bool:
    """Return True if n is strictly positive (> 0)."""
    return n > 0


def is_even(n: int) -> bool:
    """
    Return True if n is an even integer.

    INTENTIONAL SOURCE CODE DEFECT:
    Returns n % 2 == 1, which evaluates to True for odd numbers instead of even numbers!
    The FailureAnalysisAgent should classify test failures against this function as
    source_code_defect, triggering the Phase 4 safety gate.
    """
    return n % 2 == 1
