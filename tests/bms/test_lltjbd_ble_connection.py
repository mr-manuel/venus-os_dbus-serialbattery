# -*- coding: utf-8 -*-
"""Tests for the LltJbd_Ble reconnect loop against the BLE connection backend.

bleak and utils_ble are stubbed before import so the loop logic can be
exercised for real without a radio. Instances are built with __new__: the
real __init__ probes hciattach process state, which only exists on Venus OS.
"""

import asyncio
import os
import sys
import threading
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery"))


def _enrich(module_name, **attrs):
    module = sys.modules.setdefault(module_name, types.ModuleType(module_name))
    for name, value in attrs.items():
        if not hasattr(module, name):
            setattr(module, name, value)
    return module


_bleak_exc = _enrich(
    "bleak.exc",
    BleakError=type("BleakError", (Exception,), {}),
    BleakDeviceNotFoundError=type("BleakDeviceNotFoundError", (Exception,), {}),
    BleakDBusError=type("BleakDBusError", (Exception,), {}),
)
_enrich(
    "bleak",
    BleakClient=type("BleakClient", (), {"__init__": lambda self, *a, **kw: None}),
    BleakScanner=object,
    BLEDevice=type("BLEDevice", (), {}),
    exc=_bleak_exc,
)

_async_noop = None


async def _return_none(*args, **kwargs):
    return None


_enrich(
    "utils_ble",
    Syncron_Ble=None,
    BLE_ESTABLISH_TIMEOUT=5.0,
    BLE_RELEASE_TIMEOUT=1.0,
    BLE_HOLD_POLL_INTERVAL=0.01,
    ble_hold_active=lambda address: False,
    get_ble_backend=lambda name=None: None,
    restart_ble_hardware_and_bluez_driver=lambda: None,
)

from bms import lltjbd_ble  # noqa: E402
from bms.lltjbd_ble import LltJbd_Ble  # noqa: E402


class FakeClient:
    def __init__(self):
        self.connected = True

    @property
    def is_connected(self):
        return self.connected


class RecordingBackend:
    def __init__(self, script):
        self.script = list(script)
        self.create_calls = 0
        self.establish_calls = 0
        self.released = []

    def create_client(self, address, disconnected_callback):
        self.create_calls += 1
        return None

    async def establish(self, client, address, notify_char, notify_callback):
        self.establish_calls += 1
        result = self.script.pop(0) if self.script else RuntimeError("script exhausted")
        if isinstance(result, Exception):
            raise result
        return result

    async def release(self, client):
        self.released.append(client)


class FakeScanner:
    """BleakScanner stand-in whose find_device_by_address pops a script."""

    script = []

    @classmethod
    async def find_device_by_address(cls, address, **kwargs):
        return cls.script.pop(0) if cls.script else None


def _make_bat(backend, monkeypatch, device=object()):
    monkeypatch.setattr(lltjbd_ble, "BleakScanner", FakeScanner)
    FakeScanner.script = [device] * 100
    bat = LltJbd_Ble.__new__(LltJbd_Ble)
    bat.address = "AA:BB:CC:DD:EE:FF"
    bat.main_thread = threading.current_thread()
    bat.run = True
    bat.backend = backend
    bat.ready_event = None  # created inside the running loop by _run
    bat.device = None
    bat.bt_client = None
    bat.bt_loop = None
    bat.response_queue = None
    bat.notify_active = False
    bat.response_buffer = bytearray()
    bat.response_future = None
    bat.hci_uart_ok = True
    return bat


def _run(bat, stop_after=None):
    """Run one bt_main_loop pass; optionally stop the session after a delay."""

    async def runner():
        bat.ready_event = asyncio.Event()  # py3.9: must exist inside the loop
        if stop_after is None:
            await bat.bt_main_loop()
            return
        task = asyncio.ensure_future(bat.bt_main_loop())
        await asyncio.sleep(stop_after)
        bat.run = False
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(runner())


def test_an_empty_scan_no_longer_kills_the_reconnect_thread(monkeypatch):
    """
    bt_main_loop used to set run=False when the device was not found - one
    battery reboot and the thread was dead until a driver restart.
    """
    backend = RecordingBackend([])
    bat = _make_bat(backend, monkeypatch)
    FakeScanner.script = []  # scan comes up empty

    _run(bat)

    assert bat.run is True
    assert backend.establish_calls == 0


def test_a_failed_establish_no_longer_kills_the_reconnect_thread(monkeypatch):
    backend = RecordingBackend([RuntimeError("le-connection-abort-by-local")])
    bat = _make_bat(backend, monkeypatch)

    _run(bat)

    assert bat.run is True
    assert backend.establish_calls == 1
    # nothing connected, nothing to release
    assert backend.released == []


def test_a_connected_session_walks_create_establish_release(monkeypatch):
    client = FakeClient()
    backend = RecordingBackend([client])
    bat = _make_bat(backend, monkeypatch)

    _run(bat, stop_after=0.3)

    assert backend.create_calls == 1
    assert backend.establish_calls == 1
    assert backend.released == [client]
    assert bat.bt_client is client
    # session state was reset for the lazy notify in send_command
    assert bat.notify_active is False


def test_a_hold_flag_pauses_the_background_loop(monkeypatch):
    backend = RecordingBackend([])
    bat = _make_bat(backend, monkeypatch)
    monkeypatch.setattr(lltjbd_ble, "ble_hold_active", lambda address: True)
    monkeypatch.setattr(lltjbd_ble, "BLE_HOLD_POLL_INTERVAL", 0.01)

    attempts = []

    async def record_attempt():
        attempts.append(1)

    bat.bt_main_loop = record_attempt

    thread = threading.Thread(target=bat.background_loop, daemon=True)
    thread.start()
    import time

    time.sleep(0.1)
    bat.run = False
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert attempts == []
