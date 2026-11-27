"""Tests for publishing /History/TimeSinceLastFullCharge in DbusHelper.publish_dbus.

The value grows by one every second, so the write cache in _CachedDbusProxy
never suppresses it. publish_dbus therefore publishes it at most every 60
seconds, and at once when history.timestamp_last_full_charge changes.

Platform-specific modules (dbus, velib_python) are stubbed via conftest.py
so these tests run on macOS, CI, and Linux alike.
"""

import pytest
from unittest.mock import MagicMock

import dbushelper
from dbushelper import DbusHelper, _CachedDbusProxy

PATH = "/History/TimeSinceLastFullCharge"
T0 = 1_750_000_000
"""Driver start time (seconds since epoch) used by the fake clock."""
LAST_FULL_CHARGE = T0 - 3600


class FakeClock:
    """Replaces dbushelper.time() so the test controls the current time."""

    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock(T0)
    monkeypatch.setattr(dbushelper, "time", fake)
    return fake


@pytest.fixture
def battery():
    """A mock battery with just enough real values for publish_dbus to run."""
    bat = MagicMock()
    bat.port = "/dev/ttyUSB0"
    bat.unique_identifier.return_value = "TEST"
    bat.get_midvoltage.return_value = (None, None)
    bat.soc_reset_requested = False
    bat.soc_reset_last_reached = 0
    bat.current_calc = None
    bat.capacity = None
    bat.history.timestamp_last_full_charge = LAST_FULL_CHARGE
    return bat


@pytest.fixture
def published():
    """List of (time, value) for every write of PATH that reaches the D-Bus service."""
    return []


@pytest.fixture
def helper(battery, clock, published):
    """A DbusHelper whose D-Bus service is a mock behind the real write cache."""
    svc = MagicMock()

    def setitem(path, value):
        if path == PATH:
            published.append((clock.now, value))

    svc.__setitem__ = MagicMock(side_effect=setitem)
    # The service is its own context, so a write made inside a ``with`` block is counted too
    svc.__enter__ = MagicMock(return_value=svc)

    dbus_helper = DbusHelper(battery)
    dbus_helper._dbusservice = _CachedDbusProxy(svc)
    dbus_helper.save_current_battery_state = MagicMock()
    dbus_helper.set_settings = MagicMock()
    return dbus_helper


def poll(helper, clock, start, stop, interval, before_poll=None):
    """Call publish_dbus every `interval` seconds from T0+start to T0+stop inclusive."""
    for offset in range(start, stop + 1, interval):
        clock.now = T0 + offset
        if before_poll is not None:
            before_poll(offset)
        helper.publish_dbus()


def offsets(published):
    return [t - T0 for t, _ in published]


class TestThrottle:
    """At most one publish per 60 seconds while the timestamp is unchanged."""

    def test_one_second_polls_publish_once_per_minute(self, helper, clock, published):
        poll(helper, clock, 0, 120, 1)
        assert offsets(published) == [0, 60, 120]

    def test_first_poll_publishes(self, helper, clock, published):
        poll(helper, clock, 0, 0, 1)
        assert len(published) == 1

    def test_first_poll_publishes_even_if_clock_is_below_60(self, helper, clock, published):
        """The first publish does not depend on the clock value."""
        helper.battery.history.timestamp_last_full_charge = None
        clock.now = 10
        helper.publish_dbus()
        assert published == [(10, None)]

    @pytest.mark.parametrize("interval", [60, 61, 600])
    def test_poll_interval_of_60_seconds_or_more_publishes_every_poll(self, helper, clock, published, interval):
        poll(helper, clock, 0, interval * 4, interval)
        assert offsets(published) == [interval * n for n in range(5)]

    def test_published_value_is_computed_at_publish_time(self, helper, clock, published):
        poll(helper, clock, 0, 120, 1)
        assert published == [(T0 + n, T0 + n - LAST_FULL_CHARGE) for n in (0, 60, 120)]


class TestTimestampChange:
    """A changed timestamp_last_full_charge publishes at once, inside the window."""

    def test_new_full_charge_publishes_at_once(self, helper, clock, published):
        def before_poll(offset):
            if offset == 10:
                helper.battery.history.timestamp_last_full_charge = T0 + 10

        poll(helper, clock, 0, 80, 1, before_poll)
        assert published == [
            (T0, T0 - LAST_FULL_CHARGE),
            (T0 + 10, 0),
            # the 60 second window restarts at the publish caused by the change
            (T0 + 70, 60),
        ]

    def test_none_to_value_publishes_at_once(self, helper, clock, published):
        helper.battery.history.timestamp_last_full_charge = None

        def before_poll(offset):
            if offset == 5:
                helper.battery.history.timestamp_last_full_charge = LAST_FULL_CHARGE

        poll(helper, clock, 0, 30, 1, before_poll)
        assert published == [(T0, None), (T0 + 5, T0 + 5 - LAST_FULL_CHARGE)]

    def test_value_to_none_publishes_at_once(self, helper, clock, published):
        def before_poll(offset):
            if offset == 5:
                helper.battery.history.timestamp_last_full_charge = None

        poll(helper, clock, 0, 30, 1, before_poll)
        assert published == [(T0, T0 - LAST_FULL_CHARGE), (T0 + 5, None)]

    def test_none_stays_none(self, helper, clock, published):
        """An unchanged None is published once; the write cache drops the repeats."""
        helper.battery.history.timestamp_last_full_charge = None
        poll(helper, clock, 0, 120, 1)
        assert published == [(T0, None)]
