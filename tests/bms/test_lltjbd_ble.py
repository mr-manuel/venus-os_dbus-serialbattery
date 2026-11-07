# -*- coding: utf-8 -*-
"""Tests for LLT/JBD BLE connection worker cleanup."""

import asyncio
import os
import sys
import types
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery"))

sys.modules.setdefault(
    "bleak",
    types.SimpleNamespace(BleakClient=MagicMock, BleakScanner=MagicMock, BLEDevice=MagicMock),
)
sys.modules.setdefault("bleak.exc", types.SimpleNamespace(BleakDBusError=Exception))
utils_ble = sys.modules.setdefault("utils_ble", types.SimpleNamespace())
utils_ble.restart_ble_hardware_and_bluez_driver = MagicMock()

from bms import lltjbd_ble  # noqa: E402
from bms.lltjbd_ble import LltJbd_Ble  # noqa: E402


class _FakeThread:
    def __init__(self, alive):
        self.alive = alive
        self.started = False
        self.join_timeout = None

    def is_alive(self):
        return self.alive

    def start(self):
        self.started = True

    def join(self, timeout=None):
        self.join_timeout = timeout


def _make_bms(thread):
    bms = LltJbd_Ble.__new__(LltJbd_Ble)
    bms.hci_uart_ok = True
    bms.bt_thread = thread
    bms.run = True
    return bms


def test_shutdown_callback_bounds_worker_join(monkeypatch):
    class _ReadyEvent:
        async def wait(self):
            return True

    registered = {}
    thread = _FakeThread(alive=False)
    bms = _make_bms(thread)

    monkeypatch.setattr(lltjbd_ble.asyncio, "Event", _ReadyEvent)

    def capture_registration(callback, callback_thread):
        registered["callback"] = callback
        registered["thread"] = callback_thread

    monkeypatch.setattr(lltjbd_ble.atexit, "register", capture_registration)

    assert asyncio.run(bms.async_test_connection()) is True
    assert thread.started is True

    registered["callback"](registered["thread"])

    assert bms.run is False
    assert thread.join_timeout == 5


def test_connection_timeout_stops_worker(monkeypatch):
    timeout_seconds = []
    timeout_error = asyncio.TimeoutError
    thread = _FakeThread(alive=True)
    bms = _make_bms(thread)

    async def raise_timeout(awaitable, timeout):
        timeout_seconds.append(timeout)
        awaitable.close()
        raise timeout_error

    monkeypatch.setattr(lltjbd_ble.asyncio, "wait_for", raise_timeout)

    assert asyncio.run(bms.async_test_connection()) is False
    assert timeout_seconds == [5]
    assert bms.run is False
