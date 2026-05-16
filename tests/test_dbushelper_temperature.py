"""Regression tests for D-Bus temperature adjustment helpers."""

import pytest

from dbushelper import _adjust_temperature


def test_adjust_temperature_preserves_missing_sensor_value():
    assert _adjust_temperature(None, [0.0, 1.0]) is None


@pytest.mark.parametrize(
    "value,adjustment,expected",
    [
        (25.0, [0.0, 1.0], 25.0),
        (25.0, [1.5, 1.0], 26.5),
        (25.0, [0.0, 1.1], 27.5),
        (-5.0, [-1.0, 0.5], -3.5),
    ],
)
def test_adjust_temperature_applies_offset_and_multiplier(value, adjustment, expected):
    assert _adjust_temperature(value, adjustment) == pytest.approx(expected)
