"""
converter.py — Unit conversion utilities.

Part of the TestPilot AI python_simple benchmark.

Coverage note:
  This ENTIRE MODULE is intentionally uncovered.
  No test file exists for converter.py.
  The TestPilot analyzer should detect this as a coverage gap.
"""

from __future__ import annotations


# Temperature conversions

def celsius_to_fahrenheit(c: float) -> float:
    """Convert Celsius to Fahrenheit."""
    return (c * 9 / 5) + 32


def fahrenheit_to_celsius(f: float) -> float:
    """Convert Fahrenheit to Celsius."""
    return (f - 32) * 5 / 9


def celsius_to_kelvin(c: float) -> float:
    """Convert Celsius to Kelvin."""
    return c + 273.15


# Distance conversions

def km_to_miles(km: float) -> float:
    """Convert kilometres to miles."""
    return km * 0.621371


def miles_to_km(miles: float) -> float:
    """Convert miles to kilometres."""
    return miles / 0.621371


# Weight conversions

def kg_to_pounds(kg: float) -> float:
    """Convert kilograms to pounds."""
    return kg * 2.20462


def pounds_to_kg(pounds: float) -> float:
    """Convert pounds to kilograms."""
    return pounds / 2.20462
