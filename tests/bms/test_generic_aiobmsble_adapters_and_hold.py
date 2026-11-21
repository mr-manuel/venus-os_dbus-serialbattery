# -*- coding: utf-8 -*-
"""Tests for Generic_AioBmsBle adapter-aware device resolution and hold flag.

The vendored aiobmsble stack is stubbed out; only the wrapper's own logic
runs. generic_aiobmsble uses PEP 604 annotations evaluated at import time,
so the module needs Python 3.10+.
"""

import asyncio
import os
import sys
import threading
import types

import pytest

if sys.version_info < (3, 10):
    pytest.skip("generic_aiobmsble needs Python 3.10+ (PEP 604 annotations)", allow_module_level=True)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery", "ext", "velib_python"))


def _enrich(module_name, **attrs):
    module = sys.modules.setdefault(module_name, types.ModuleType(module_name))
    for name, value in attrs.items():
        if not hasattr(module, name):
            setattr(module, name, value)
    return module


class _StubScanner:
    @classmethod
    async def find_device_by_address(cls, address, **kwargs):
        return None


_bleak_exc = _enrich(
    "bleak.exc",
    BleakError=type("BleakError", (Exception,), {}),
    BleakDeviceNotFoundError=type("BleakDeviceNotFoundError", (Exception,), {}),
    BleakDBusError=type("BleakDBusError", (Exception,), {}),
)
_ble_device = type("BLEDevice", (), {})
_enrich(
    "bleak",
    BleakClient=type("BleakClient", (), {"__init__": lambda self, *a, **kw: None}),
    BleakScanner=_StubScanner,
    BLEDevice=_ble_device,
    exc=_bleak_exc,
)
_enrich("bleak.backends")
_enrich("bleak.backends.device", BLEDevice=_ble_device)


async def _none(*args, **kwargs):
    return None


# the full surface utils_ble imports, so this stub also satisfies
# tests/test_utils_ble.py when this module registers the stub first
_enrich(
    "bleak_retry_connector",
    get_device=_none,
    get_device_by_adapter=_none,
    close_stale_connections=_none,
    establish_connection=_none,
)


class _TempKind:
    class T:
        GENERIC = "generic"
        MOSFET = "mosfet"


_enrich("aiobmsble", BMSInfo=dict, BMSSample=dict, TempSensor=_TempKind)
_enrich(
    "utils_ble",
    Syncron_Ble=None,
    BLE_ESTABLISH_TIMEOUT=5.0,
    BLE_RELEASE_TIMEOUT=1.0,
    BLE_HOLD_POLL_INTERVAL=0.01,
    ble_hold_active=lambda address: False,
    ble_strict_pin_blocks=lambda address: False,
    ble_link_up=lambda address: None,
    adapters_in_attempt_order=lambda address, present=None: [],
    get_ble_backend=lambda name=None: None,
    restart_ble_hardware_and_bluez_driver=lambda: None,
)

from bms import generic_aiobmsble  # noqa: E402
from bms.generic_aiobmsble import Generic_AioBmsBle  # noqa: E402

ADDRESS = "AA:BB:CC:DD:EE:FF"


def _make_bat():
    bat = Generic_AioBmsBle.__new__(Generic_AioBmsBle)
    bat.address = ADDRESS
    bat._aiobmsble = None
    bat._aiobmsble_device = None
    bat._loop = None
    bat._loop_thread = None
    bat._loop_ready = None
    bat._coro_lock = threading.Lock()
    bat._run_timeout = 1
    bat._grace_timeout = 1
    bat._cancel_timeout = 1
    bat._current_future = None
    bat._last_successful_update = None
    bat._max_data_age = 5
    bat._ble_hold_logged = False
    bat.aiobmsble_data = None
    return bat


def test_an_unpinned_battery_resolves_from_the_bluez_cache_without_scanning(monkeypatch):
    device = object()
    scans = []

    async def cached(address):
        return device

    class Scanner:
        @classmethod
        async def find_device_by_address(cls, address, **kwargs):
            scans.append(kwargs)
            return None

    monkeypatch.setattr(generic_aiobmsble, "adapters_in_attempt_order", lambda address, present=None: [])
    monkeypatch.setattr(generic_aiobmsble, "get_device", cached)
    monkeypatch.setattr(generic_aiobmsble, "BleakScanner", Scanner)

    bat = _make_bat()
    assert asyncio.run(bat._find_device()) is device
    assert scans == []


def test_an_unpinned_battery_falls_back_to_a_scan_on_cache_miss(monkeypatch):
    device = object()
    scans = []

    class Scanner:
        @classmethod
        async def find_device_by_address(cls, address, **kwargs):
            scans.append((address, kwargs))
            return device

    monkeypatch.setattr(generic_aiobmsble, "adapters_in_attempt_order", lambda address, present=None: [])
    monkeypatch.setattr(generic_aiobmsble, "get_device", _none)
    monkeypatch.setattr(generic_aiobmsble, "BleakScanner", Scanner)

    bat = _make_bat()
    assert asyncio.run(bat._find_device()) is device
    assert scans == [(ADDRESS, {})]


