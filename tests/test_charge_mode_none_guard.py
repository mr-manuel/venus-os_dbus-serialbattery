# -*- coding: utf-8 -*-
"""Tests that manage_charge_voltage_limit() survives charge_mode being None.

battery.py declares ``self.charge_mode: str = None``, so None is a value the
attribute really takes. The float branch has two arms testing it: the first is
guarded, which means a None fails that test and is delivered straight to the
second one. The exception handler around the whole method catches TypeError
only, so an AttributeError raised there leaves the method entirely.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dbus-serialbattery"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dbus-serialbattery", "ext", "velib_python"))

import pytest  # noqa: E402
import utils  # noqa: E402
from battery import Battery  # noqa: E402


class StubBattery(Battery):
    """Concrete Battery, so it can be instantiated. No BMS communication."""

    def test_connection(self) -> bool:
        return True

    def get_settings(self) -> bool:
        return True

    def refresh_data(self) -> bool:
        return True


def _battery_in_float_mode(charge_mode):
    """A battery on the float branch, with charge_mode set by the caller.

    allow_max_voltage False selects the float branch, and control_voltage being
    set opens the gate in front of the two arms that read charge_mode.
    """
    battery = StubBattery("/dev/null", 9600, None)

    battery.cell_count = 16
    battery.max_battery_voltage = 56.8
    battery.control_voltage = 55.2
    battery.charge_mode = charge_mode

    # take the float branch and stay on it
    battery.allow_max_voltage = False
    battery.max_voltage_start_time = None
    battery.soc_calc = 100
    battery.soc_reset_requested = False
    battery.soc_reset_last_reached = 0

    # balanced cells, below max voltage: no switch back to bulk
    battery.get_cell_voltage_sum = lambda: 53.0
    battery.get_max_cell_voltage = lambda: 3.35
    battery.get_min_cell_voltage = lambda: 3.33

    return battery


@pytest.fixture(autouse=True)
def _deterministic_config(monkeypatch):
    """Pin the settings that steer the branch, so config.ini cannot change the test."""
    monkeypatch.setattr(utils, "SWITCH_TO_BULK_SOC_THRESHOLD", 0)
    monkeypatch.setattr(utils, "SWITCH_TO_BULK_CELL_VOLTAGE_DIFF", 10)
    monkeypatch.setattr(utils, "SWITCH_TO_FLOAT_CELL_VOLTAGE_DIFF", 10)
    monkeypatch.setattr(utils, "FLOAT_CELL_VOLTAGE", 3.375)
    monkeypatch.setattr(utils, "SOC_CALCULATION", False)


def test_none_charge_mode_does_not_raise():
    """The regression: None reaches the second arm and must not be dereferenced."""
    battery = _battery_in_float_mode(None)

    battery.manage_charge_voltage_limit()

    # completing the branch proves it ran past the arms rather than escaping
    assert battery.charge_mode.startswith("Float")


def test_none_charge_mode_error_is_not_caught_by_the_handler():
    """The method only catches TypeError, so an AttributeError here would escape.

    Guards the reason this matters: without the fix the failure is not the
    "Non blocking exception" the handler reports, it leaves the method.
    """
    battery = _battery_in_float_mode(None)

    battery.manage_charge_voltage_limit()

    # the handler sets this string when it swallows a TypeError; reaching a real
    # Float mode instead shows nothing was raised and swallowed on the way
    assert battery.charge_mode != "Error, please check the logs!"
    assert battery.charge_mode.startswith("Float")


def test_float_transition_arm_still_runs():
    """The guard must not disable the arm it protects."""
    battery = _battery_in_float_mode("Float Transition")
    battery.transition_start_time = 0
    battery.initial_control_voltage = 55.2

    battery.manage_charge_voltage_limit()

    assert battery.charge_mode.startswith("Float")


def test_bulk_charge_mode_takes_the_first_arm():
    """A non-None charge_mode not starting with Float still enters the transition."""
    battery = _battery_in_float_mode("Bulk")

    battery.manage_charge_voltage_limit()

    assert battery.charge_mode.startswith("Float Transition")
