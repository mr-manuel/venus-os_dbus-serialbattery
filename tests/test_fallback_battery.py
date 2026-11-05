# -*- coding: utf-8 -*-
"""Tests for the fallback sensor feature (FALLBACK_SENSOR_DBUS_*), which lives
entirely in FallbackBattery — a wrapper around any configured Battery."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dbus-serialbattery"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dbus-serialbattery", "ext", "velib_python"))

import utils  # noqa: E402
from battery import Battery, Cell  # noqa: E402
from fallback_battery import FallbackBattery  # noqa: E402


class _FakeDbusItem:
    def __init__(self, value=None):
        self.value = value

    def get_value(self):
        return self.value


class _FakeBleHandle:
    def __init__(self, connected=True, rebuildable=True):
        self.connected = connected
        self.rebuilds = 0
        if not rebuildable:
            del self.rebuild_ble_thread

    def rebuild_ble_thread(self):
        self.rebuilds += 1
        return True


class _NoRebuildBleHandle:
    def __init__(self, connected=True):
        self.connected = connected


# concrete subclass so the abstract Battery can be instantiated without a BMS
_ConcreteBattery = type("_ConcreteBattery", (Battery,), {name: lambda self, *a, **kw: None for name in Battery.__abstractmethods__})


class _FakeBattery(_ConcreteBattery):
    """A driver that reports honestly and can be told what to report."""

    def __init__(self, port="ble_test", address="AA:BB"):
        super().__init__(port, 9600, address)
        self.type = "Fake"
        self.refresh_result = True
        self.refresh_calls = 0
        self.voltage = 26.0
        self.current = -10.0
        self.soc = 55.0
        self.capacity = 280.0
        self.cell_count = 8
        self.cells = [Cell(False) for _ in range(8)]
        for cell in self.cells:
            cell.voltage = 3.25
        self.temperature_1 = 20.0
        self.temperature_2 = 21.0
        self.online = True

    def test_connection(self):
        return self.refresh_result

    def refresh_data(self):
        self.refresh_calls += 1
        return self.refresh_result

    def connection_name(self):
        return "BLE AA:BB"


def _make_wrapper(monkeypatch, tmp_path=None, shunt=None, connected=True, rebuildable=True, battery=None):
    """Build a wrapper with no configured device (so the dbus watcher stays
    inert) and inject resolved fallback proxies directly."""
    monkeypatch.setattr(utils, "FALLBACK_SENSOR_DBUS_DEVICE", None)
    if tmp_path is not None:
        monkeypatch.setattr(FallbackBattery, "STASH_DIRECTORY", str(tmp_path))
    battery = battery if battery is not None else _FakeBattery()
    if connected is not None:
        battery.ble_handle = _FakeBleHandle(connected=connected) if rebuildable else _NoRebuildBleHandle(connected=connected)
    wrapper = FallbackBattery(battery)
    if shunt is not None:
        wrapper.dbus_fallback_objects = {key: _FakeDbusItem(value) for key, value in shunt.items()}
    return wrapper


_LIVE_SHUNT = {"Voltage": 25.5, "Current": -12.0, "Temperature": 21.0, "Soc": 61.0}


def _serve(wrapper, stale_by=100.0):
    """Force the wrapper into the serving state by ageing the freshness clock."""
    wrapper._last_fresh_time = _now() - stale_by
    return wrapper.refresh_data()


def _now():
    from time import time

    return time()


# ── configuration ────────────────────────────────────────────────────────


class TestResolveDevice:
    def _resolve(self, monkeypatch, config_value, port="/ble_5320b7d7f9e7"):
        monkeypatch.setattr(utils, "FALLBACK_SENSOR_DBUS_DEVICE", config_value)
        battery = _FakeBattery(port=port)
        return FallbackBattery.resolve_device(battery)

    def test_not_configured_returns_none(self, monkeypatch):
        assert self._resolve(monkeypatch, None) is None

    def test_single_service_applies_to_any_battery(self, monkeypatch):
        assert self._resolve(monkeypatch, "com.victronenergy.battery.ttyS2") == "com.victronenergy.battery.ttyS2"

    def test_mapping_resolves_matching_battery(self, monkeypatch):
        mapping = "ble_5320b7d7f9e7:com.victronenergy.battery.ttyS5, ble_ab807254e0b4:com.victronenergy.battery.ttyS6"
        assert self._resolve(monkeypatch, mapping, port="/ble_5320b7d7f9e7") == "com.victronenergy.battery.ttyS5"
        assert self._resolve(monkeypatch, mapping, port="/ble_ab807254e0b4") == "com.victronenergy.battery.ttyS6"

    def test_mapping_without_match_returns_none(self, monkeypatch):
        assert self._resolve(monkeypatch, "ble_5320b7d7f9e7:com.victronenergy.battery.ttyS5", port="/ble_ab807254e0b4") is None

    def test_configured_for_requires_device_and_a_path(self, monkeypatch):
        battery = _FakeBattery(port="ble_test")
        monkeypatch.setattr(utils, "FALLBACK_SENSOR_DBUS_PATH_VOLTAGE", "/Dc/0/Voltage")
        monkeypatch.setattr(utils, "FALLBACK_SENSOR_DBUS_DEVICE", None)
        assert FallbackBattery.configured_for(battery) is False
        monkeypatch.setattr(utils, "FALLBACK_SENSOR_DBUS_DEVICE", "com.victronenergy.battery.ttyS2")
        assert FallbackBattery.configured_for(battery) is True

    def test_configured_for_device_without_paths_is_not_enough(self, monkeypatch):
        battery = _FakeBattery(port="ble_test")
        monkeypatch.setattr(utils, "FALLBACK_SENSOR_DBUS_DEVICE", "com.victronenergy.battery.ttyS2")
        for name in ("VOLTAGE", "CURRENT", "TEMPERATURE", "SOC"):
            monkeypatch.setattr(utils, f"FALLBACK_SENSOR_DBUS_PATH_{name}", None)
        assert FallbackBattery.configured_for(battery) is False


# ── measurement topology ─────────────────────────────────────────────────


class TestPairedSensorDevice:
    """The wrapper publishes the paired instrument, so consumers that need the
    measurement topology can learn that a second service measures this pack."""

    def test_paired_device_is_the_resolved_service(self, monkeypatch, tmp_path):
        monkeypatch.setattr(FallbackBattery, "STASH_DIRECTORY", str(tmp_path))
        monkeypatch.setattr(utils, "FALLBACK_SENSOR_DBUS_DEVICE", "ble_5320b7d7f9e7:com.victronenergy.battery.ttyS5")
        wrapper = FallbackBattery(_FakeBattery(port="/ble_5320b7d7f9e7"))
        assert wrapper.get_paired_sensor_device() == "com.victronenergy.battery.ttyS5"

    def test_no_configured_device_means_no_pairing(self, monkeypatch, tmp_path):
        wrapper = _make_wrapper(monkeypatch, tmp_path)
        assert wrapper.get_paired_sensor_device() is None

    def test_mapping_without_a_match_means_no_pairing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(FallbackBattery, "STASH_DIRECTORY", str(tmp_path))
        monkeypatch.setattr(utils, "FALLBACK_SENSOR_DBUS_DEVICE", "ble_5320b7d7f9e7:com.victronenergy.battery.ttyS5")
        wrapper = FallbackBattery(_FakeBattery(port="/ble_ab807254e0b4"))
        assert wrapper.get_paired_sensor_device() is None

    def test_the_pairing_is_stated_regardless_of_the_serving_state(self, monkeypatch, tmp_path):
        """The pairing is a physical fact, not a mode: it holds while the BMS
        is answering and while the shunt is being served."""
        monkeypatch.setattr(FallbackBattery, "STASH_DIRECTORY", str(tmp_path))
        monkeypatch.setattr(utils, "FALLBACK_SENSOR_DBUS_DEVICE", "com.victronenergy.battery.ttyS5")
        # there is no bus in the test process; the resolved proxies are injected
        monkeypatch.setattr(FallbackBattery, "_watch_fallback_sensor", lambda self: None)
        battery = _FakeBattery()
        battery.ble_handle = _FakeBleHandle(connected=True)
        wrapper = FallbackBattery(battery)
        wrapper.dbus_fallback_objects = {key: _FakeDbusItem(value) for key, value in _LIVE_SHUNT.items()}
        wrapper.refresh_data()
        assert wrapper._serving is False
        assert wrapper.get_paired_sensor_device() == "com.victronenergy.battery.ttyS5"
        battery.ble_handle.connected = False
        wrapper.refresh_data()
        assert wrapper._serving is True
        assert wrapper.get_paired_sensor_device() == "com.victronenergy.battery.ttyS5"

    def test_the_accessor_is_not_swallowed_by_the_forwarding_wrapper(self, monkeypatch, tmp_path):
        """The wrapped driver has no such method; the wrapper must answer it
        itself rather than forwarding the lookup and raising."""
        wrapper = _make_wrapper(monkeypatch, tmp_path)
        assert not hasattr(wrapper.battery, "get_paired_sensor_device")
        assert getattr(wrapper, "get_paired_sensor_device", lambda: "unreachable")() is None


# ── serving rule ─────────────────────────────────────────────────────────


class TestServingRule:
    """Serve BMS values only while connected AND the data is younger than 15 s."""

    def test_connected_and_fresh_serves_bms(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=True)
        assert wrapper.refresh_data() is True
        assert wrapper._serving is False
        assert wrapper.get_voltage() == 26.0

    def test_connected_but_stale_serves_shunt(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=True)
        wrapper.battery.refresh_result = False
        assert _serve(wrapper) is True
        assert wrapper._serving is True
        assert wrapper.get_voltage() == 25.5

    def test_disconnected_flips_instantly_even_with_fresh_data(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=True)
        wrapper.refresh_data()
        assert wrapper._serving is False
        # the data is one cycle old — well inside the freshness window
        wrapper.battery.ble_handle.connected = False
        wrapper.refresh_data()
        assert wrapper._serving is True
        assert wrapper.get_voltage() == 25.5

    def test_disconnected_and_stale_serves_shunt(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        assert _serve(wrapper) is True
        assert wrapper._serving is True

    def test_refresh_data_is_skipped_while_disconnected(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        wrapper.refresh_data()
        wrapper.refresh_data()
        assert wrapper.battery.refresh_calls == 0

    def test_refresh_data_is_called_while_connected(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=True)
        wrapper.refresh_data()
        assert wrapper.battery.refresh_calls == 1

    def test_driver_without_connection_state_uses_freshness_only(self, monkeypatch):
        battery = _FakeBattery()
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=None, battery=battery)
        assert wrapper.refresh_data() is True
        assert wrapper._serving is False
        wrapper.battery.refresh_result = False
        _serve(wrapper)
        assert wrapper._serving is True


class TestObservationalStaleness:
    """The wrapper stamps its own clock; it never reads driver internals."""

    def test_successful_refresh_with_core_values_stamps(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT)
        wrapper._last_fresh_time = 0.0
        wrapper.refresh_data()
        assert wrapper._last_fresh_time > 0.0

    def test_no_stamp_when_core_values_are_none(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT)
        wrapper.battery.voltage = None
        wrapper._last_fresh_time = 0.0
        wrapper.refresh_data()
        assert wrapper._last_fresh_time == 0.0
        assert wrapper._serving is True

    def test_no_stamp_when_refresh_fails(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT)
        wrapper.battery.refresh_result = False
        wrapper._last_fresh_time = 0.0
        wrapper.refresh_data()
        assert wrapper._last_fresh_time == 0.0

    def test_fresh_process_serves_the_shunt_from_the_first_cycle(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        assert wrapper._last_fresh_time == 0.0
        wrapper.refresh_data()
        assert wrapper._serving is True


class TestAuditFixes:
    """Regression coverage for the accountability-audit findings."""

    def test_temperature_writes_are_frozen_while_serving(self, monkeypatch):
        # B5: DbusHelper re-applies TEMPERATURE_*_ADJUST to the stored value
        # each success cycle; during an outage that compounds without bound
        # unless the wrapper drops the writes.
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        wrapper.battery.temperature_1 = 20.0
        _serve(wrapper)
        assert wrapper._serving is True
        wrapper.temperature_1 = 21.5  # DbusHelper's adjusted write-back
        assert wrapper.battery.temperature_1 == 20.0
        wrapper.battery.ble_handle.connected = True
        wrapper.refresh_data()
        assert wrapper._serving is False
        wrapper.temperature_1 = 21.5
        assert wrapper.battery.temperature_1 == 21.5

    def test_projection_is_undone_when_leaving_fallback(self, monkeypatch):
        # B6: without the undo, a partial frame (core values but no cell
        # frame) lets the next engagement snapshot our own synthetic
        # voltages as if they were measurements.
        monkeypatch.setattr(utils, "FALLBACK_SAFE_CELL_VOLTAGE_MIN", 2.7)
        monkeypatch.setattr(utils, "FALLBACK_SAFE_CELL_VOLTAGE_MAX", 3.55)
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        measured = [cell.voltage for cell in wrapper.battery.cells]
        _serve(wrapper)
        assert wrapper._projection_valid is True
        assert [cell.voltage for cell in wrapper.battery.cells] != measured
        wrapper.battery.ble_handle.connected = True
        wrapper.refresh_data()
        assert wrapper._fallback_mode is False
        assert [cell.voltage for cell in wrapper.battery.cells] == measured

    def test_stash_write_is_atomic(self, monkeypatch, tmp_path):
        # B3: a truncated stash silently loses the boot-without-BMS
        # registration; the write must go through a temp file + rename.
        import json as json_module

        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT, connected=True)
        real_dump = json_module.dump
        observed = {}

        def dump_and_check(obj, fh, *args, **kwargs):
            observed["path"] = fh.name
            return real_dump(obj, fh, *args, **kwargs)

        monkeypatch.setattr("fallback_battery.json.dump", dump_and_check)
        wrapper.refresh_data()
        assert os.path.exists(wrapper._stash_path)
        assert observed["path"] != wrapper._stash_path
        with open(wrapper._stash_path) as stash_file:
            assert json_module.load(stash_file)["cell_count"] == 8

    def test_charge_mode_reverts_to_the_driver_when_not_serving(self, monkeypatch):
        # B7: in the both-dark state the stock disconnect ladder owns the
        # user-visible story; a lingering "Fallback" label contradicts it.
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        wrapper.battery.charge_mode = "Bulk"
        _serve(wrapper)
        assert "Fallback" in wrapper.charge_mode
        for item in wrapper.dbus_fallback_objects.values():
            item.value = None
        wrapper.battery.refresh_result = False
        _serve(wrapper)
        assert wrapper._serving is False
        assert wrapper._fallback_mode is True
        assert wrapper.charge_mode == "Bulk"


class TestTransparencyWhenShuntIsDark:
    """D2: no invented both-dark handling — the wrapper simply steps aside."""

    def test_no_proxies_means_transparent(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=None, connected=False)
        wrapper.battery.refresh_result = False
        assert _serve(wrapper) is False
        assert wrapper._serving is False
        assert wrapper.get_voltage() == 26.0

    def test_dead_proxies_mean_transparent(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt={"Voltage": None, "Current": None}, connected=False)
        wrapper.battery.refresh_result = False
        assert _serve(wrapper) is False
        assert wrapper._serving is False

    def test_online_is_delegated_when_not_serving(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=None, connected=False)
        wrapper.battery.refresh_result = False
        _serve(wrapper)
        wrapper.battery.online = True
        assert wrapper.online is True
        wrapper.battery.online = False
        assert wrapper.online is False

    def test_refresh_verdict_is_the_drivers_own_when_transparent(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=None, connected=True)
        wrapper.battery.refresh_result = True
        assert wrapper.refresh_data() is True
        wrapper.battery.refresh_result = False
        assert wrapper.refresh_data() is False

    def test_shunt_dying_mid_outage_keeps_fallback_mode(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        _serve(wrapper)
        assert wrapper._fallback_mode is True
        for item in wrapper.dbus_fallback_objects.values():
            item.value = None
        _serve(wrapper)
        assert wrapper._serving is False
        # the BMS is still away: the snapshot and the alarm state must survive
        assert wrapper._fallback_mode is True


# ── served values ────────────────────────────────────────────────────────


class TestServedValues:
    def test_voltage_current_soc_temperature_from_shunt(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        _serve(wrapper)
        assert wrapper.get_voltage() == 25.5
        assert wrapper.get_current() == -12.0
        # SoC is anchored on the BMS reading and moved by the shunt's travel,
        # so at engagement it equals the BMS value rather than the shunt's
        assert wrapper.get_soc() == 55.0
        assert wrapper.get_temperature() == 21.0

    def test_bms_values_while_fresh(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=True)
        wrapper.refresh_data()
        assert wrapper.get_voltage() == 26.0
        assert wrapper.get_current() == -10.0

    def test_missing_shunt_key_falls_back_to_the_bms_value(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt={"Voltage": 25.5}, connected=False)
        _serve(wrapper)
        assert wrapper.get_voltage() == 25.5
        assert wrapper.get_current() == -10.0

    def test_external_sensor_wins_over_the_shunt(self, monkeypatch):
        # the external sensor always overrides the BMS, and therefore the shunt
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        wrapper.battery.dbus_external_objects = {"Current": _FakeDbusItem(-7.0)}
        _serve(wrapper)
        assert wrapper.get_current() == -7.0

    def test_set_calculated_data_writes_through_to_the_battery(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        _serve(wrapper)
        wrapper.set_calculated_data()
        assert wrapper.get_voltage() == 25.5
        assert wrapper.battery.current_calc == -12.0
        assert wrapper.battery.soc_calc == 55.0
        assert wrapper.battery.power_calc == pytest.approx(25.5 * -12.0)

    def test_capacity_remain_derives_from_the_served_soc(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        wrapper.battery.capacity_remain = 111.0
        _serve(wrapper)
        wrapper.set_calculated_data()
        assert wrapper.get_capacity_remain() == pytest.approx(280.0 * 55.0 / 100)
        assert wrapper.get_capacity_consumed() == pytest.approx(-(280.0 - 280.0 * 55.0 / 100))

    def test_capacity_remain_uses_the_bms_value_while_fresh(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=True)
        wrapper.battery.capacity_remain = 111.0
        wrapper.refresh_data()
        assert wrapper.get_capacity_remain() == 111.0

    def test_fet_state_still_clamps_the_shunt_current(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        wrapper.battery.discharge_fet = False
        _serve(wrapper)
        assert wrapper.get_current() == 0.0


class TestUnreadFetStates:
    """A service registered from the stash has never read the FET states. The
    base class reads unset as not-allowed, which would have it publish full
    configured limits while telling DVCC the battery can do neither."""

    def test_unread_fets_do_not_assert_a_block_while_serving(self, monkeypatch):
        # a configured safe zone the projection sits inside, so governance is
        # not the thing blocking and the FET state is what is under test
        monkeypatch.setattr(utils, "FALLBACK_SAFE_CELL_VOLTAGE_MIN", 2.70)
        monkeypatch.setattr(utils, "FALLBACK_SAFE_CELL_VOLTAGE_MAX", 3.55)
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        wrapper.battery.charge_fet = None
        wrapper.battery.discharge_fet = None
        wrapper.battery.control_allow_charge = True
        wrapper.battery.control_allow_discharge = True
        _serve(wrapper)

        assert wrapper.get_allow_to_charge() is True
        assert wrapper.get_allow_to_discharge() is True

    def test_a_fet_the_bms_reported_open_is_still_honoured(self, monkeypatch):
        # unknown is not the same as known-open: a real report must win
        monkeypatch.setattr(utils, "FALLBACK_SAFE_CELL_VOLTAGE_MIN", 2.70)
        monkeypatch.setattr(utils, "FALLBACK_SAFE_CELL_VOLTAGE_MAX", 3.55)
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        wrapper.battery.charge_fet = False
        wrapper.battery.discharge_fet = False
        wrapper.battery.control_allow_charge = True
        wrapper.battery.control_allow_discharge = True
        _serve(wrapper)

        assert wrapper.get_allow_to_charge() is False
        assert wrapper.get_allow_to_discharge() is False

    def test_unread_fets_are_not_overridden_when_not_serving(self, monkeypatch):
        # with the BMS answering, an unread FET is the base class's business
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=True)
        wrapper.battery.charge_fet = None
        wrapper.battery.control_allow_charge = True
        wrapper.refresh_data()

        assert wrapper._serving is False
        assert wrapper.get_allow_to_charge() is False

    def test_the_drivers_own_control_decision_still_applies(self, monkeypatch):
        # only the FET term is substituted, not the limiter's decision
        monkeypatch.setattr(utils, "FALLBACK_SAFE_CELL_VOLTAGE_MIN", 2.70)
        monkeypatch.setattr(utils, "FALLBACK_SAFE_CELL_VOLTAGE_MAX", 3.55)
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        wrapper.battery.charge_fet = None
        wrapper.battery.control_allow_charge = False
        _serve(wrapper)

        assert wrapper.get_allow_to_charge() is False


class TestSocAnchoring:
    """The served SoC is the BMS reading moved by the shunt's travel, not the
    shunt's own absolute estimate. Two instruments disagree on absolute SoC by
    a point or two, and publishing that difference at every engagement and
    again at every recovery is a sawtooth on a system that loses its BMS link
    a few times an hour."""

    def test_no_step_at_engagement(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        wrapper.battery.soc = 55.0
        before = wrapper.get_soc()

        _serve(wrapper)

        assert wrapper._serving is True
        assert wrapper.get_soc() == before, "SoC must be continuous across the switch to the shunt"

    def test_shunt_travel_moves_the_served_soc(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        wrapper.battery.soc = 55.0
        _serve(wrapper)

        # the pack discharges 3 points while the BMS is away
        wrapper.dbus_fallback_objects["Soc"].value = _LIVE_SHUNT["Soc"] - 3.0
        _serve(wrapper)

        assert wrapper.get_soc() == pytest.approx(52.0)

    def test_no_step_at_recovery(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        wrapper.battery.soc = 55.0
        _serve(wrapper)
        wrapper.dbus_fallback_objects["Soc"].value = _LIVE_SHUNT["Soc"] - 3.0
        _serve(wrapper)
        served = wrapper.get_soc()

        # BMS returns having counted the same discharge
        wrapper.battery.soc = 52.0
        wrapper.battery.ble_handle.connected = True
        wrapper.refresh_data()

        assert wrapper._serving is False
        assert wrapper.get_soc() == pytest.approx(served)

    def test_without_a_bms_reading_the_shunt_value_is_served(self, monkeypatch):
        # a process that registered from the stash has never seen a BMS SoC,
        # so there is nothing to anchor on and the sensor's own value is all
        # there is
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        wrapper.battery.soc = None
        _serve(wrapper)

        assert wrapper._soc_anchor is None
        assert wrapper.get_soc() == _LIVE_SHUNT["Soc"]

    def test_the_served_soc_stays_in_range(self, monkeypatch):
        # two readings that are each in range can sum out of it
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        wrapper.battery.soc = 99.0
        _serve(wrapper)
        wrapper.dbus_fallback_objects["Soc"].value = _LIVE_SHUNT["Soc"] + 20.0
        _serve(wrapper)

        assert wrapper.get_soc() == 100.0

    def test_the_anchor_is_dropped_on_recovery(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        wrapper.battery.soc = 55.0
        _serve(wrapper)
        assert wrapper._soc_anchor == 55.0

        wrapper.battery.ble_handle.connected = True
        wrapper.refresh_data()

        assert wrapper._soc_anchor is None, "a stale anchor would corrupt the next outage"


class TestOnlineAndConnectionStrings:
    def test_online_is_false_while_serving(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        _serve(wrapper)
        wrapper.battery.online = True
        assert wrapper.online is False

    def test_connection_name_gets_the_fallback_suffix_while_serving(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        assert wrapper.connection_name() == "BLE AA:BB"
        _serve(wrapper)
        assert wrapper.connection_name() == "BLE AA:BB - FALLBACK: on shunt"

    def test_connection_info_tells_the_truth_while_serving(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        wrapper.battery.connection_info = "Connected"
        assert wrapper.connection_info == "Connected"
        _serve(wrapper)
        assert "operating on live fallback values" in wrapper.connection_info


# ── cell projection ──────────────────────────────────────────────────────


class TestCellProjection:
    def _engaged(self, monkeypatch, cells=(3.20, 3.25, 3.30), shunt_voltage=9.75):
        battery = _FakeBattery()
        battery.cell_count = len(cells)
        battery.cells = [Cell(False) for _ in cells]
        for cell, voltage in zip(battery.cells, cells):
            cell.voltage = voltage
        wrapper = _make_wrapper(monkeypatch, shunt=dict(_LIVE_SHUNT, Voltage=shunt_voltage), connected=False, battery=battery)
        # the cells came from a live read a second ago; the known disconnect is
        # what puts the wrapper into serving, not the age of the data
        wrapper._last_fresh_time = _now() - 1
        wrapper.refresh_data()
        return wrapper

    def test_snapshot_is_taken_on_engagement(self, monkeypatch):
        wrapper = self._engaged(monkeypatch)
        assert wrapper._cell_snapshot == [3.20, 3.25, 3.30]

    def test_snapshot_is_refused_when_a_cell_is_unread(self, monkeypatch):
        battery = _FakeBattery()
        battery.cell_count = 3
        battery.cells = [Cell(False) for _ in range(3)]
        battery.cells[0].voltage = 3.2
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False, battery=battery)
        wrapper._last_fresh_time = _now() - 1
        wrapper.refresh_data()
        assert wrapper._cell_snapshot is None
        assert wrapper._projection_valid is False

    def test_projection_distributes_the_delta_evenly(self, monkeypatch):
        wrapper = self._engaged(monkeypatch, shunt_voltage=9.90)  # +0.15 over the 9.75 snapshot sum
        assert wrapper.project_cells(9.90) == pytest.approx([3.25, 3.30, 3.35])

    def test_projection_preserves_cell_ordering(self, monkeypatch):
        wrapper = self._engaged(monkeypatch)
        projected = wrapper.project_cells(9.60)
        assert projected[0] < projected[1] < projected[2]

    def test_projection_needs_a_shunt_voltage(self, monkeypatch):
        wrapper = self._engaged(monkeypatch)
        assert wrapper.project_cells(None) is None

    def test_projection_rejects_an_implausible_delta(self, monkeypatch):
        wrapper = self._engaged(monkeypatch)
        assert wrapper.project_cells(9.75 + 3 * 0.31) is None

    def test_projection_is_published_onto_the_cells(self, monkeypatch):
        wrapper = self._engaged(monkeypatch, shunt_voltage=9.90)
        assert wrapper._projection_valid is True
        assert [cell.voltage for cell in wrapper.battery.cells] == pytest.approx([3.25, 3.30, 3.35])

    def test_basis_age_is_re_checked_continuously(self, monkeypatch):
        wrapper = self._engaged(monkeypatch)
        assert wrapper.project_cells(9.75) is not None
        # same snapshot, but its basis has now aged past the limit
        wrapper._cell_snapshot_time = _now() - (FallbackBattery.SNAPSHOT_MAX_AGE_SECONDS + 1)
        assert wrapper.project_cells(9.75) is None

    def test_stale_basis_refuses_projection_on_the_next_cycle(self, monkeypatch):
        wrapper = self._engaged(monkeypatch)
        wrapper._cell_snapshot_time = _now() - (FallbackBattery.SNAPSHOT_MAX_AGE_SECONDS + 1)
        wrapper.refresh_data()
        assert wrapper._projection_valid is False

    def test_a_process_that_never_saw_live_data_gets_no_basis(self, monkeypatch):
        battery = _FakeBattery()
        battery.cell_count = 3
        battery.cells = [Cell(False) for _ in range(3)]
        for cell in battery.cells:
            cell.voltage = 3.25  # e.g. restored from somewhere, but never read
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False, battery=battery)
        wrapper.refresh_data()
        assert wrapper._projection_valid is False


class TestBandFlags:
    def _wrapper(self, monkeypatch, minimum=2.70, maximum=3.55):
        monkeypatch.setattr(utils, "FALLBACK_SAFE_CELL_VOLTAGE_MIN", minimum)
        monkeypatch.setattr(utils, "FALLBACK_SAFE_CELL_VOLTAGE_MAX", maximum)
        return _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT)

    def test_zone_unset_blocks_charging_keeps_discharging(self, monkeypatch):
        wrapper = self._wrapper(monkeypatch, 0, 0)
        wrapper.update_band_flags(3.2, 3.3)
        assert (wrapper._charge_blocked, wrapper._discharge_blocked) == (True, False)

    def test_inside_the_zone_allows_both(self, monkeypatch):
        wrapper = self._wrapper(monkeypatch)
        wrapper.update_band_flags(3.2, 3.3)
        assert (wrapper._charge_blocked, wrapper._discharge_blocked) == (False, False)

    def test_above_the_zone_blocks_charging_only(self, monkeypatch):
        wrapper = self._wrapper(monkeypatch)
        wrapper.update_band_flags(3.2, 3.60)
        assert (wrapper._charge_blocked, wrapper._discharge_blocked) == (True, False)

    def test_below_the_zone_blocks_discharging_only(self, monkeypatch):
        wrapper = self._wrapper(monkeypatch)
        wrapper.update_band_flags(2.65, 3.3)
        assert (wrapper._charge_blocked, wrapper._discharge_blocked) == (False, True)

    def test_charge_reallow_requires_the_hysteresis_margin(self, monkeypatch):
        wrapper = self._wrapper(monkeypatch)
        wrapper.update_band_flags(3.2, 3.60)
        wrapper.update_band_flags(3.2, 3.54)  # back inside, but not by the margin
        assert wrapper._charge_blocked is True
        wrapper.update_band_flags(3.2, 3.49)
        assert wrapper._charge_blocked is False

    def test_discharge_reallow_requires_the_hysteresis_margin(self, monkeypatch):
        wrapper = self._wrapper(monkeypatch)
        wrapper.update_band_flags(2.65, 3.3)
        wrapper.update_band_flags(2.71, 3.3)
        assert wrapper._discharge_blocked is True
        wrapper.update_band_flags(2.76, 3.3)
        assert wrapper._discharge_blocked is False

    def test_spread_wider_than_the_band_blocks_both(self, monkeypatch):
        wrapper = self._wrapper(monkeypatch)
        wrapper.update_band_flags(2.60, 3.60)
        assert (wrapper._charge_blocked, wrapper._discharge_blocked) == (True, True)


# ── limits, modes and alarms ─────────────────────────────────────────────


class TestGovernedLimits:
    def _engaged(self, monkeypatch, cells=(3.20, 3.25, 3.30), shunt_voltage=9.75, zone=(2.70, 3.55)):
        monkeypatch.setattr(utils, "FALLBACK_SAFE_CELL_VOLTAGE_MIN", zone[0])
        monkeypatch.setattr(utils, "FALLBACK_SAFE_CELL_VOLTAGE_MAX", zone[1])
        battery = _FakeBattery()
        battery.cell_count = len(cells)
        battery.cells = [Cell(False) for _ in cells]
        for cell, voltage in zip(battery.cells, cells):
            cell.voltage = voltage
        battery.control_charge_current = 50
        battery.control_discharge_current = 60
        wrapper = _make_wrapper(monkeypatch, shunt=dict(_LIVE_SHUNT, Voltage=shunt_voltage), connected=False, battery=battery)
        wrapper._last_fresh_time = _now() - 1
        wrapper.refresh_data()
        return wrapper

    def test_limits_are_untouched_without_a_valid_projection(self, monkeypatch):
        # no snapshot at all: reports, not cutoffs — zeroing here took whole banks down
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        wrapper.battery.cells[0].voltage = None
        wrapper.battery.control_charge_current = 50
        wrapper.battery.control_discharge_current = 60
        _serve(wrapper)
        assert wrapper._projection_valid is False
        assert wrapper.control_charge_current == 50
        assert wrapper.control_discharge_current == 60
        assert wrapper.charge_mode == "Fallback - no cell projection (limits unchanged, BMS self-protects)"

    def test_inside_the_zone_keeps_the_limits(self, monkeypatch):
        wrapper = self._engaged(monkeypatch)
        assert wrapper.control_charge_current == 50
        assert wrapper.control_discharge_current == 60
        assert wrapper.charge_mode == "Fallback - operating on projected cells"

    def test_above_the_zone_zeroes_the_charge_limit(self, monkeypatch):
        wrapper = self._engaged(monkeypatch, cells=(3.50, 3.55, 3.60), shunt_voltage=10.65)
        assert wrapper.control_charge_current == 0
        assert wrapper.get_allow_to_charge() is False
        assert wrapper.control_discharge_current == 60
        assert wrapper.charge_mode == "Fallback - charging blocked (projected cell above safe zone)"

    def test_below_the_zone_zeroes_the_discharge_limit(self, monkeypatch):
        wrapper = self._engaged(monkeypatch, cells=(2.60, 2.65, 2.70), shunt_voltage=7.95)
        assert wrapper.control_discharge_current == 0
        assert wrapper.get_allow_to_discharge() is False
        assert wrapper.control_charge_current == 50
        assert wrapper.charge_mode == "Fallback - discharging blocked (projected cell below safe zone)"

    def test_without_a_configured_zone_charging_is_blocked(self, monkeypatch):
        wrapper = self._engaged(monkeypatch, zone=(0, 0))
        assert wrapper.control_charge_current == 0
        assert wrapper.control_discharge_current == 60
        assert wrapper.charge_mode == "Fallback - charging blocked (no safe zone configured)"

    def test_limits_return_to_the_battery_after_recovery(self, monkeypatch):
        wrapper = self._engaged(monkeypatch, cells=(3.50, 3.55, 3.60), shunt_voltage=10.65)
        assert wrapper.control_charge_current == 0
        wrapper.battery.refresh_result = True
        wrapper.battery.ble_handle.connected = True
        wrapper.refresh_data()
        assert wrapper._fallback_mode is False
        assert wrapper.control_charge_current == 50
        assert wrapper.charge_mode is None


class TestAlarms:
    def test_internal_failure_is_suppressed_while_serving(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        wrapper.battery.protection.internal_failure = 2
        _serve(wrapper)
        assert wrapper.battery.protection.internal_failure == 0

    def test_internal_failure_is_not_touched_when_transparent(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=None, connected=False)
        wrapper.battery.refresh_result = False
        wrapper.battery.protection.internal_failure = 2
        _serve(wrapper)
        assert wrapper.battery.protection.internal_failure == 2

    def test_internal_failure_is_cleared_on_recovery(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        _serve(wrapper)
        wrapper.battery.protection.internal_failure = 2
        wrapper.battery.ble_handle.connected = True
        wrapper.refresh_data()
        assert wrapper.battery.protection.internal_failure == 0

    def test_bms_cable_warning_is_delayed_while_serving(self, monkeypatch):
        monkeypatch.setattr(utils, "FALLBACK_BMS_CABLE_WARN_MINUTES", 480.0)
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        _serve(wrapper)
        assert wrapper.bms_cable_alarm == 0
        wrapper._fallback_since = _now() - 480 * 60
        _serve(wrapper)
        assert wrapper.bms_cable_alarm == 1

    def test_bms_cable_alarm_clears_on_recovery(self, monkeypatch):
        monkeypatch.setattr(utils, "FALLBACK_BMS_CABLE_WARN_MINUTES", 0.0)
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        _serve(wrapper)
        assert wrapper.bms_cable_alarm == 1
        wrapper.battery.ble_handle.connected = True
        wrapper.refresh_data()
        assert wrapper.bms_cable_alarm == 0


class TestRecoveryLadder:
    def _stalled(self, wrapper):
        wrapper._stall_action_time = _now() - (FallbackBattery.STALL_MINUTES * 60 + 1)
        wrapper._fallback_since = _now() - (FallbackBattery.STALL_MINUTES * 60 + 1)
        wrapper._last_fresh_time = _now() - (FallbackBattery.STALL_MINUTES * 60 + 1)
        wrapper.refresh_data()

    def test_nothing_happens_before_the_stall_window(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        _serve(wrapper)
        assert wrapper.battery.ble_handle.rebuilds == 0
        assert wrapper.restart_requested is False

    def test_two_rebuilds_then_the_wrapper_holds_without_restarting(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        _serve(wrapper)
        self._stalled(wrapper)
        assert wrapper.battery.ble_handle.rebuilds == 1
        assert wrapper.restart_requested is False
        self._stalled(wrapper)
        assert wrapper.battery.ble_handle.rebuilds == 2
        assert wrapper.restart_requested is False
        # Staleness alone never restarts: a long outage is covered operation,
        # and restart-cycling the service during it is the churn the fallback
        # exists to prevent.
        self._stalled(wrapper)
        self._stalled(wrapper)
        assert wrapper.battery.ble_handle.rebuilds == 2
        assert wrapper.restart_requested is False

    def test_a_mechanically_failing_rebuild_asks_for_a_restart(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        _serve(wrapper)

        def broken_rebuild():
            raise RuntimeError("thread constructor exploded")

        wrapper.battery.ble_handle.rebuild_ble_thread = broken_rebuild
        self._stalled(wrapper)
        assert wrapper.restart_requested is True

    def test_a_driver_without_a_rebuild_hook_holds_without_restarting(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False, rebuildable=False)
        _serve(wrapper)
        self._stalled(wrapper)
        assert wrapper.restart_requested is False

    def test_recovery_resets_the_ladder(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=False)
        _serve(wrapper)
        self._stalled(wrapper)
        assert wrapper._stall_rebuilds == 1
        wrapper.battery.ble_handle.connected = True
        wrapper.refresh_data()
        assert wrapper._stall_rebuilds == 0

    def test_the_ladder_does_not_run_when_transparent(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=None, connected=False)
        wrapper.battery.refresh_result = False
        self._stalled(wrapper)
        assert wrapper.restart_requested is False


# ── persistence and startup ──────────────────────────────────────────────


class TestStash:
    def test_stash_is_written_and_registers_a_fresh_process(self, monkeypatch, tmp_path):
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT, connected=True)
        wrapper.battery.max_battery_voltage = 29.2
        wrapper.refresh_data()
        assert os.path.exists(wrapper._stash_path)

        # a new process, no BMS contact at all
        battery = _FakeBattery()
        battery.cell_count = None
        battery.cells = []
        battery.capacity = None
        battery.max_battery_voltage = None
        restarted = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT, connected=False, battery=battery)
        assert restarted.battery.cell_count == 8
        assert len(restarted.battery.cells) == 8
        assert restarted.battery.capacity == 280.0
        # The stash carries the voltage, for installations where it came from
        # the BMS, but with USE_BMS_DVCC_VALUES off it is config times the cell
        # count, and battery.py derives it from the config as it reads today.
        # See test_an_edited_limit_reaches_a_registration_made_without_bms_contact.
        with open(restarted._stash_path) as stash_file:
            assert json.load(stash_file)["max_battery_voltage"] == 29.2
        assert restarted.battery.max_battery_voltage is None

    def test_restored_cells_are_unread(self, monkeypatch, tmp_path):
        # The stash carries cell voltages as a projection *basis*; no served
        # value is persisted, and the basis is never restored onto the cells.
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT, connected=True)
        wrapper.refresh_data()
        with open(wrapper._stash_path) as stash_file:
            stash = json.load(stash_file)
        assert "voltage" not in stash and "soc" not in stash and "current" not in stash

        battery = _FakeBattery()
        battery.cells = []
        battery.cell_count = None
        restarted = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT, connected=False, battery=battery)
        assert all(cell.voltage is None for cell in restarted.battery.cells)

    def test_stash_is_not_overwritten_during_an_outage(self, monkeypatch, tmp_path):
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT, connected=True)
        wrapper.refresh_data()
        written = os.path.getmtime(wrapper._stash_path)
        wrapper.battery.cell_count = None
        wrapper.battery.ble_handle.connected = False
        _serve(wrapper)
        with open(wrapper._stash_path) as stash_file:
            assert json.load(stash_file)["cell_count"] == 8
        assert os.path.getmtime(wrapper._stash_path) == written

    def test_stash_is_rewritten_only_every_interval(self, monkeypatch, tmp_path):
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT, connected=True)
        wrapper.refresh_data()
        first = wrapper._stash_written
        wrapper.refresh_data()
        assert wrapper._stash_written == first
        wrapper._stash_written = _now() - (FallbackBattery.STASH_INTERVAL_SECONDS + 1)
        wrapper.refresh_data()
        assert wrapper._stash_written > first


class TestPersistedProjectionBasis:
    """What survives a restart is the projection BASIS, not a limit.

    A limit computed from a live projection revises itself when conditions
    change; a persisted limit is a latch, with no input that could ever
    revise it. So the input is what gets written to disk.
    """

    def _restart(self, monkeypatch, tmp_path, shunt=_LIVE_SHUNT, **battery_attributes):
        """A process that starts mid-outage: stash on disk, BMS unreachable."""
        battery = _FakeBattery()
        battery.cells = []
        battery.cell_count = None
        for name, value in battery_attributes.items():
            setattr(battery, name, value)
        return _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=shunt, connected=False, battery=battery)

    def test_the_stash_carries_the_cells_and_the_age_of_the_data(self, monkeypatch, tmp_path):
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT, connected=True)
        wrapper.refresh_data()

        # a later cycle that brings no new observation: the recorded age must
        # follow the data, not the moment of writing
        wrapper._stash_written = 0.0
        wrapper._last_fresh_time = _now() - 5
        wrapper.battery.voltage = None
        wrapper.refresh_data()

        with open(wrapper._stash_path) as stash_file:
            stash = json.load(stash_file)
        assert stash["cells"] == [3.25] * 8
        assert stash["cells_time"] == wrapper._last_fresh_time
        assert stash["timestamp"] - stash["cells_time"] >= 5

    def test_projected_voltages_never_become_the_stashed_basis(self, monkeypatch, tmp_path):
        # A link that drops while its last frame is still fresh engages the
        # projection and refreshes the stash in the same cycle. Only
        # measurements may be a basis - projected cells are our own
        # arithmetic, and stashing them would compound it across restarts.
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=dict(_LIVE_SHUNT, Voltage=24.0), connected=True)
        wrapper.refresh_data()
        wrapper._stash_written = 0.0

        wrapper.battery.ble_handle.connected = False
        wrapper.refresh_data()

        assert wrapper._serving is True and wrapper._projection_valid is True
        assert wrapper.battery.cells[0].voltage == 3.0
        with open(wrapper._stash_path) as stash_file:
            assert json.load(stash_file)["cells"] == [3.25] * 8

    def _seed_stash(self, tmp_path, **overrides):
        """Write a stash as an earlier process would have left it on disk."""
        stash = {
            "timestamp": _now(),
            "cell_count": 8,
            "capacity": 280.0,
            "max_battery_voltage": 27.6,  # an earlier MAX_CELL_VOLTAGE of 3.45
            "min_battery_voltage": 23.2,
            "max_battery_charge_current": 111.0,
            "max_battery_discharge_current": 222.0,
        }
        stash.update(overrides)
        # _FakeBattery's port "ble_test" does not spell out its address "AA:BB"
        path = tmp_path / "fallback_state_ble_test_AA_BB.json"
        path.write_text(json.dumps(stash))
        return path

    def test_an_edited_limit_reaches_a_registration_made_without_bms_contact(self, monkeypatch, tmp_path):
        # The four DVCC values are config, or config times the cell count.
        # Restoring them pinned whatever the config said when the stash was
        # written: a stash holding 27.6 V survived a config raised to 3.60 per
        # cell, because battery.py derives the voltage only while it is still
        # None. Observed live as a CVL stuck at 13.8 on a 4S pack configured
        # for 14.4, across reconnects, until the stash was deleted.
        monkeypatch.setattr(utils, "USE_BMS_DVCC_VALUES", False)
        monkeypatch.setattr(utils, "MAX_CELL_VOLTAGE", 3.60)
        monkeypatch.setattr(utils, "MAX_BATTERY_CHARGE_CURRENT", 250.0)
        monkeypatch.setattr(utils, "MAX_BATTERY_DISCHARGE_CURRENT", 250.0)
        self._seed_stash(tmp_path)

        wrapper = self._restart(monkeypatch, tmp_path)

        # left for battery.py to derive from the cell count and today's config
        assert wrapper.battery.max_battery_voltage is None
        assert wrapper.battery.min_battery_voltage is None
        assert wrapper.battery.max_battery_charge_current == 250.0
        assert wrapper.battery.max_battery_discharge_current == 250.0
        # capacity has no config equivalent, so it is still restored
        assert wrapper.battery.capacity == 280.0
        assert wrapper.battery.cell_count == 8

        # and the derivation now produces the edited number, not the stashed one
        for cell in wrapper.battery.cells:
            cell.voltage = 3.25
        wrapper.battery.soc_calc = 55.0  # the bulk/float logic reads it
        wrapper.manage_charge_voltage()
        assert wrapper.battery.max_battery_voltage == pytest.approx(28.8)

    def test_bms_sourced_limits_are_still_restored(self, monkeypatch, tmp_path):
        # With USE_BMS_DVCC_VALUES on the four values came from the BMS and no
        # config can reproduce them, so a registration without BMS contact has
        # nothing else to publish. Dropping the restore outright would leave
        # those installations with no limits at all.
        monkeypatch.setattr(utils, "USE_BMS_DVCC_VALUES", True)
        monkeypatch.setattr(utils, "MAX_CELL_VOLTAGE", 3.60)
        self._seed_stash(tmp_path)

        wrapper = self._restart(monkeypatch, tmp_path)

        assert wrapper.battery.max_battery_voltage == 27.6
        assert wrapper.battery.min_battery_voltage == 23.2
        assert wrapper.battery.max_battery_charge_current == 111.0
        assert wrapper.battery.max_battery_discharge_current == 222.0

    def test_a_restart_restores_the_basis_and_leaves_the_cells_unread(self, monkeypatch, tmp_path):
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT, connected=True)
        wrapper.refresh_data()

        restarted = self._restart(monkeypatch, tmp_path)

        assert restarted._cell_snapshot == [3.25] * 8
        assert restarted._cell_snapshot_restored is True
        # the basis is an input, never a reading
        assert all(cell.voltage is None for cell in restarted.battery.cells)

    def test_engagement_does_not_clobber_the_restored_basis(self, monkeypatch, tmp_path):
        # every live cell is unread on a restored process - which is exactly
        # the state the old snapshot rule threw the basis away for
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT, connected=True)
        wrapper.refresh_data()

        restarted = self._restart(monkeypatch, tmp_path)
        _serve(restarted)

        assert restarted._cell_snapshot == [3.25] * 8
        assert restarted._projection_valid is True

    def test_a_basis_older_than_the_window_is_refused(self, monkeypatch, tmp_path):
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT, connected=True)
        wrapper.refresh_data()
        with open(wrapper._stash_path) as stash_file:
            stash = json.load(stash_file)
        stash["cells_time"] = _now() - (FallbackBattery.SNAPSHOT_MAX_AGE_SECONDS + 1)
        with open(wrapper._stash_path, "w") as stash_file:
            json.dump(stash, stash_file)

        restarted = self._restart(monkeypatch, tmp_path, max_battery_charge_current=50.0)
        _serve(restarted)

        assert restarted._projection_valid is False
        assert restarted._cell_snapshot is None
        # nothing to compute from: the configured rating, as before
        restarted.manage_charge_and_discharge_current()
        assert restarted.control_charge_current == 50.0

    def test_a_computed_zero_clears_itself_when_the_shunt_moves(self, monkeypatch, tmp_path):
        # The property the whole change exists for. A limit derived from the
        # basis every cycle comes back on its own; a persisted limit would
        # latch until a restart, which is how a zeroed CCL once propagated
        # bank-wide through the aggregate into DVCC.
        monkeypatch.setattr(utils, "FALLBACK_SAFE_CELL_VOLTAGE_MIN", 3.05)
        monkeypatch.setattr(utils, "FALLBACK_SAFE_CELL_VOLTAGE_MAX", 3.55)
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT, connected=True)
        wrapper.refresh_data()

        # 24.0 V over 8 cells projects to 3.00 V/cell: below the safe zone
        restarted = self._restart(monkeypatch, tmp_path, shunt=dict(_LIVE_SHUNT, Voltage=24.0), control_discharge_current=60)
        _serve(restarted)
        assert restarted._projection_valid is True
        assert restarted.control_discharge_current == 0

        # the pack recovers; no restart, no BMS data, no new basis
        restarted.dbus_fallback_objects["Voltage"].value = 25.2
        _serve(restarted)
        assert restarted.control_discharge_current == 60

    def test_a_restored_basis_is_never_published_as_a_cell_measurement(self, monkeypatch, tmp_path):
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT, connected=True)
        wrapper.refresh_data()

        restarted = self._restart(monkeypatch, tmp_path)
        _serve(restarted)
        # the BMS answers again: the projection is undone, and a basis that
        # came off disk is put back as unread rather than as a reading
        restarted.battery.ble_handle.connected = True
        restarted.refresh_data()

        assert all(cell.voltage is None for cell in restarted.battery.cells)


class TestStashIdentifier:
    def test_a_ble_port_does_not_repeat_its_address(self, monkeypatch, tmp_path):
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, battery=_FakeBattery(port="ble_5320b7d7f9e7", address="53:20:B7:D7:F9:E7"))
        assert os.path.basename(wrapper._stash_path) == "fallback_state_ble_5320b7d7f9e7.json"

    def test_a_serial_port_keeps_the_bus_address_apart(self, monkeypatch, tmp_path):
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, battery=_FakeBattery(port="/dev/ttyUSB0", address="0x02"))
        assert os.path.basename(wrapper._stash_path) == "fallback_state_ttyUSB0_0x02.json"


class TestTestConnection:
    def test_successful_driver_test_stamps_freshness(self, monkeypatch, tmp_path):
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT)
        assert wrapper.test_connection() is True
        assert wrapper._last_fresh_time > 0

    def test_failed_driver_test_registers_from_the_stash(self, monkeypatch, tmp_path):
        monkeypatch.setattr(utils, "FALLBACK_SENSOR_DBUS_DEVICE", "com.victronenergy.battery.ttyS2")
        monkeypatch.setattr(FallbackBattery, "STASH_DIRECTORY", str(tmp_path))
        battery = _FakeBattery()
        battery.refresh_result = False
        wrapper = FallbackBattery(battery)
        wrapper._stash = {"cell_count": 8, "capacity": 280.0}
        assert wrapper.test_connection() is True

    def test_failed_driver_test_without_a_stash_fails(self, monkeypatch, tmp_path):
        monkeypatch.setattr(utils, "FALLBACK_SENSOR_DBUS_DEVICE", "com.victronenergy.battery.ttyS2")
        monkeypatch.setattr(FallbackBattery, "STASH_DIRECTORY", str(tmp_path))
        battery = _FakeBattery()
        battery.refresh_result = False
        assert FallbackBattery(battery).test_connection() is False

    def test_failed_driver_test_without_a_device_fails(self, monkeypatch, tmp_path):
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path)
        wrapper.battery.refresh_result = False
        wrapper._stash = {"cell_count": 8}
        assert wrapper.test_connection() is False

    def test_unread_cells_do_not_raise_error_code_eight(self, monkeypatch, tmp_path):
        # Observed live: a stash-registered battery has cells that exist but
        # were never read, and manage_charge_voltage's cell-diff subtraction
        # raised TypeError -> CVL collapsed to float + manage_error_code(8).
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT, connected=False)
        for cell in wrapper.battery.cells:
            cell.voltage = None
        wrapper.battery.control_voltage = None
        wrapper.battery.max_battery_voltage = 14.6
        wrapper.battery.error_code = None

        wrapper.manage_charge_voltage()

        assert wrapper.battery.control_voltage == 14.6
        assert wrapper.battery.charge_mode != "Error, please check the logs!"
        assert wrapper.battery.error_code is None

    def test_unread_cells_without_a_stashed_ceiling_use_the_configured_cell_maximum(self, monkeypatch, tmp_path):
        # A stash written before the BMS ever reported its pack limits leaves
        # max_battery_voltage None, and publishing no CVL at all is the case
        # velib turns into an *invalid* limit downstream.
        monkeypatch.setattr(utils, "MAX_CELL_VOLTAGE", 3.45)
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT, connected=False)
        for cell in wrapper.battery.cells:
            cell.voltage = None
        wrapper.battery.control_voltage = None
        wrapper.battery.max_battery_voltage = None
        wrapper.battery.cell_count = 8

        wrapper.manage_charge_voltage()

        assert wrapper.battery.control_voltage == pytest.approx(27.6)

    def test_unread_cells_publish_configured_currents_without_errors(self, monkeypatch, tmp_path):
        # The cell-voltage and temperature limiters raise on unread cells and
        # each raises error code 8 while falling back to configured currents,
        # so the limiter must not be entered at all. Not running it is what
        # the untouched charge/discharge_limitation strings witness.
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT, connected=False)
        for cell in wrapper.battery.cells:
            cell.voltage = None
        wrapper.battery.max_battery_charge_current = 50.0
        wrapper.battery.max_battery_discharge_current = 60.0
        wrapper.battery.error_code = None

        wrapper.manage_charge_and_discharge_current()

        assert wrapper.battery.control_charge_current == 50.0
        assert wrapper.battery.control_discharge_current == 60.0
        assert wrapper.battery.error_code is None
        assert wrapper.battery.charge_limitation is None
        assert wrapper.battery.discharge_limitation is None

    def test_real_cells_still_run_the_current_limiter(self, monkeypatch, tmp_path):
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT)
        ran = []
        wrapper.battery.manage_charge_and_discharge_current = lambda: ran.append(True)
        wrapper.manage_charge_and_discharge_current()
        assert ran == [True]

    def test_unread_temperatures_publish_configured_currents_without_warnings(self, monkeypatch, tmp_path):
        # The temperature limiter logs a warning on every cycle its inputs
        # are None - observed at two per second for a whole registration
        # window, on a device that logs to flash. Cells being readable is not
        # enough: temperatures are never projected, so the limiter suite must
        # wait for a real frame.
        monkeypatch.setattr(utils, "CCCM_T_ENABLE", True)
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT)
        wrapper.battery.temperature_1 = None
        wrapper.battery.temperature_2 = None
        wrapper.battery.max_battery_charge_current = 50.0
        wrapper.battery.max_battery_discharge_current = 60.0
        ran = []
        wrapper.battery.manage_charge_and_discharge_current = lambda: ran.append(True)

        wrapper.manage_charge_and_discharge_current()

        assert ran == []
        assert wrapper.battery.control_charge_current == 50.0
        assert wrapper.battery.control_discharge_current == 60.0

    def test_disabled_temperature_limiting_does_not_wait_for_temperatures(self, monkeypatch, tmp_path):
        # With temperature limiting off the limiters never consult the
        # sensors, so unread temperatures are no reason to hold back.
        monkeypatch.setattr(utils, "CCCM_T_ENABLE", False)
        monkeypatch.setattr(utils, "DCCM_T_ENABLE", False)
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT)
        wrapper.battery.temperature_1 = None
        wrapper.battery.temperature_2 = None
        ran = []
        wrapper.battery.manage_charge_and_discharge_current = lambda: ran.append(True)

        wrapper.manage_charge_and_discharge_current()

        assert ran == [True]

    def test_real_cells_still_run_the_state_machine(self, monkeypatch, tmp_path):
        wrapper = _make_wrapper(monkeypatch, tmp_path=tmp_path, shunt=_LIVE_SHUNT)
        ran = []
        wrapper.battery.manage_charge_voltage = lambda: ran.append(True)
        wrapper.manage_charge_voltage()
        assert ran == [True]

    def test_stash_registration_serves_before_the_service_exists(self, monkeypatch, tmp_path):
        # The paths are added as None by setup_vedbus; a consumer that
        # recomputes on value change samples that leading edge. Values must
        # already be real when test_connection returns.
        monkeypatch.setattr(utils, "FALLBACK_SENSOR_DBUS_DEVICE", "com.victronenergy.battery.ttyS2")
        monkeypatch.setattr(FallbackBattery, "STASH_DIRECTORY", str(tmp_path))
        battery = _FakeBattery()
        battery.refresh_result = False
        battery.voltage = None
        battery.current = None
        battery.soc = None
        wrapper = FallbackBattery(battery)
        wrapper._stash = {"cell_count": 8, "capacity": 280.0}
        wrapper.dbus_fallback_objects = {key: _FakeDbusItem(value) for key, value in _LIVE_SHUNT.items()}

        assert wrapper.test_connection() is True
        assert wrapper._serving is True
        assert wrapper.get_voltage() == _LIVE_SHUNT["Voltage"]
        assert wrapper.get_current() == _LIVE_SHUNT["Current"]
        assert wrapper.get_soc() == _LIVE_SHUNT["Soc"]


# ── end to end through DbusHelper ────────────────────────────────────────


class _FakeDbusService(dict):
    """Stand-in for the VeDbusService proxy: a dict that can be entered."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def add_path(self, path, value, **kwargs):
        self[path] = value

    def register(self):
        self.registered = True


