"""Regression tests for dbushelper.get_bus() cache behaviour.

Issue #410: multiple ``VeDbusService`` instances on the *same* ``BusConnection`` collide
when registering object path ``/``. The fix is to cache one connection per distinct bus
name (battery service name vs shared settings name). Full reproduction needs a live
session/system bus and real ``VeDbusService``; these tests assert the caching contract
that prevents regressing back to a single global connection for every name.

PR #402: unbounded ``BusConnection`` creation (e.g. one per ``get_bus()`` call) leaks
until the D-Bus daemon hits per-user limits. Tests that count ``SystemBus`` construction
guard against regressions to a non-caching pattern for a given key.
"""

from unittest.mock import MagicMock, patch

import pytest

import dbushelper


@pytest.fixture(autouse=True)
def get_bus_test_isolation(monkeypatch):
    """Use system-bus code path and clear the module cache between tests."""
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    dbushelper._bus_instances.clear()
    yield
    dbushelper._bus_instances.clear()


def _mock_bus():
    m = MagicMock()
    m.get_is_connected.return_value = True
    return m


class TestGetBusCache:
    def test_same_name_returns_same_connection(self):
        """Repeated get_bus(name) must reuse one BusConnection (leak fix, #402)."""
        a = dbushelper.get_bus("com.victronenergy.battery.ttyUSB0__0x01")
        b = dbushelper.get_bus("com.victronenergy.battery.ttyUSB0__0x01")
        assert a is b

    def test_distinct_battery_names_get_distinct_connections(self):
        """Each battery service name must have its own connection (#410)."""
        first = dbushelper.get_bus("com.victronenergy.battery.ttyUSB0__0x01")
        second = dbushelper.get_bus("com.victronenergy.battery.ttyUSB0__0x02")
        assert first is not second

    def test_settings_constant_matches_literal_for_cache(self):
        """Settings I/O must share one cached connection under VICTRON_SETTINGS_DBUS_NAME."""
        from dbushelper import VICTRON_SETTINGS_DBUS_NAME

        assert VICTRON_SETTINGS_DBUS_NAME == "com.victronenergy.settings"
        via_const = dbushelper.get_bus(VICTRON_SETTINGS_DBUS_NAME)
        via_literal = dbushelper.get_bus("com.victronenergy.settings")
        assert via_const is via_literal

    def test_battery_connection_not_settings_connection(self):
        """A battery export must not share the settings cache entry."""
        from dbushelper import VICTRON_SETTINGS_DBUS_NAME

        batt = dbushelper.get_bus("com.victronenergy.battery.can0__0x01")
        settings = dbushelper.get_bus(VICTRON_SETTINGS_DBUS_NAME)
        assert batt is not settings


class TestGetBusConnectionLeak:
    """Count real BusConnection constructors: must stay bounded per cache key (#402)."""

    def test_many_get_bus_calls_one_system_bus_per_key(self):
        """Same key many times → SystemBus() once (not once per call)."""
        with patch.object(dbushelper, "SystemBus", side_effect=_mock_bus) as mock_sys:
            for _ in range(100):
                dbushelper.get_bus("com.victronenergy.settings")
            assert mock_sys.call_count == 1

    def test_distinct_keys_construct_distinct_buses(self):
        """N keys touched once each → N SystemBus() calls, then cache hits only."""
        names = [
            "com.victronenergy.battery.ttyUSB0__0x01",
            "com.victronenergy.battery.ttyUSB0__0x02",
            "com.victronenergy.settings",
        ]
        with patch.object(dbushelper, "SystemBus", side_effect=_mock_bus) as mock_sys:
            for n in names:
                dbushelper.get_bus(n)
            for _ in range(20):
                dbushelper.get_bus(names[1])
            assert mock_sys.call_count == len(names)

    def test_disconnected_bus_is_replaced_once(self):
        """If get_is_connected is false, get_bus allocates a fresh connection for that key."""
        with patch.object(dbushelper, "SystemBus") as mock_sys_cls:
            dead = MagicMock()
            dead.get_is_connected.return_value = False
            live = MagicMock()
            live.get_is_connected.return_value = True
            mock_sys_cls.side_effect = [dead, live]

            first = dbushelper.get_bus("com.victronenergy.settings")
            second = dbushelper.get_bus("com.victronenergy.settings")

            assert first is dead
            assert second is live
            assert mock_sys_cls.call_count == 2

    def test_many_calls_one_session_bus_per_key_when_session_env_set(self, monkeypatch):
        """Same as system-bus case when DBUS_SESSION_BUS_ADDRESS selects SessionBus."""
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/tmp/dbus-session-stub")
        dbushelper._bus_instances.clear()
        with patch.object(dbushelper, "SessionBus", side_effect=_mock_bus) as mock_sess:
            for _ in range(80):
                dbushelper.get_bus("com.victronenergy.settings")
            assert mock_sess.call_count == 1
