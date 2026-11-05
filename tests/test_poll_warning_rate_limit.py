# -*- coding: utf-8 -*-
"""Tests for the rate limiting of the slow poll warning.

A stalled battery connection makes every poll a slow poll, so the warning fired
once per cycle for as long as the outage lasted, alongside the dbushelper's own
report of the same outage.
"""

import importlib.util
import os
import sys
import types

DRIVER_DIR = os.path.join(os.path.dirname(__file__), "..", "dbus-serialbattery")
sys.path.insert(0, DRIVER_DIR)
sys.path.insert(0, os.path.join(DRIVER_DIR, "ext", "velib_python"))

import pytest  # noqa: E402

# conftest registers bare stubs for the Linux-only D-Bus modules. Complete the attributes
# this module imports, instead of registering a stub that setdefault() would discard.
_glib_mainloop = sys.modules.setdefault("dbus.mainloop.glib", types.ModuleType("dbus.mainloop.glib"))

if not hasattr(_glib_mainloop, "DBusGMainLoop"):
    _glib_mainloop.DBusGMainLoop = lambda **kwargs: None


def _load_driver_module():
    """Import dbus-serialbattery.py, whose file name is not a valid module name."""
    path = os.path.join(DRIVER_DIR, "dbus-serialbattery.py")
    spec = importlib.util.spec_from_file_location("dbus_serialbattery_main", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


driver = _load_driver_module()


def _battery(online):
    return types.SimpleNamespace(online=online)


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """The timestamp is module state, so each test has to start from a known point."""
    driver.poll_warning_last_time = 0
    yield
    driver.poll_warning_last_time = 0


def test_first_slow_poll_is_reported():
    assert driver.should_log_poll_warning([_battery(True)], 1000) is True


def test_second_slow_poll_within_the_interval_is_suppressed():
    """The regression: one warning per cycle for the whole outage."""
    assert driver.should_log_poll_warning([_battery(True)], 1000) is True

    for offset in range(1, driver.poll_warning_interval):
        assert driver.should_log_poll_warning([_battery(True)], 1000 + offset) is False


def test_warning_returns_after_the_interval():
    """Rate limited, not silenced: a persisting problem is still reported."""
    assert driver.should_log_poll_warning([_battery(True)], 1000) is True

    assert driver.should_log_poll_warning([_battery(True)], 1000 + driver.poll_warning_interval) is True


def test_offline_battery_suppresses_the_warning():
    """The dbushelper already reports the outage; the slow poll is that outage."""
    assert driver.should_log_poll_warning([_battery(False)], 1000) is False


def test_one_offline_battery_suppresses_it_for_the_process():
    """The poll is a single loop over all batteries, so one dead link delays all of them."""
    assert driver.should_log_poll_warning([_battery(True), _battery(False)], 1000) is False


def test_battery_that_has_never_polled_does_not_suppress_it():
    """online is None before the first successful poll, and a slow start is worth reporting."""
    assert driver.should_log_poll_warning([_battery(None)], 1000) is True


def test_suppressed_warning_does_not_start_the_interval():
    """An outage must not delay the first warning after recovery."""
    assert driver.should_log_poll_warning([_battery(False)], 1000) is False

    assert driver.should_log_poll_warning([_battery(True)], 1001) is True
