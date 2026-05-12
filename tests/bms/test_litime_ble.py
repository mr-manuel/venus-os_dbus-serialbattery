# -*- coding: utf-8 -*-
"""Tests for LiTime BLE BMS parse_status cell handling."""

import os
import struct
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery", "ext", "velib_python"))

sys.modules.setdefault("utils_ble", types.SimpleNamespace(Syncron_Ble=None))

from battery import History  # noqa: E402
from bms.litime_ble import LiTime_Ble  # noqa: E402


def _build_status_payload(cell_voltage_mv=3320, nr_cells=4):
    """Build a 104-byte payload mimicking the LiTime BLE status response."""
    data = bytearray(104)
    struct.pack_into("II", data, 8, cell_voltage_mv * nr_cells, cell_voltage_mv * nr_cells)
    for i in range(nr_cells):
        struct.pack_into("H", data, 16 + i * 2, cell_voltage_mv)
    struct.pack_into("ihhhHHHHH", data, 48, 0, 250, 250, 0, 0, 0, 5000, 32000, 0)
    struct.pack_into("IIIIIHHIII", data, 68, 0, 0, 0, 0, 0, 0, 75, 100, 0, 0)
    return bytes(data)


def _make_bms():
    bms = LiTime_Ble.__new__(LiTime_Ble)
    bms.cells = []
    bms.last_remian_ah = 0
    bms.last_remian_ah_time = 0
    bms.last_remian_ah_initiation = 0
    bms.current_based_on_remaning = 0
    bms.last_few_currents = []
    bms.history = History()
    return bms


def test_parse_status_does_not_grow_cells_on_repeated_calls():
    """Regression for issue #440."""
    bms = _make_bms()
    payload = _build_status_payload(cell_voltage_mv=3320, nr_cells=4)
    for _ in range(10):
        bms.parse_status(payload)
    assert bms.cell_count == 4
    assert len(bms.cells) == 4
