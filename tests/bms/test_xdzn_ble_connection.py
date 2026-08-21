# -*- coding: utf-8 -*-
"""Tests for the Xdzn_Ble connect/disconnect path against the BLE backend."""

import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery", "ext", "velib_python"))


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

from bms import xdzn_ble  # noqa: E402
from bms.xdzn_ble import Xdzn_Ble  # noqa: E402


class FakeClient:
    def __init__(self):
        self.connected = True
        self.writes = []
        self.stopped_notify = []

    @property
    def is_connected(self):
        return self.connected

    async def write_gatt_char(self, char, data, response=False):
        self.writes.append((char, bytes(data)))

    async def stop_notify(self, char):
        self.stopped_notify.append(char)


class RecordingBackend:
    def __init__(self, script):
        self.script = list(script)
        self.create_calls = 0
        self.establish_notify_chars = []
        self.released = []

    def create_client(self, address, disconnected_callback):
        self.create_calls += 1
        return None

    async def establish(self, client, address, notify_char, notify_callback):
        self.establish_notify_chars.append(notify_char)
        result = self.script.pop(0) if self.script else RuntimeError("script exhausted")
        if isinstance(result, Exception):
            raise result
        return result

    async def release(self, client):
        self.released.append(client)


def _make_bat(backend, monkeypatch):
    monkeypatch.setattr(xdzn_ble, "ble_hold_active", lambda address: False)
    bat = Xdzn_Ble.__new__(Xdzn_Ble)
    bat.address = "AA:BB:CC:DD:EE:FF"
    bat.backend = backend
    bat._client = None
    bat._buf = bytearray()
    bat._expected = None
    bat._loop = None
    return bat


def test_connect_establishes_with_the_fixed_notify_char_and_authenticates(monkeypatch):
    client = FakeClient()
    backend = RecordingBackend([client])
    bat = _make_bat(backend, monkeypatch)

    async def run():
        bat._event = asyncio.Event()
        return await bat._connect()

    assert asyncio.run(run()) is True
    assert backend.create_calls == 1
    # the notify characteristic is fixed, so the backend subscribes it
    assert backend.establish_notify_chars == [xdzn_ble.NOTIFY_UUID]
    assert bat._client is client
    # the auth handshake stays in the driver, after establish
    assert client.writes == [(xdzn_ble.AUTH_UUID, xdzn_ble.AUTH_KEY)]


def test_a_failed_establish_leaves_no_client_for_the_next_poll(monkeypatch):
    backend = RecordingBackend([RuntimeError("device fell off the bus")])
    bat = _make_bat(backend, monkeypatch)

    async def run():
        bat._event = asyncio.Event()
        return await bat._connect()

    assert asyncio.run(run()) is False
    assert bat._client is None
    assert backend.released == []


def test_a_hold_flag_prevents_any_attempt(monkeypatch):
    backend = RecordingBackend([])
    bat = _make_bat(backend, monkeypatch)
    monkeypatch.setattr(xdzn_ble, "ble_hold_active", lambda address: True)

    async def run():
        bat._event = asyncio.Event()
        return await bat._connect()

    assert asyncio.run(run()) is False
    assert backend.create_calls == 0
    assert backend.establish_notify_chars == []


def test_disconnect_releases_through_the_backend(monkeypatch):
    client = FakeClient()
    backend = RecordingBackend([])
    bat = _make_bat(backend, monkeypatch)
    bat._client = client

    asyncio.run(bat._disconnect())

    assert client.stopped_notify == [xdzn_ble.NOTIFY_UUID]
    assert backend.released == [client]
    assert bat._client is None
