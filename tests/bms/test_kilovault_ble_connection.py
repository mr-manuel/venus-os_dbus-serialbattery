# -*- coding: utf-8 -*-
"""Tests for the Kilovault_Ble connection thread against the BLE backend."""

import asyncio
import os
import sys
import threading
import time
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
    ble_strict_pin_blocks=lambda address: False,
    ble_link_up=lambda address: None,
    get_ble_backend=lambda name=None: None,
    restart_ble_hardware_and_bluez_driver=lambda: None,
)

from bms import kilovault_ble  # noqa: E402
from bms.kilovault_ble import Kilovault_Ble  # noqa: E402


class FakeCharacteristic:
    pass


class FakeService:
    def get_characteristic(self, uuid):
        return FakeCharacteristic()


class FakeServices:
    def get_service(self, uuid):
        return FakeService()


class FakeClient:
    def __init__(self):
        self.connected = True
        self.notify_started = []
        self.services = FakeServices()

    @property
    def is_connected(self):
        return self.connected

    async def read_gatt_char(self, uuid):
        return b"KV1234 "

    async def start_notify(self, char, callback):
        self.notify_started.append(char)


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


def _make_bat(backend, monkeypatch):
    monkeypatch.setattr(kilovault_ble, "atexit", types.SimpleNamespace(register=lambda *a, **kw: None))
    bat = Kilovault_Ble.__new__(Kilovault_Ble)
    bat.address = "AA:BB:CC:DD:EE:FF"
    bat.main_thread = threading.current_thread()
    bat.run = True
    bat.backend = backend
    bat.client = None
    bat.notifyService = None
    bat._device_name = None
    bat.status_buffer = bytearray()
    bat.lastUpdateTime = 0  # stale: the session loop exits immediately
    return bat


def test_a_session_walks_create_establish_release(monkeypatch):
    client = FakeClient()
    backend = RecordingBackend([client])
    bat = _make_bat(backend, monkeypatch)

    assert asyncio.run(bat.connection_thread()) is True

    assert backend.create_calls == 1
    assert backend.establish_calls == 1
    # the release in finally replaces the old context manager exit
    assert backend.released == [client]
    assert bat._device_name == "KV1234"
    assert len(client.notify_started) == 1


def test_a_failed_establish_reports_failure_and_releases_nothing(monkeypatch):
    backend = RecordingBackend([RuntimeError("connection slot unavailable")])
    bat = _make_bat(backend, monkeypatch)

    assert asyncio.run(bat.connection_thread()) is False

    # the reconnect loop's while condition: a failure must not stop it
    assert bat.run is True
    assert backend.released == []


def test_a_hold_flag_pauses_the_background_loop(monkeypatch):
    backend = RecordingBackend([])
    bat = _make_bat(backend, monkeypatch)
    monkeypatch.setattr(kilovault_ble, "ble_hold_active", lambda address: True)
    monkeypatch.setattr(kilovault_ble, "BLE_HOLD_POLL_INTERVAL", 0.01)

    attempts = []

    async def record_attempt():
        attempts.append(1)

    bat.connection_thread = record_attempt

    thread = threading.Thread(target=bat.background_loop, daemon=True)
    thread.start()
    time.sleep(0.1)
    bat.run = False
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert attempts == []


def test_a_strict_pin_without_its_adapter_pauses_the_background_loop(monkeypatch):
    backend = RecordingBackend([])
    bat = _make_bat(backend, monkeypatch)
    monkeypatch.setattr(kilovault_ble, "ble_hold_active", lambda address: False)
    monkeypatch.setattr(kilovault_ble, "ble_strict_pin_blocks", lambda address: True)
    monkeypatch.setattr(kilovault_ble, "BLE_HOLD_POLL_INTERVAL", 0.01)

    attempts = []

    async def record_attempt():
        attempts.append(1)

    bat.connection_thread = record_attempt

    thread = threading.Thread(target=bat.background_loop, daemon=True)
    thread.start()
    time.sleep(0.1)
    bat.run = False
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert attempts == []