class _FakeLoop:
    def __init__(self):
        self.quit_called = False

    def quit(self):
        self.quit_called = True


class TestPublishCycleThroughDbusHelper:
    """Drive the real DbusHelper publish cycle against a wrapped battery.

    This is the completeness check for the delegation surface: every
    attribute, getter and setter DbusHelper touches has to resolve through
    the wrapper, and the published values have to come from the shunt.
    """

    def _helper(self, monkeypatch, connected=False, shunt=_LIVE_SHUNT):
        from dbushelper import DbusHelper

        monkeypatch.setattr(utils, "EXTERNAL_SENSOR_DBUS_DEVICE", None)
        monkeypatch.setattr(utils, "TIME_TO_GO_ENABLE", False)
        monkeypatch.setattr(utils, "TIME_TO_SOC_POINTS", [])
        monkeypatch.setattr(utils, "HISTORY_ENABLE", False)
        monkeypatch.setattr(utils, "BMS_CABLE_ALARM", True)
        monkeypatch.setattr(utils, "FALLBACK_BMS_CABLE_WARN_MINUTES", 480.0)

        wrapper = _make_wrapper(monkeypatch, shunt=shunt, connected=connected)
        helper = DbusHelper.__new__(DbusHelper)
        helper.battery = wrapper
        helper.cell_voltages_good = None
        helper.disconnect_threshold = None
        helper.bms_cable_alarm = 0
        helper.error = {"cleared": True, "count": 0, "timestamp_first": None, "timestamp_last": None}
        helper._dbusservice = _FakeDbusService({"/Mode": 3})
        helper.history_calculated_last_time = int(_now())
        helper.settings_saved_last_time = int(_now())
        helper.last_seen_saved_last_time = int(_now())
        helper.telemetry_upload = lambda: None
        return helper

    def test_a_fallback_served_soc_still_registers_the_bms_comparison_paths(self, monkeypatch):
        # The live configuration sets FALLBACK_SENSOR_DBUS_PATH_SOC and
        # neither SOC_CALCULATION nor EXTERNAL_SENSOR_DBUS_PATH_SOC, so
        # gating these three paths on the other two alone deletes them from
        # the running service and the documented BMS-vs-shunt comparison
        # disappears without a word.
        monkeypatch.setattr(utils, "SOC_CALCULATION", False)
        monkeypatch.setattr(utils, "EXTERNAL_SENSOR_DBUS_PATH_SOC", None)
        monkeypatch.setattr(utils, "FALLBACK_SENSOR_DBUS_PATH_SOC", "/Soc")
        monkeypatch.setattr(utils, "PUBLISH_CONFIG_VALUES", False)
        monkeypatch.setattr(utils, "BATTERY_CELL_DATA_FORMAT", 0)

        helper = self._helper(monkeypatch)
        helper.setup_instance = lambda: True
        helper._dbusname = "com.victronenergy.battery.ble_test"
        helper.bms_id = "ble_test"
        helper.instance = 1
        helper.settings = {"CustomName": "Test"}
        helper._dbusservice = _FakeDbusService()

        assert helper.setup_vedbus() is True

        service = helper._dbusservice
        assert "/SocBms" in service
        assert "/CapacityBms" in service
        assert "/ConsumedAmphoursBms" in service

        # and the publish cycle fills them with the BMS's own values rather
        # than the shunt-served ones
        helper.battery.battery.capacity_remain = 170.0
        helper.battery._last_fresh_time = _now() - 100
        helper.publish_battery(_FakeLoop())
        assert service["/SocBms"] == round(helper.battery.battery.soc, 2)
        assert service["/CapacityBms"] == 170.0

        # The served SoC is anchored on the BMS reading, so the two agree at
        # engagement and only separate as the shunt travels. Move the shunt
        # and they must diverge by exactly that travel, which is the whole
        # point of keeping the comparison path.
        helper.battery.dbus_fallback_objects["Soc"].value = _LIVE_SHUNT["Soc"] - 4.0
        helper.publish_battery(_FakeLoop())
        assert service["/Soc"] == pytest.approx(service["/SocBms"] - 4.0)

    def test_a_cell_blind_battery_never_publishes_an_invalid_charge_limit(self, monkeypatch):
        # velib maps a None publish to *invalid* rather than refusing it, and
        # a consumer taking a bank minimum over its constituents then hands
        # DVCC an invalid limit. Observed live on this system.
        helper = self._helper(monkeypatch)
        helper._dbusservice["/Info/MaxChargeVoltage"] = 14.6
        for cell in helper.battery.battery.cells:
            cell.voltage = None
        helper.battery.battery.control_voltage = None

        helper.publish_battery(None)

        assert helper._dbusservice["/Info/MaxChargeVoltage"] is not None
        assert helper._dbusservice["/Info/MaxChargeCurrent"] is not None
        assert helper._dbusservice["/Info/MaxDischargeCurrent"] is not None

    def test_a_full_cycle_publishes_the_shunt_values(self, monkeypatch):
        helper = self._helper(monkeypatch)
        helper.battery._last_fresh_time = _now() - 100
        loop = _FakeLoop()

        helper.publish_battery(loop)

        service = helper._dbusservice
        assert service["/Dc/0/Voltage"] == 25.5
        assert service["/Dc/0/Current"] == -12.0
        assert service["/Dc/0/Temperature"] == 21.0
        assert service["/Soc"] == 55.0
        assert service["/Capacity"] == pytest.approx(280.0 * 55.0 / 100)
        assert service["/System/NrOfModulesOnline"] == 0
        assert service["/System/NrOfModulesOffline"] == 1
        assert service["/Mgmt/Connection"] == "BLE AA:BB - FALLBACK: on shunt"
        assert "operating on live fallback values" in service["/ConnectionInformation"]
        assert service["/Alarms/InternalFailure"] == 0
        assert service["/Alarms/BmsCable"] == 0
        # serving is not an outage as far as the driver lifecycle goes
        assert loop.quit_called is False

    def test_a_full_cycle_publishes_bms_values_while_fresh(self, monkeypatch):
        helper = self._helper(monkeypatch, connected=True)
        loop = _FakeLoop()

        helper.publish_battery(loop)

        service = helper._dbusservice
        assert service["/Dc/0/Voltage"] == 26.0
        assert service["/System/NrOfModulesOnline"] == 1
        assert service["/Mgmt/Connection"] == "BLE AA:BB"
        assert loop.quit_called is False

    def test_the_delayed_cable_warning_reaches_dbus(self, monkeypatch):
        helper = self._helper(monkeypatch)
        helper.battery._last_fresh_time = _now() - 100
        helper.publish_battery(_FakeLoop())
        helper.battery._fallback_since = _now() - 480 * 60
        helper.publish_battery(_FakeLoop())
        assert helper._dbusservice["/Alarms/BmsCable"] == 1

    def test_a_restart_request_quits_the_loop(self, monkeypatch):
        helper = self._helper(monkeypatch)
        helper.battery._last_fresh_time = _now() - 100
        helper.battery.restart_requested = True
        loop = _FakeLoop()
        helper.publish_battery(loop)
        assert loop.quit_called is True
        assert helper._dbusservice["/Alarms/BmsCable"] == 2

    def test_both_dark_falls_through_to_the_stock_disconnect_handling(self, monkeypatch):
        helper = self._helper(monkeypatch, shunt={"Voltage": None})
        helper.battery.battery.refresh_result = False
        helper.battery._last_fresh_time = _now() - 100
        helper.publish_battery(_FakeLoop())
        # the wrapper stepped aside: DbusHelper counted an error of its own
        assert helper.error["count"] == 1
        assert helper.battery._serving is False