def test_a_pinned_battery_walks_its_adapters_in_order(monkeypatch):
    """
    hci5 has lost the device (cache miss, empty scan); the battery must be
    resolved on hci6 - and every lookup must be bound to the adapter it is
    walking, never the system default.
    """
    device = object()
    cache_lookups = []
    scans = []

    async def cache(address, adapter):
        cache_lookups.append(adapter)
        return device if adapter == "hci6" else None

    class Scanner:
        @classmethod
        async def find_device_by_address(cls, address, **kwargs):
            scans.append(kwargs.get("adapter"))
            return None

    monkeypatch.setattr(generic_aiobmsble, "adapters_in_attempt_order", lambda address, present=None: ["hci5", "hci6"])
    monkeypatch.setattr(generic_aiobmsble, "get_device_by_adapter", cache)
    monkeypatch.setattr(generic_aiobmsble, "BleakScanner", Scanner)

    bat = _make_bat()
    assert asyncio.run(bat._find_device()) is device
    assert cache_lookups == ["hci5", "hci6"]
    assert scans == ["hci5"]


def test_a_battery_nowhere_to_be_found_resolves_to_none(monkeypatch):
    monkeypatch.setattr(generic_aiobmsble, "adapters_in_attempt_order", lambda address, present=None: ["hci5"])
    monkeypatch.setattr(generic_aiobmsble, "get_device_by_adapter", _none)
    monkeypatch.setattr(generic_aiobmsble, "BleakScanner", _StubScanner)

    bat = _make_bat()
    assert asyncio.run(bat._find_device()) is None


def test_a_hold_flag_stops_attempts_and_releases_the_kept_alive_link_once(monkeypatch):
    monkeypatch.setattr(generic_aiobmsble, "ble_hold_active", lambda address: True)

    bat = _make_bat()
    bms = object()
    bat._aiobmsble = bms

    scheduled = []
    bat._run_coro = lambda coro, timeout=None: (scheduled.append(coro), False)[1]

    assert bat.refresh_data() is False
    # the kept-alive link was released exactly once and the client dropped,
    # so the next unheld refresh resolves the device again
    assert len(scheduled) == 1
    assert bat._aiobmsble is None

    assert bat.refresh_data() is False
    assert len(scheduled) == 1  # not released again, not reconnected


def test_release_of_the_hold_resumes_updates(monkeypatch):
    held = {"value": True}
    monkeypatch.setattr(generic_aiobmsble, "ble_hold_active", lambda address: held["value"])

    bat = _make_bat()
    scheduled = []
    bat._run_coro = lambda coro, timeout=None: (scheduled.append(coro), False)[1]

    assert bat.refresh_data() is False
    assert scheduled == []  # nothing kept alive, nothing to release

    held["value"] = False
    assert bat.refresh_data() is False  # update ran but found no device
    assert len(scheduled) == 1  # _update_async was scheduled again
    assert bat._ble_hold_logged is False


def test_a_strict_pin_without_its_adapter_makes_no_new_connection(monkeypatch):
    monkeypatch.setattr(generic_aiobmsble, "ble_hold_active", lambda address: False)
    monkeypatch.setattr(generic_aiobmsble, "ble_strict_pin_blocks", lambda address: True)

    bat = _make_bat()
    scheduled = []
    bat._run_coro = lambda coro, timeout=None: (scheduled.append(coro), False)[1]

    assert bat.refresh_data() is False
    assert scheduled == []


def test_a_strict_pin_does_not_cut_a_link_that_is_already_up(monkeypatch):
    """The gate stops new connections; a kept-alive client is still polled."""
    monkeypatch.setattr(generic_aiobmsble, "ble_hold_active", lambda address: False)
    monkeypatch.setattr(generic_aiobmsble, "ble_strict_pin_blocks", lambda address: True)

    bat = _make_bat()
    bat._aiobmsble = object()
    scheduled = []
    bat._run_coro = lambda coro, timeout=None: (scheduled.append(coro), False)[1]

    bat.refresh_data()
    assert len(scheduled) == 1


def test_a_successful_update_reports_the_link_up(monkeypatch):
    monkeypatch.setattr(generic_aiobmsble, "ble_hold_active", lambda address: False)
    links = []
    monkeypatch.setattr(generic_aiobmsble, "ble_link_up", links.append)

    bat = _make_bat()
    bat._run_coro = lambda coro, timeout=None: True
    bat.refresh_data()  # data parsing fails on the empty sample; the link note comes first
    assert links == [ADDRESS]
