"""Regression tests for dbushelper.get_bus() cache behaviour.

Issue #410: multiple ``VeDbusService`` instances on the *same* ``BusConnection`` collide
when registering object path ``/``. The fix is to cache one connection per distinct bus
name (battery service name vs shared settings name). Full reproduction needs a live
session/system bus and real ``VeDbusService``; these tests assert the caching contract
that prevents regressing back to a single global connection for every name.
"""

import pytest

import dbushelper


@pytest.fixture(autouse=True)
def clear_bus_cache():
    """Isolate tests from each other and from any prior imports."""
    dbushelper._bus_instances.clear()
    yield
    dbushelper._bus_instances.clear()


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
