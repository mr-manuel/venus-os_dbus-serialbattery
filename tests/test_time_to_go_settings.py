"""TimeToGo reads current ESS settings without walking unrelated schedules."""

from unittest.mock import Mock, call

import pytest

from battery import Battery
import dbushelper
from dbushelper import DbusHelper, VICTRON_SETTINGS_DBUS_NAME


PATHS = (
    "/Settings/CGwacs/BatteryLife/State",
    "/Settings/CGwacs/BatteryLife/MinimumSocLimit",
    "/Settings/CGwacs/BatteryLife/SocLimit",
    "/Settings/CGwacs/Hub4Mode",
)


class FakeDictionary(dict):
    pass


class FakeBattery(Battery):
    def test_connection(self):
        return True

    def get_settings(self):
        return True

    def refresh_data(self):
        return True


@pytest.fixture
def settings(monkeypatch):
    values = dict(zip(PATHS, (10, 15.0, 25.0, 1)))
    bus = Mock()

    def get_object(service, path, introspect=False):
        obj = Mock()
        obj.GetValue.side_effect = lambda **kwargs: values[path]
        return obj

    bus.get_object.side_effect = get_object
    monkeypatch.setattr(dbushelper, "get_bus", Mock(return_value=bus))
    monkeypatch.setattr(dbushelper.dbus, "Dictionary", FakeDictionary, raising=False)
    return values, bus


@pytest.fixture
def helper(monkeypatch):
    battery = FakeBattery("/no-device", 9600, None)
    battery.cell_count = 0
    battery.soc = battery.soc_calc = 50
    battery.current_calc = -5
    battery.capacity = 280
    battery.online = True
    battery.get_allow_to_charge = Mock(return_value=True)
    battery.get_allow_to_discharge = Mock(return_value=True)
    battery.get_time_to_soc = Mock(return_value=3600)
    battery.manage_error_code = Mock()
    battery.log_cell_data = Mock()
    obj = DbusHelper.__new__(DbusHelper)
    obj.battery = battery
    obj._dbusservice = {"/Mode": 3, "/TimeToGo": "previous"}
    obj.bms_cable_alarm = 0
    obj.history_calculated_last_time = 1000
    obj.settings_saved_last_time = 1000
    obj.last_seen_saved_last_time = 1000
    obj.get_settings_with_values = Mock(side_effect=AssertionError("recursive settings traversal"))
    monkeypatch.setattr(dbushelper, "time", lambda: 1000)
    for name, value in {
        "TIME_TO_GO_ENABLE": True,
        "TIME_TO_SOC_POINTS": [],
        "TIME_TO_SOC_RECALCULATE_EVERY": 60,
        "SOC_LOW_WARNING": 20,
        "BATTERY_CELL_DATA_FORMAT": 0,
        "PUBLISH_BATTERY_DATA_AS_JSON": False,
        "HISTORY_ENABLE": False,
    }.items():
        monkeypatch.setattr(dbushelper.utils, name, value)
    return obj


def test_reads_only_four_current_settings_with_bounded_calls(settings):
    values, bus = settings
    objects = {path: Mock() for path in PATHS}
    for path, obj in objects.items():
        obj.GetValue.return_value = values[path]
    bus.get_object.side_effect = lambda service, path, introspect=False: objects[path]
    helper = DbusHelper.__new__(DbusHelper)

    life, mode = helper.get_time_to_go_settings()

    assert life["Settings"]["CGwacs"]["BatteryLife"] == {"State": "10", "MinimumSocLimit": "15.0", "SocLimit": "25.0"}
    assert mode["Settings"]["CGwacs"]["Hub4Mode"] == "1"
    dbushelper.get_bus.assert_called_once_with(VICTRON_SETTINGS_DBUS_NAME)
    assert bus.get_object.call_args_list == [call(VICTRON_SETTINGS_DBUS_NAME, path, introspect=False) for path in PATHS]
    for obj in objects.values():
        obj.GetValue.assert_called_once_with(dbus_interface="com.victronenergy.BusItem", timeout=1)


@pytest.mark.parametrize("mode", [0, 1, 2, 3])
@pytest.mark.parametrize("state", [0, 9, 10, 11, 12, 13])
@pytest.mark.parametrize("current", [-5, 0, 5])
def test_publisher_preserves_target_selection(helper, settings, mode, state, current):
    values, _ = settings
    values[PATHS[0]], values[PATHS[3]] = state, mode
    helper.battery.current_calc = current

    helper.publish_dbus()

    target = 15 if mode == 1 and state in (10, 11, 12) else 25 if mode == 1 and state != 9 else 20
    expected = target if current < 0 else 100
    helper.battery.get_time_to_soc.assert_called_once()
    assert helper.battery.get_time_to_soc.call_args.args[0] == expected
    assert helper._dbusservice["/TimeToGo"] == (3600 if current else None)
    helper.battery.manage_error_code.assert_not_called()
    helper.get_settings_with_values.assert_not_called()


def test_setting_changes_are_read_on_the_next_calculation(helper, settings, monkeypatch):
    values, _ = settings
    helper.publish_dbus()
    values[PATHS[1]] = 30.0
    monkeypatch.setattr(dbushelper, "time", lambda: 1060)
    helper.settings_saved_last_time = helper.last_seen_saved_last_time = 1060
    helper.publish_dbus()
    assert [c.args[0] for c in helper.battery.get_time_to_soc.call_args_list] == [15, 30]
    helper.battery.manage_error_code.assert_not_called()


@pytest.mark.parametrize("value", ["invalid", "", None])
def test_invalid_soc_limit_keeps_previous_display_and_reports_error(helper, settings, value):
    values, _ = settings
    values[PATHS[1]] = value
    helper.publish_dbus()
    helper.battery.manage_error_code.assert_called_once_with(8)
    helper.battery.get_time_to_soc.assert_not_called()
    assert helper._dbusservice["/TimeToGo"] == "previous"


@pytest.mark.parametrize("path", [PATHS[1], PATHS[2], PATHS[3]])
def test_dictionary_values_are_omitted_as_in_recursive_reader(helper, settings, path):
    values, _ = settings
    values[path] = FakeDictionary()
    helper.publish_dbus()
    assert helper.battery.get_time_to_soc.call_args.args[0] == 20
    helper.battery.manage_error_code.assert_not_called()


@pytest.mark.parametrize("path", PATHS)
def test_read_failure_reaches_existing_publisher_error_handler(helper, settings, path):
    _, bus = settings
    original = bus.get_object.side_effect

    def fail(service, requested, introspect=False):
        obj = original(service, requested, introspect=introspect)
        if requested == path:
            obj.GetValue.side_effect = RuntimeError("read failed")
        return obj

    bus.get_object.side_effect = fail
    helper.publish_dbus()
    helper.battery.manage_error_code.assert_called_once_with(8)
    helper.battery.get_time_to_soc.assert_not_called()
    assert helper._dbusservice["/TimeToGo"] == "previous"


@pytest.mark.parametrize("setting", ["TIME_TO_GO_ENABLE", "not_due"])
def test_disabled_or_not_due_does_not_read_settings(helper, settings, monkeypatch, setting):
    _, bus = settings
    if setting == "not_due":
        helper.battery.time_to_soc_update = 999
    else:
        monkeypatch.setattr(dbushelper.utils, setting, False)
    helper.publish_dbus()
    bus.get_object.assert_not_called()
    helper.battery.get_time_to_soc.assert_not_called()