# ── delegation integrity ─────────────────────────────────────────────────


#: Every attribute and method DbusHelper reads off the battery. Generated with
#:   grep -o "self\.battery\.[a-zA-Z_]*" dbus-serialbattery/dbushelper.py
#: The wrapper must resolve all of them, or the driver dies at publish time.
_DBUSHELPER_READS = (
    "address allow_max_voltage callback_balancing_turn_off callback_charging_force_off callback_discharging_force_off callback_heating_turn_off "
    "callback_soc_reset_to callbacks_available capacity cell_count cells charge_discharged_last charge_limitation charge_mode charge_mode_debug "
    "charge_mode_debug_bulk charge_mode_debug_float connection_info connection_name control_charge_current control_discharge_current control_voltage "
    "current_avg current_avg_lst current_calc custom_field custom_name dbus_external_objects discharge_limitation error_code "
    "error_code_last_reset_check get_allow_to_balance get_allow_to_charge get_allow_to_discharge get_allow_to_heat get_balancing "
    "get_capacity_consumed get_capacity_consumed_bms get_capacity_remain get_capacity_remain_bms get_cell_balancing get_heating get_max_cell_desc "
    "get_max_cell_voltage get_max_temperature get_max_temperature_id get_midvoltage get_min_cell_desc get_min_cell_voltage get_min_temperature "
    "get_min_temperature_id get_seconds_to_string get_temperature get_time_to_soc get_voltage hardware_version has_settings heater_current "
    "heater_power heater_temperature_start heater_temperature_stop history history_calculate_values history_reset_callback init_values "
    "last_refresh_duration log_cell_data manage_charge_and_discharge_current manage_charge_voltage manage_error_code manage_error_code_reset "
    "max_battery_charge_current max_battery_discharge_current max_battery_voltage max_voltage_start_time min_battery_voltage online port power_calc "
    "previous_current_avg product_name production protection refresh_data role set_calculated_data setup_external_sensor soc soc_calc "
    "soc_calc_capacity_remain soc_reset_last_reached soc_reset_requested soh start_time state temperature_1 temperature_2 temperature_3 "
    "temperature_4 temperature_mos time_to_soc_update type unique_identifier"
).split()


