"""The service publishes real values at registration, before the first poll tick.

Drives the real ``main()`` with a probe BMS on a stand-in serial port. GLib is
a stub here, so ``mainloop.run()`` returns at once and no poll tick ever
fires: whatever is on the bus when ``main()`` returns was published during
registration.
"""

import importlib.util
import os
import signal
import sys
from collections import defaultdict

import pytest

import dbushelper
from battery import Battery, Cell

# the conftest stub for dbus.mainloop.glib is an empty module
sys.modules["dbus.mainloop.glib"].DBusGMainLoop = lambda *a, **kw: None


class RecordingService:
    """Stands in for VeDbusService, keeping the current value of every path."""

    def __init__(self, *a, **kw):
        self.values = {}

    def add_path(self, path, value=None, *a, **kw):
        self.values[path] = value

    def __setitem__(self, path, value):
        self.values[path] = value

    def __getitem__(self, path):
        return self.values.get(path)

    def __getattr__(self, name):
        return lambda *a, **kw: None


class ProbeBattery(Battery):
    """A healthy 4s LiFePO4, as test_connection() would leave it."""

    def __init__(self, port, baud, address):
        super().__init__(port, baud, address)
        self.type = "Probe"

    def test_connection(self):
        self.cell_count = 4
        self.cells = [Cell(False) for _ in range(4)]
        for cell in self.cells:
            cell.voltage = 3.325
        self.voltage = 13.3
        self.current = 2.0
        self.soc = 80
        self.capacity = 100
        self.charge_fet = True
        self.discharge_fet = True
        self.max_battery_voltage = 14.2
        self.min_battery_voltage = 12.0
        self.max_battery_charge_current = 50
        self.max_battery_discharge_current = 60
        return True

    def get_settings(self):
        return True

    def refresh_data(self):
        return True

    def unique_identifier(self):
        return "probe"


def _load_driver():
    path = os.path.join(os.path.dirname(__file__), "..", "dbus-serialbattery", "dbus-serialbattery.py")
    spec = importlib.util.spec_from_file_location("dbus_serialbattery_main", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def service(monkeypatch, tmp_path):
    driver = _load_driver()
    services = []

    def _service(*a, **kw):
        services.append(RecordingService())
        return services[-1]

    def _instance(self):
        # what setup_instance() leaves behind after reading the settings service
        self.settings = defaultdict(lambda: 0, {"CustomName": "Probe"})
        return True

    monkeypatch.setattr(dbushelper, "VeDbusService", _service)
    monkeypatch.setattr(dbushelper.DbusHelper, "setup_instance", _instance)
    monkeypatch.setattr(dbushelper.DbusHelper, "get_settings_with_values", lambda self, *a, **kw: {})
    monkeypatch.setattr(dbushelper.DbusHelper, "set_settings", lambda self, *a, **kw: True)
    monkeypatch.setattr(dbushelper.DbusHelper, "save_current_battery_state", lambda self, *a, **kw: True)
    monkeypatch.setattr(driver, "supported_bms_types", [{"bms": ProbeBattery, "baud": 9600}])
    monkeypatch.setattr(driver, "expected_bms_types", [{"bms": ProbeBattery, "baud": 9600}])
    monkeypatch.setattr(driver, "load_bms_detection_cache", lambda: {})
    monkeypatch.setattr(driver, "save_bms_detection_cache", lambda cache: None)
    monkeypatch.setattr(driver, "sleep", lambda seconds: None)
    for name in ("get_venus_os_version", "get_venus_os_image_type", "get_venus_os_device_type"):
        monkeypatch.setattr(driver, name, lambda: "probe")
    monkeypatch.setattr(signal, "signal", lambda *a: None)

    port = tmp_path / "ttyProbe"
    port.touch()
    monkeypatch.setattr(sys, "argv", ["dbus-serialbattery.py", str(port)])

    driver.main()
    assert len(services) == 1, "main() should register exactly one battery service"
    return services[0]


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/Dc/0/Voltage", 13.3),
        ("/Dc/0/Current", 2.0),
        ("/Soc", 80),
        ("/System/MinCellVoltage", 3.325),
        ("/System/MaxCellVoltage", 3.325),
    ],
)
def test_values_are_published_at_registration(service, path, expected):
    # setup_vedbus() registers these as None; without the publish in main()
    # they stay None until the first poll tick, which never fires here
    assert service.values[path] == pytest.approx(expected)
