# -*- coding: utf-8 -*-
"""Tests for the bluetoothctl diagnostics of the JKBMS BLE BMS.

get_bluetoothctl_info() replaced os.popen("bluetoothctl info <addr> | grep -i -E ..."),
so it must pick the same lines the grep did, must not start a shell, and must never
raise: it only feeds a log line on the path that handles a stalled connection.
"""

import os
import subprocess
import sys
import types
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery", "ext", "velib_python"))

# Other test modules stub these too, and whichever is collected first wins setdefault().
# Complete whatever is registered instead, so every module gets the attributes it imports.
_bleak_exc = sys.modules.setdefault("bleak.exc", types.ModuleType("bleak.exc"))
for _name in ("BleakError", "BleakDBusError"):
    if not hasattr(_bleak_exc, _name):
        setattr(_bleak_exc, _name, type(_name, (Exception,), {}))

_bleak = sys.modules.setdefault("bleak", types.ModuleType("bleak"))
for _name, _value in (("BleakClient", MagicMock), ("BleakScanner", MagicMock), ("BLEDevice", MagicMock), ("exc", _bleak_exc)):
    if not hasattr(_bleak, _name):
        setattr(_bleak, _name, _value)

_utils_ble = sys.modules.setdefault("utils_ble", types.SimpleNamespace())
for _name, _value in (("Syncron_Ble", None), ("restart_ble_hardware_and_bluez_driver", lambda: None)):
    if not hasattr(_utils_ble, _name):
        setattr(_utils_ble, _name, _value)

from bms import jkbms_ble  # noqa: E402

ADDRESS = "C8:47:8C:E4:9F:2A"

# bluetoothctl info output, including the lines the old grep dropped
BLUETOOTHCTL_OUTPUT = """Device C8:47:8C:E4:9F:2A (public)
\tName: JK-B2A24S
\tAlias: JK-B2A24S
\tClass: 0x00000000
\tIcon: input-keyboard
\tPaired: yes
\tBonded: yes
\tTrusted: yes
\tBlocked: no
\tConnected: yes
\tLegacyPairing: no
\tUUID: Vendor specific           (0000ffe0-0000-1000-8000-00805f9b34fb)
\tManufacturerData Key: 0x0000
\tManufacturerData Value:
  01 02 03 04                                      ....
\tRSSI: -67
\tTxPower: 4
"""

# what `grep -i -E "device|name|alias|pair|trusted|blocked|connected|rssi|power"` printed
# for that output, captured from the real grep, trailing newline removed
GREP_OUTPUT = """Device C8:47:8C:E4:9F:2A (public)
\tName: JK-B2A24S
\tAlias: JK-B2A24S
\tPaired: yes
\tTrusted: yes
\tBlocked: no
\tConnected: yes
\tLegacyPairing: no
\tRSSI: -67
\tTxPower: 4"""


def _completed(stdout):
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


@pytest.fixture
def run_calls(monkeypatch):
    """Record every subprocess.run() call and answer it with the sample output."""
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return _completed(BLUETOOTHCTL_OUTPUT)

    monkeypatch.setattr(jkbms_ble.subprocess, "run", fake_run)
    return calls


def test_runs_bluetoothctl_without_a_shell(run_calls):
    """An argument list and no shell=True: no shell is forked from the driver process."""
    jkbms_ble.get_bluetoothctl_info(ADDRESS)

    ((args, kwargs),) = run_calls
    assert args[0] == ["bluetoothctl", "info", ADDRESS]
    assert not kwargs.get("shell", False)


def test_bounds_how_long_bluetoothctl_may_take(run_calls):
    """os.popen().read() waited indefinitely; a hung bluetoothctl must not stall the poll."""
    jkbms_ble.get_bluetoothctl_info(ADDRESS)

    ((_, kwargs),) = run_calls
    assert kwargs.get("timeout") is not None


def test_keeps_the_same_lines_the_grep_kept(run_calls):
    """The replaced shell pipeline filtered with grep; the log line must not change."""
    assert jkbms_ble.get_bluetoothctl_info(ADDRESS) == GREP_OUTPUT


def test_drops_the_lines_the_grep_dropped(run_calls):
    result = jkbms_ble.get_bluetoothctl_info(ADDRESS)

    for dropped in ("Class:", "Icon:", "UUID:", "ManufacturerData", "01 02 03 04"):
        assert dropped not in result


def test_empty_output_gives_an_empty_result(monkeypatch):
    monkeypatch.setattr(jkbms_ble.subprocess, "run", lambda *args, **kwargs: _completed(""))

    assert jkbms_ble.get_bluetoothctl_info(ADDRESS) == ""


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError(2, "No such file or directory", "bluetoothctl"),
        subprocess.TimeoutExpired(cmd=["bluetoothctl", "info", ADDRESS], timeout=10),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
    ],
    ids=["not installed", "timed out", "undecodable output"],
)
def test_failure_is_reported_instead_of_raised(monkeypatch, error):
    """This only feeds a log line, on the path that is already handling a stalled connection."""

    def failing_run(*args, **kwargs):
        raise error

    monkeypatch.setattr(jkbms_ble.subprocess, "run", failing_run)

    result = jkbms_ble.get_bluetoothctl_info(ADDRESS)

    assert ADDRESS in result
    assert "could not be run" in result