class TestDelegation:
    def test_every_attribute_dbushelper_reads_resolves(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT)
        # DbusHelper stamps this one itself before reading it back
        wrapper.last_refresh_duration = 0.1
        missing = [name for name in _DBUSHELPER_READS if not hasattr(wrapper, name)]
        assert missing == []

    def test_writes_reach_the_wrapped_battery(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT)
        wrapper.state = 14
        wrapper.temperature_1 = 19.5
        wrapper.connection_info = "Connected"
        wrapper.online = True
        assert wrapper.battery.state == 14
        assert wrapper.battery.temperature_1 == 19.5
        assert wrapper.battery.connection_info == "Connected"
        assert wrapper.battery.online is True

    def test_wrapper_state_does_not_leak_onto_the_battery(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT)
        wrapper._serving = True
        assert not hasattr(wrapper.battery, "_serving")
        assert wrapper._serving is True

    def test_class_identity_is_the_wrapped_driver(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT)
        assert isinstance(wrapper, Battery)
        assert wrapper.__class__ is _FakeBattery
        assert isinstance(wrapper, FallbackBattery)

    def test_unknown_attributes_still_raise(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT)
        with pytest.raises(AttributeError):
            wrapper.there_is_no_such_attribute

    def test_read_fallback_sensor_bypasses_the_serving_gate(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=_LIVE_SHUNT, connected=True)
        wrapper.refresh_data()
        assert wrapper._serving is False
        assert wrapper.read_fallback_sensor("Voltage") == 25.5
        assert wrapper.get_value_from_fallback_sensor("Voltage") is None

    def test_read_fallback_sensor_is_none_when_unresolved(self, monkeypatch):
        wrapper = _make_wrapper(monkeypatch, shunt=None)
        assert wrapper.read_fallback_sensor("Voltage") is None
        wrapper.dbus_fallback_objects = {"Voltage": _FakeDbusItem(25.5)}
        assert wrapper.read_fallback_sensor("Current") is None


