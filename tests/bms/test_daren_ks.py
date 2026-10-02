# -*- coding: utf-8 -*-
"""Regression tests for the Daren485 and KS48100 protocol changes."""

import os
import sys

import pytest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery"),
)

from battery import Cell  # noqa: E402
from bms.daren_485 import Daren485  # noqa: E402
from bms.ks48100 import KS48100  # noqa: E402
import bms.daren_485 as daren_module  # noqa: E402
import bms.ks48100 as ks_module  # noqa: E402


def _u8(value):
    return f"{value & 0xFF:02X}"


def _u16(value):
    return f"{value & 0xFFFF:04X}"


def _i16(value):
    return _u16(value)


def build_realtime_payload(
    cell_count=16,
    temperature_count=4,
    balance_low=0,
    balance_high=0,
    warning_status=0,
):
    parts = [
        _u8(1),
        _u16(7550),
        _u16(5260),
        _u8(cell_count),
    ]
    parts.extend(_u16(3300 + i) for i in range(cell_count))
    parts.extend(
        [
            _i16(250),
            _i16(260),
            _i16(270),
            _u8(temperature_count),
        ]
    )
    parts.extend(_i16(280 + (i * 10)) for i in range(temperature_count))
    parts.extend(
        [
            _i16(-123),
            _u16(12),
            _u16(99),
            _u8(0),
            _u16(10000),
            _u16(7500),
            _u16(123),
            _u16(0),
            _u16(0),
            _u16(0),
            _u16(warning_status),
            _u16(3),
            _u16(0),
            _u16(0),
            _u16(0),
            _u16(0),
            _u16(balance_low),
            _u16(balance_high),
        ]
    )
    return "".join(parts)


class FakeSerial:
    port = "/dev/mock"

    def __init__(self):
        self.written = []

    def flushOutput(self):
        pass

    def flushInput(self):
        pass

    def write(self, value):
        self.written.append(value)


def _frame(payload):
    return ("0" * 13) + payload + ("0" * 5)


def _make_daren(cell_count=16):
    bms = Daren485("/dev/mock", 9600, b"\x01")
    bms.cell_count = cell_count
    bms.cells = [Cell(False) for _ in range(cell_count)]
    return bms


def _make_ks(cell_count=16):
    bms = KS48100("/dev/mock", 9600, b"\x01")
    bms.cell_count = cell_count
    bms.cells = [Cell(False) for _ in range(cell_count)]
    return bms


@pytest.fixture(autouse=True)
def no_protocol_sleep(monkeypatch):
    monkeypatch.setattr(daren_module, "sleep", lambda _seconds: None)
    monkeypatch.setattr(ks_module, "sleep", lambda _seconds: None)


def test_daren_realtime_balance_mask_and_values(monkeypatch):
    bms = _make_daren()
    payload = build_realtime_payload(balance_low=0x0005)
    monkeypatch.setattr(bms, "read_response", lambda _ser: _frame(payload))

    assert bms.get_realtime_data(FakeSerial()) is True
    assert bms.cell_count == 16
    assert len(bms.cells) == 16
    assert bms.cells[0].balance is True
    assert bms.cells[1].balance is False
    assert bms.cells[2].balance is True
    assert bms.balance_fet is True
    assert bms.soc == 75.5
    assert bms.voltage == 52.6
    assert bms.current == -1.23
    assert bms.soh == 99
    assert bms.capacity == 100
    assert bms.capacity_remain == 75


def test_daren_rejects_runtime_cell_count_change(monkeypatch):
    bms = _make_daren(cell_count=16)
    payload = build_realtime_payload(cell_count=15)
    monkeypatch.setattr(bms, "read_response", lambda _ser: _frame(payload))

    assert bms.get_realtime_data(FakeSerial()) is False
    assert bms.cell_count == 16
    assert len(bms.cells) == 16


def test_ks_realtime_balance_mask_and_values():
    bms = _make_ks()
    payload = build_realtime_payload(balance_low=0x0005)

    status = bms._parse_realtime_payload(payload)

    assert status == (0, 0, 0, 0, 3)
    assert bms.cells[0].balance is True
    assert bms.cells[1].balance is False
    assert bms.cells[2].balance is True
    assert bms.balance_fet is True
    assert bms.soc == 75.5
    assert bms.voltage == 52.6
    assert bms.current == -1.23
    assert bms.soh == 99
    assert bms.capacity == 100
    assert bms.capacity_remain == 75


def test_ks_rejects_runtime_cell_count_change():
    bms = _make_ks(cell_count=16)
    payload = build_realtime_payload(cell_count=15)

    with pytest.raises(ValueError, match="differs from configured cell count"):
        bms._parse_realtime_payload(payload)

    assert bms.cell_count == 16
    assert len(bms.cells) == 16


def test_ks_internal_failure_uses_upper_warning_bits(monkeypatch):
    bms = _make_ks()
    payload = build_realtime_payload(warning_status=(1 << 9))
    monkeypatch.setattr(bms, "read_response", lambda _ser: _frame(payload))

    assert bms.get_realtime_data(FakeSerial()) is True
    assert bms.protection.internal_failure == 2


def test_ks_low_battery_warning_is_not_internal_failure(monkeypatch):
    bms = _make_ks()
    payload = build_realtime_payload(warning_status=(1 << 7))
    monkeypatch.setattr(bms, "read_response", lambda _ser: _frame(payload))

    assert bms.get_realtime_data(FakeSerial()) is True
    assert bms.protection.internal_failure == 0


def test_ks_get_cap_params_uses_framework_capacity_remain(monkeypatch):
    bms = _make_ks()
    payload = _u16(7550) + _u16(10000) + _u16(10000) + "00000064" + "00000032" + _u16(1234) + _u16(567)
    response = ("0" * 25) + payload + ("0" * 5)
    monkeypatch.setattr(bms, "read_response", lambda _ser: response)

    assert bms.get_cap_params(FakeSerial()) is True
    assert bms.capacity_remain == 75
    assert not hasattr(bms, "capacity_remaining")
