# -*- coding: utf-8 -*-
"""Tests for the Jkbms_Brn scrape loop against the BLE connection backend.

bleak and utils_ble are stubbed before import so the loop logic can be
exercised for real without a radio. The stubs are enriched rather than
replaced: other test modules in this suite register their own minimal
versions of the same modules, and whichever is collected first wins.
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
)
_enrich(
    "bleak",
    BleakClient=type("BleakClient", (), {"__init__": lambda self, *a, **kw: None}),
    BleakScanner=object,
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
)

from bms import jkbms_brn  # noqa: E402


class FakeClient:
    def __init__(self, connected_polls=0):
        # how many times the session loop sees the link up before it drops
        self.remaining_polls = connected_polls
        self.notify_chars = []

    @property
    def is_connected(self):
        if self.remaining_polls > 0:
            self.remaining_polls -= 1
            return True
        return False

    async def start_notify(self, char, callback):
        self.notify_chars.append(char)

    async def write_gatt_char(self, char, data, response=False):
        pass


class RecordingBackend:
    """Backend double: establish() pops scripted results, raising exceptions."""

    def __init__(self, script):
        self.script = list(script)
        self.create_calls = 0
        self.establish_calls = 0
        self.released = []

    def create_client(self, address, disconnected_callback):
        self.create_calls += 1
        return None  # like BleakRetryBackend, the client comes from establish()

    async def establish(self, client, address, notify_char, notify_callback):
        self.establish_calls += 1
        result = self.script.pop(0) if self.script else RuntimeError("script exhausted")
        if isinstance(result, Exception):
            raise result
        return result

    async def release(self, client):
        self.released.append(client)


def _make_jk(backend, monkeypatch):
    monkeypatch.setattr(jkbms_brn, "get_ble_backend", lambda name=None: backend)
    monkeypatch.setattr(jkbms_brn, "ble_hold_active", lambda address: False)
    monkeypatch.setattr(jkbms_brn, "RECONNECT_BACKOFF_S", [0])
    monkeypatch.setattr(jkbms_brn, "ble_strict_pin_blocks", lambda address: False)
    monkeypatch.setattr(jkbms_brn, "ble_link_up", lambda address: None)
    jk = jkbms_brn.Jkbms_Brn("C8:47:8C:00:00:00")
    jk.main_thread = threading.current_thread()
    return jk


def test_a_failed_connect_no_longer_kills_the_loop(monkeypatch):
    """
    The old loop set run=False on every error, so 'autoreconnect' never made
    a second attempt. The loop must retry in place, and only after the full
    failure streak hand the session back to monitor_scraping.
    """
    backend = RecordingBackend([RuntimeError("radio busy")] * 10)
    monkeypatch.setattr(jkbms_brn, "MAX_CONSECUTIVE_FAILURES", 3)
    jk = _make_jk(backend, monkeypatch)

    asyncio.run(jk.asy_connect_and_scrape())

    assert backend.establish_calls == 3
    # nothing ever connected, so nothing may be released
    assert backend.released == []


def test_the_failure_streak_survives_stop_scraping_semantics(monkeypatch):
    """run=False must still end the loop immediately: deliberate shutdown."""
    backend = RecordingBackend([RuntimeError("radio busy")] * 10)
    monkeypatch.setattr(jkbms_brn, "MAX_CONSECUTIVE_FAILURES", 100)
    jk = _make_jk(backend, monkeypatch)

    async def scrape_then_stop():
        task = asyncio.ensure_future(jk.asy_connect_and_scrape())
        await asyncio.sleep(0.05)
        jk.run = False
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scrape_then_stop())
    assert backend.establish_calls >= 2  # it was retrying, not dead


def test_the_loop_walks_create_establish_release(monkeypatch):
    """A connected session must be released through the backend on shutdown."""
    client = FakeClient(connected_polls=1000)
    backend = RecordingBackend([client])
    monkeypatch.setattr(jkbms_brn, "MAX_CONSECUTIVE_FAILURES", 1)
    jk = _make_jk(backend, monkeypatch)

    async def _noop_request(rtype, c):
        return None

    jk.request_bt = _noop_request

    async def scrape_then_stop():
        task = asyncio.ensure_future(jk.asy_connect_and_scrape())
        await asyncio.sleep(0.05)
        jk.run = False
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scrape_then_stop())

    assert backend.create_calls == 1
    assert backend.establish_calls == 1
    assert backend.released == [client]
    # the driver, not the backend, subscribes: it owns the UUID failover
    assert client.notify_chars == [jkbms_brn.CHAR_HANDLE]


def test_a_hold_flag_pauses_attempts_without_ending_the_loop(monkeypatch):
    backend = RecordingBackend([])
    jk = _make_jk(backend, monkeypatch)
    monkeypatch.setattr(jkbms_brn, "ble_hold_active", lambda address: True)
    monkeypatch.setattr(jkbms_brn, "BLE_HOLD_POLL_INTERVAL", 0.01)

    async def scrape_then_stop():
        task = asyncio.ensure_future(jk.asy_connect_and_scrape())
        await asyncio.sleep(0.05)
        jk.run = False
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scrape_then_stop())
    assert backend.create_calls == 0
    assert backend.establish_calls == 0


def test_a_strict_pin_without_its_adapter_makes_no_attempt(monkeypatch):
    """BLUETOOTH_ADAPTER_PIN_STRICT: waiting beats connecting over the wrong radio."""
    backend = RecordingBackend([])
    jk = _make_jk(backend, monkeypatch)
    monkeypatch.setattr(jkbms_brn, "ble_strict_pin_blocks", lambda address: True)
    monkeypatch.setattr(jkbms_brn, "BLE_HOLD_POLL_INTERVAL", 0.01)

    async def scrape_then_stop():
        task = asyncio.ensure_future(jk.asy_connect_and_scrape())
        await asyncio.sleep(0.05)
        jk.run = False
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scrape_then_stop())
    assert backend.create_calls == 0
    assert backend.establish_calls == 0


def test_a_connected_session_reports_the_link_up(monkeypatch):
    """The pin warning is re-armed per connection, so the next lost card is said again."""
    client = FakeClient(connected_polls=1000)
    backend = RecordingBackend([client])
    monkeypatch.setattr(jkbms_brn, "MAX_CONSECUTIVE_FAILURES", 1)
    jk = _make_jk(backend, monkeypatch)
    links = []
    monkeypatch.setattr(jkbms_brn, "ble_link_up", links.append)

    async def _noop_request(rtype, c):
        return None

    jk.request_bt = _noop_request

    async def scrape_then_stop():
        task = asyncio.ensure_future(jk.asy_connect_and_scrape())
        await asyncio.sleep(0.05)
        jk.run = False
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scrape_then_stop())
    assert links == ["C8:47:8C:00:00:00"]
