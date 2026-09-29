# -*- coding: utf-8 -*-
"""Tests for the /Measurement/* topology declarations published by DbusHelper.

They tell consumers that sum battery services whether two services are two
batteries or two views of the same physical battery.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dbus-serialbattery"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dbus-serialbattery", "ext", "velib_python"))

import utils  # noqa: E402
from battery import Battery  # noqa: E402
from dbushelper import DbusHelper  # noqa: E402
from fallback_battery import FallbackBattery  # noqa: E402


# concrete subclass so the abstract Battery can be instantiated without a BMS
_ConcreteBattery = type("_ConcreteBattery", (Battery,), {name: lambda self, *a, **kw: None for name in Battery.__abstractmethods__})


class _FakeBattery(_ConcreteBattery):
    """A battery with just enough surface for setup_vedbus()."""

    def __init__(self):
        super().__init__("/dev/ttyUSB0", 9600, None)
        self.type = "Fake"
        self.cells = []
        self.has_settings = False

    def unique_identifier(self):
        return "FAKE-0001"

    def connection_name(self):
        return "Serial /dev/ttyUSB0"

    def product_name(self):
        return "SerialBattery(Fake)"


class _PairedBattery(_FakeBattery):
    """A battery that knows about another service measuring the same pack."""

    PAIRED_SERVICE = "com.victronenergy.battery.ttyUSB1"

    def get_paired_sensor_device(self):
        return self.PAIRED_SERVICE


class _FakeDbusService(dict):
    """Stand-in for the VeDbusService proxy: records the registered paths."""

    def __init__(self):
        super().__init__()
        self.registered = False

    def add_path(self, path, value, **kwargs):
        self[path] = value

    def register(self):
        self.registered = True


def _run_setup_vedbus(monkeypatch, battery):
    """Drive the real setup_vedbus() against a fake service and return it."""
    # keep the optional path groups out of the way, they are not under test
    monkeypatch.setattr(utils, "SOC_CALCULATION", False)
    monkeypatch.setattr(utils, "EXTERNAL_SENSOR_DBUS_PATH_SOC", None)
    monkeypatch.setattr(utils, "BATTERY_CELL_DATA_FORMAT", 0)
    monkeypatch.setattr(utils, "TIME_TO_GO_ENABLE", False)
    monkeypatch.setattr(utils, "PUBLISH_CONFIG_VALUES", False)
    monkeypatch.setattr(DbusHelper, "setup_instance", lambda self: True)

    helper = DbusHelper.__new__(DbusHelper)
    helper.battery = battery
    helper.instance = 1
    helper.bms_id = "FAKE_0001"
    helper.settings = {"CustomName": ""}
    helper._dbusname = "com.victronenergy.battery.ttyUSB0"
    helper._dbusservice = _FakeDbusService()

    assert helper.setup_vedbus() is True
    assert helper._dbusservice.registered is True
    return helper._dbusservice


def test_a_battery_declares_itself_as_a_direct_measurement(monkeypatch):
    service = _run_setup_vedbus(monkeypatch, _FakeBattery())

    assert service["/Measurement/Kind"] == "direct"


def test_the_physical_device_id_is_derived_from_the_bms_id(monkeypatch):
    service = _run_setup_vedbus(monkeypatch, _FakeBattery())

    assert service["/Measurement/PhysicalDevice"] == "battery:FAKE_0001"


def test_an_unpaired_battery_declares_no_peers(monkeypatch):
    """Stock upstream case: no battery has a paired sensor service, so the
    peer paths must not be registered at all."""
    service = _run_setup_vedbus(monkeypatch, _FakeBattery())

    assert "/Measurement/PeerServices" not in service
    assert "/Measurement/LineAuthority" not in service


def test_a_paired_battery_declares_its_peer_and_line_authority(monkeypatch):
    service = _run_setup_vedbus(monkeypatch, _PairedBattery())

    assert service["/Measurement/PeerServices"] == _PairedBattery.PAIRED_SERVICE
    assert service["/Measurement/LineAuthority"] == _PairedBattery.PAIRED_SERVICE
    # the pairing does not change what this service measures
    assert service["/Measurement/Kind"] == "direct"
    assert service["/Measurement/PhysicalDevice"] == "battery:FAKE_0001"


@pytest.mark.parametrize("path", ["/Measurement/Kind", "/Measurement/PhysicalDevice"])
def test_the_always_present_paths_carry_a_value(monkeypatch, path):
    """A consumer keys off /Measurement/Kind to know the vocabulary is spoken,
    so neither of the two unconditional paths may be published as None."""
    service = _run_setup_vedbus(monkeypatch, _FakeBattery())

    assert service[path] is not None


# ── the seam with the fallback wrapper ───────────────────────────────────
#
# The declarations above look up the pairing generically, and the fallback
# wrapper is the first thing to supply it. These tests wire the two together
# with no test double in between: a real FallbackBattery, configured exactly
# as an installation configures it, driven through the real setup_vedbus().


def _wrap(monkeypatch, tmp_path, battery, device):
    """Wrap a battery the way the harness does, with `device` configured as
    its fallback sensor."""
    monkeypatch.setattr(FallbackBattery, "STASH_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(utils, "FALLBACK_SENSOR_DBUS_DEVICE", device)
    return FallbackBattery(battery)


def test_a_wrapped_battery_declares_its_shunt_as_peer_and_line_authority(monkeypatch, tmp_path):
    """The whole point of the pairing hook: a battery wrapped by the fallback
    wrapper, with a fallback sensor configured, publishes that sensor's service
    as its peer and its line authority."""
    shunt = "com.victronenergy.battery.ttyUSB1"
    wrapper = _wrap(monkeypatch, tmp_path, _FakeBattery(), shunt)

    service = _run_setup_vedbus(monkeypatch, wrapper)

    assert service["/Measurement/PeerServices"] == shunt
    assert service["/Measurement/LineAuthority"] == shunt
    # wrapping changes nothing about what this service itself measures
    assert service["/Measurement/Kind"] == "direct"
    assert service["/Measurement/PhysicalDevice"] == "battery:FAKE_0001"


def test_the_per_battery_mapping_reaches_the_declaration(monkeypatch, tmp_path):
    """With one shunt per battery the config maps them by port; the declared
    peer must be this battery's shunt, not some other battery's."""
    mapping = "ttyUSB0:com.victronenergy.battery.ttyUSB1, ttyUSB9:com.victronenergy.battery.ttyUSB8"
    wrapper = _wrap(monkeypatch, tmp_path, _FakeBattery(), mapping)

    service = _run_setup_vedbus(monkeypatch, wrapper)

    assert service["/Measurement/PeerServices"] == "com.victronenergy.battery.ttyUSB1"
    assert service["/Measurement/LineAuthority"] == "com.victronenergy.battery.ttyUSB1"


def test_a_wrapped_battery_without_a_mapped_shunt_declares_no_peers(monkeypatch, tmp_path):
    """Being wrapped is not itself a pairing: if no fallback sensor resolves
    for this battery, the optional paths stay off the service."""
    wrapper = _wrap(monkeypatch, tmp_path, _FakeBattery(), "ttyUSB9:com.victronenergy.battery.ttyUSB8")

    service = _run_setup_vedbus(monkeypatch, wrapper)

    assert "/Measurement/PeerServices" not in service
    assert "/Measurement/LineAuthority" not in service
    assert service["/Measurement/Kind"] == "direct"