# ── import-time configuration validation ─────────────────────────────────


class TestUtilsImportTimeConfig:
    """Import utils.py for real against a config file, so import-time validation
    and clamping runs — the class of bug the monkeypatch pattern structurally
    misses (production incident: config values silently clamped + error #119)."""

    def _import_utils_with_config(self, tmp_path, config_ini):
        import shutil
        import subprocess

        src = os.path.join(os.path.dirname(__file__), "..", "dbus-serialbattery")
        shutil.copy(os.path.join(src, "utils.py"), tmp_path / "utils.py")
        shutil.copy(os.path.join(src, "config.default.ini"), tmp_path / "config.default.ini")
        (tmp_path / "config.ini").write_text(config_ini)
        # minimal serial stub so utils imports without pyserial
        (tmp_path / "serial.py").write_text(
            "class Serial:\n    pass\n\nclass SerialException(IOError):\n    pass\n\nEIGHTBITS = 8\nPARITY_NONE = 'N'\nSTOPBITS_ONE = 1\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", "import utils, json; print(json.dumps(utils.errors_in_config))"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"utils import failed: {result.stderr}"
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_the_production_configuration_loads_without_config_errors(self, tmp_path):
        errors = self._import_utils_with_config(
            tmp_path,
            "[DEFAULT]\n"
            "FALLBACK_SENSOR_DBUS_DEVICE = ble_test:com.victronenergy.battery.ttyS5\n"
            "FALLBACK_SENSOR_DBUS_PATH_VOLTAGE = /Dc/0/Voltage\n"
            "FALLBACK_SENSOR_DBUS_PATH_CURRENT = /Dc/0/Current\n"
            "FALLBACK_SENSOR_DBUS_PATH_TEMPERATURE = /Dc/0/Temperature\n"
            "FALLBACK_SENSOR_DBUS_PATH_SOC = /Soc\n"
            "FALLBACK_BMS_CABLE_WARN_MINUTES = 480\n"
            "FALLBACK_SAFE_CELL_VOLTAGE_MIN = 2.70\n"
            "FALLBACK_SAFE_CELL_VOLTAGE_MAX = 3.55\n",
        )
        assert errors == []

    def test_paths_without_a_device_report_a_config_error(self, tmp_path):
        errors = self._import_utils_with_config(
            tmp_path,
            "[DEFAULT]\nFALLBACK_SENSOR_DBUS_PATH_VOLTAGE = /Dc/0/Voltage\n",
        )
        assert any("FALLBACK_SENSOR_DBUS_DEVICE" in error for error in errors)

    def test_safe_zone_min_without_max_reports_a_config_error(self, tmp_path):
        errors = self._import_utils_with_config(
            tmp_path,
            "[DEFAULT]\nFALLBACK_SAFE_CELL_VOLTAGE_MIN = 2.70\n",
        )
        assert any("FALLBACK_SAFE_CELL_VOLTAGE" in error for error in errors)

    def test_the_retired_stop_minutes_knob_is_gone(self, tmp_path):
        errors = self._import_utils_with_config(tmp_path, "[DEFAULT]\n")
        assert not any("FALLBACK_STOP_MINUTES" in error for error in errors)
        assert not hasattr(utils, "FALLBACK_STOP_MINUTES")
