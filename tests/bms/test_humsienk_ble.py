# -*- coding: utf-8 -*-
"""Tests for the HumsiENK BLE protocol logic.

Everything here runs against the frame codec and the response parsers, which
is all of the driver that does not need a radio: framing and reassembly,
resynchronisation after corrupt input, the register offsets of each response,
the alarm bit map, and the request budget that bounds startup.

utils_ble imports bleak, which is not installed on the machines this suite
runs on, so a minimal stub stands in for it while bms.humsienk_ble is
imported. The stub is removed again afterwards so no other test module
inherits it.
"""

import os
import sys
import time
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery", "ext", "velib_python"))

_saved_utils_ble = sys.modules.get("utils_ble")
sys.modules["utils_ble"] = types.SimpleNamespace(Syncron_Ble=object, BLE_ESTABLISH_TIMEOUT=300.0, BLE_RELEASE_TIMEOUT=30.0)
try:
    import utils  # noqa: E402
    from bms import humsienk_ble  # noqa: E402
    from bms.humsienk_ble import HumsiENK_Ble  # noqa: E402
finally:
    if _saved_utils_ble is None:
        del sys.modules["utils_ble"]
    else:
        sys.modules["utils_ble"] = _saved_utils_ble


# ---------------------------------------------------------------- test doubles


class FakeBleHandle:
    """Stands in for HumsiENK_Syncron_Ble: a notification queue and a writer."""

    def __init__(self, responses=None, chunk_size=None):
        """
        :param responses: command code -> response frame, answered on send_data
        :param chunk_size: split every queued frame into chunks of this size
        """
        self.connected = True
        self.responses = responses or {}
        self.chunk_size = chunk_size
        self.queue = []
        self.sent = []
        self.watchdog_feeds = 0

    def push(self, data):
        """Queue raw bytes as they would arrive from the notification callback."""
        if self.chunk_size:
            for offset in range(0, len(data), self.chunk_size):
                self.queue.append(data[offset : offset + self.chunk_size])
        else:
            self.queue.append(data)

    def get_notification(self, timeout=0.0):
        return self.queue.pop(0) if self.queue else None

    def feed_watchdog(self):
        self.watchdog_feeds += 1

    def send_data(self, data):
        self.sent.append(data)
        if data[1] in self.responses:
            self.push(self.responses[data[1]])


def make_bms(handle=None):
    bms = HumsiENK_Ble("ble_aabbccddeeff", 9600, "AA:BB:CC:DD:EE:FF")
    bms.ble_handle = handle if handle is not None else FakeBleHandle()
    return bms


def frame(command, data=b""):
    """Build a wire frame the way the BMS does, independently of the driver."""
    body = bytes([command, len(data)]) + bytes(data)
    checksum = sum(body) & 0xFFFF
    return bytes([0xAA]) + body + bytes([checksum & 0xFF, checksum >> 8])


def battery_info_payload(
    voltage_mv=13260,
    current_ma=-4500,
    soc=87,
    soh=99,
    remaining_mah=91000,
    total_mah=100000,
    cycles=42,
    temperatures=(21, 22, 23, 24, 31, 19),
):
    payload = bytearray()
    payload += voltage_mv.to_bytes(4, "little")
    payload += current_ma.to_bytes(4, "little", signed=True)
    payload += bytes([soc, soh])
    payload += remaining_mah.to_bytes(4, "little")
    payload += total_mah.to_bytes(4, "little")
    payload += cycles.to_bytes(2, "little")
    payload += bytes((value + 256) if value < 0 else value for value in temperatures)
    return bytes(payload)


def cell_payload(millivolts):
    payload = bytearray()
    for millivolt in millivolts:
        payload += millivolt.to_bytes(2, "little")
    return bytes(payload)


def status_payload(status_bits=0, balancing=0, disconnected=0):
    payload = bytearray()
    payload += (3).to_bytes(2, "little")  # runtime days
    payload += bytes([4, 5])  # runtime hours, minutes
    payload += status_bits.to_bytes(4, "little")
    payload += balancing.to_bytes(3, "little")
    payload += disconnected.to_bytes(3, "little")
    return bytes(payload)


def config_payload(
    cell_count=4,
    capacity_centi_ah=10000,
    cell_ovp_mv=3650,
    cell_uvp_mv=2500,
    charge_ocp_deci_a=1000,
    discharge_ocp_deci_a=1500,
):
    values = [0] * 22
    values[0] = cell_count
    values[1] = capacity_centi_ah
    values[2] = cell_ovp_mv
    values[3] = cell_ovp_mv - 100  # recovery
    values[5] = cell_uvp_mv
    values[6] = cell_uvp_mv + 100  # recovery
    values[8] = charge_ocp_deci_a
    values[10] = discharge_ocp_deci_a
    values[14] = 2731 + 550  # charge high temperature, deciKelvin
    values[16] = 2731 + 0  # charge low temperature
    values[18] = 2731 + 600  # discharge high temperature
    values[20] = 2731 - 200  # discharge low temperature
    payload = bytearray()
    for value in values:
        payload += value.to_bytes(2, "little")
    return bytes(payload)


# ----------------------------------------------------------------- frame codec


def test_build_command_encodes_the_documented_frame_layout():
    bms = make_bms()
    assert bms._build_command(HumsiENK_Ble.CMD_HANDSHAKE) == b"\xaa\x00\x00\x00\x00"
    # checksum is the 16 bit little endian sum of CMD, LEN and the data bytes
    assert bms._build_command(0x50, [0x01]) == b"\xaa\x50\x01\x01\x52\x00"


def test_built_command_frames_round_trip_through_the_reader():
    bms = make_bms()
    bms.ble_handle.push(bms._build_command(HumsiENK_Ble.CMD_CELL_VOLTAGES, cell_payload([3301, 3302, 3303, 3304])))

    assert bms._read_frames() == [HumsiENK_Ble.CMD_CELL_VOLTAGES]
    assert [cell.voltage for cell in bms.cells] == [3.301, 3.302, 3.303, 3.304]


def test_frames_are_reassembled_across_notification_boundaries():
    bms = make_bms(FakeBleHandle(chunk_size=7))
    bms.ble_handle.push(frame(HumsiENK_Ble.CMD_BATTERY_INFO, battery_info_payload()))
    assert len(bms.ble_handle.queue) > 1, "the frame must actually be split for this test to mean anything"

    assert bms._read_frames() == [HumsiENK_Ble.CMD_BATTERY_INFO]
    assert bms.soc == 87


def test_several_frames_in_one_notification_are_all_parsed():
    bms = make_bms()
    bms.ble_handle.push(frame(HumsiENK_Ble.CMD_BATTERY_INFO, battery_info_payload()) + frame(HumsiENK_Ble.CMD_CELL_VOLTAGES, cell_payload([3300] * 4)))

    assert bms._read_frames() == [HumsiENK_Ble.CMD_BATTERY_INFO, HumsiENK_Ble.CMD_CELL_VOLTAGES]


def test_a_truncated_frame_is_held_until_the_rest_arrives():
    bms = make_bms()
    complete = frame(HumsiENK_Ble.CMD_BATTERY_INFO, battery_info_payload())
    bms.ble_handle.push(complete[:-3])

    assert bms._read_frames() == []
    assert bms.soc is None

    bms.ble_handle.push(complete[-3:])
    assert bms._read_frames() == [HumsiENK_Ble.CMD_BATTERY_INFO]
    assert bms.soc == 87


def test_a_bad_checksum_is_dropped_and_the_reader_resynchronises():
    bms = make_bms()
    corrupt = bytearray(frame(HumsiENK_Ble.CMD_BATTERY_INFO, battery_info_payload(soc=11)))
    corrupt[-1] ^= 0xFF
    bms.ble_handle.push(bytes(corrupt) + frame(HumsiENK_Ble.CMD_BATTERY_INFO, battery_info_payload(soc=87)))

    assert bms._read_frames() == [HumsiENK_Ble.CMD_BATTERY_INFO]
    assert bms.soc == 87, "the corrupt frame must not be applied"


def test_a_bad_checksum_does_not_count_as_data_from_the_radio():
    bms = make_bms()
    corrupt = bytearray(frame(HumsiENK_Ble.CMD_BATTERY_INFO, battery_info_payload()))
    corrupt[-1] ^= 0xFF
    bms.ble_handle.push(bytes(corrupt))

    assert bms._read_frames() == []
    assert bms._last_frame_time == 0.0
    assert bms.ble_handle.watchdog_feeds == 0


def test_an_implausible_length_byte_is_resynchronised_past():
    bms = make_bms()
    bms.ble_handle.push(bytes([0xAA, 0x21, 0xFF, 0x01, 0x02]) + frame(HumsiENK_Ble.CMD_BATTERY_INFO, battery_info_payload()))

    assert bms._read_frames() == [HumsiENK_Ble.CMD_BATTERY_INFO]
    assert bms.soc == 87


def test_reading_a_frame_marks_the_data_fresh_and_feeds_the_watchdog():
    bms = make_bms()
    bms.ble_handle.push(frame(HumsiENK_Ble.CMD_BATTERY_INFO, battery_info_payload()))

    bms._read_frames()

    assert bms.ble_handle.watchdog_feeds == 1
    assert time.time() - bms._last_frame_time < 5


def test_junk_without_a_start_byte_is_discarded():
    bms = make_bms()
    bms.ble_handle.push(b"\x01\x02\x03\x04\x05\x06")

    assert bms._read_frames() == []
    assert bms._rx_buffer == bytearray()


# -------------------------------------------------------- 0x21 battery info


def test_battery_info_offsets():
    bms = make_bms()
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_BATTERY_INFO, battery_info_payload()))

    assert bms.voltage == 13.26
    assert bms.current == -4.5
    assert bms.soc == 87
    assert bms.soh == 99
    assert bms.capacity_remain == 91.0
    assert bms.capacity == 100.0
    assert bms.history.charge_cycles == 42
    assert (bms.temperature_1, bms.temperature_2, bms.temperature_3, bms.temperature_4) == (21, 22, 23, 24)
    assert bms.temperature_mos == 31


def test_battery_info_temperatures_below_zero_are_signed():
    bms = make_bms()
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_BATTERY_INFO, battery_info_payload(temperatures=(-1, -5, -13, 0, -8, -20))))

    assert (bms.temperature_1, bms.temperature_2, bms.temperature_3, bms.temperature_4) == (-1, -5, -13, 0)
    assert bms.temperature_mos == -8


def test_battery_info_reports_a_bogus_soh_as_unknown():
    bms = make_bms()
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_BATTERY_INFO, battery_info_payload(soh=255)))

    assert bms.soh is None


def test_a_short_battery_info_frame_changes_nothing():
    bms = make_bms()
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_BATTERY_INFO, battery_info_payload()[:20]))

    assert bms.voltage is None


# ------------------------------------------------------- 0x22 cell voltages


def test_cell_voltages_stop_at_the_first_implausible_slot():
    bms = make_bms()
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_CELL_VOLTAGES, cell_payload([3300, 3310, 3320, 3330] + [0] * 20)))

    assert bms.cell_count == 4
    assert [cell.voltage for cell in bms.cells] == [3.3, 3.31, 3.32, 3.33]


def test_repeated_cell_frames_do_not_grow_the_cell_list():
    bms = make_bms()
    payload = cell_payload([3300] * 4 + [0] * 20)
    for _ in range(5):
        bms._parse_and_update(frame(HumsiENK_Ble.CMD_CELL_VOLTAGES, payload))

    assert len(bms.cells) == 4


def test_an_all_zero_cell_frame_does_not_wipe_the_cell_list():
    bms = make_bms()
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_CELL_VOLTAGES, cell_payload([3300, 3310, 3320, 3330])))
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_CELL_VOLTAGES, cell_payload([0] * 24)))

    assert bms.cell_count == 4
    assert [cell.voltage for cell in bms.cells] == [3.3, 3.31, 3.32, 3.33]


def test_a_shrinking_string_drops_the_cells_that_went_away():
    bms = make_bms()
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_CELL_VOLTAGES, cell_payload([3300] * 8)))
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_CELL_VOLTAGES, cell_payload([3300] * 4 + [0] * 4)))

    assert bms.cell_count == 4
    assert len(bms.cells) == 4


def test_the_pack_voltage_is_not_overwritten_by_the_sum_of_the_cells():
    bms = make_bms()
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_BATTERY_INFO, battery_info_payload(voltage_mv=13260)))
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_CELL_VOLTAGES, cell_payload([3300] * 4)))

    assert bms.voltage == 13.26


# ------------------------------------------------------------- 0x20 status


def test_status_reports_the_fet_states():
    bms = make_bms()
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_STATUS, status_payload(status_bits=(1 << 7) | (1 << 23) | (1 << 15))))

    assert (bms.charge_fet, bms.discharge_fet, bms.balance_fet) == (True, True, True)

    bms._parse_and_update(frame(HumsiENK_Ble.CMD_STATUS, status_payload(status_bits=0)))
    assert (bms.charge_fet, bms.discharge_fet, bms.balance_fet) == (False, False, False)


def test_status_alarm_bits_map_to_alarms_and_warnings():
    protection_bits = {
        "high_voltage": (4, 12),
        "low_voltage": (21, 28),
        "high_charge_current": (0, 8),
        "high_discharge_current": (16, 24),
        "high_charge_temperature": (1, 9),
        "low_charge_temperature": (2, 10),
        "high_temperature": (17, 25),
        "low_temperature": (18, 26),
        "high_internal_temperature": (30, 29),
    }
    for name, (alarm_bit, warning_bit) in protection_bits.items():
        bms = make_bms()
        bms._parse_and_update(frame(HumsiENK_Ble.CMD_STATUS, status_payload(status_bits=1 << warning_bit)))
        assert getattr(bms.protection, name) == 1, f"{name} should warn on bit {warning_bit}"

        bms._parse_and_update(frame(HumsiENK_Ble.CMD_STATUS, status_payload(status_bits=1 << alarm_bit)))
        assert getattr(bms.protection, name) == 2, f"{name} should alarm on bit {alarm_bit}"

        bms._parse_and_update(frame(HumsiENK_Ble.CMD_STATUS, status_payload(status_bits=0)))
        assert getattr(bms.protection, name) == 0, f"{name} should clear"


def test_a_short_circuit_is_reported_as_a_discharge_overcurrent_alarm():
    bms = make_bms()
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_STATUS, status_payload(status_bits=1 << 20)))

    assert bms.protection.high_discharge_current == 2


def test_status_applies_the_balancing_bitmap_to_the_known_cells():
    bms = make_bms()
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_CELL_VOLTAGES, cell_payload([3300] * 4)))
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_STATUS, status_payload(balancing=0b0101)))

    assert [cell.balance for cell in bms.cells] == [True, False, True, False]


def test_a_disconnected_cell_raises_an_internal_failure():
    bms = make_bms()
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_CELL_VOLTAGES, cell_payload([3300] * 4)))
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_STATUS, status_payload(disconnected=0b0010)))
    assert bms.protection.internal_failure == 2

    bms._parse_and_update(frame(HumsiENK_Ble.CMD_STATUS, status_payload(disconnected=0)))
    assert bms.protection.internal_failure == 0


def test_a_short_status_frame_changes_nothing():
    bms = make_bms()
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_STATUS, status_payload()[:10]))

    assert bms.charge_fet is None


# ------------------------------------------------------------- 0x58 config


def test_config_offsets(monkeypatch):
    # opt in, so the DVCC-gated fields are populated and their offsets checked
    monkeypatch.setattr(humsienk_ble, "USE_BMS_DVCC_VALUES", True)
    bms = make_bms()
    bms._parse_and_update(
        frame(HumsiENK_Ble.CMD_CONFIG, config_payload(cell_count=4, capacity_centi_ah=10000, charge_ocp_deci_a=1000, discharge_ocp_deci_a=1500))
    )

    assert bms.cell_count == 4
    assert bms.capacity == 100.0
    assert bms.max_battery_charge_current == 100.0
    assert bms.max_battery_discharge_current == 150.0


def test_bms_dvcc_values_are_ignored_unless_the_user_opts_in(monkeypatch):
    # Default (USE_BMS_DVCC_VALUES = False): the BMS settings frame must not
    # touch the DVCC values. These are protection trip points, not charge
    # targets - charging to the overvoltage protection is charging to the
    # point the BMS opens the charge FET. The base class derives the limits
    # from the configured cell voltages instead.
    monkeypatch.setattr(humsienk_ble, "USE_BMS_DVCC_VALUES", False)
    bms = make_bms()
    bms._parse_and_update(
        frame(
            HumsiENK_Ble.CMD_CONFIG,
            config_payload(cell_count=4, cell_ovp_mv=3650, cell_uvp_mv=2500, charge_ocp_deci_a=1000, discharge_ocp_deci_a=1500),
        )
    )

    assert bms.max_battery_voltage is None
    assert bms.min_battery_voltage is None
    assert bms.max_battery_charge_current == utils.MAX_BATTERY_CHARGE_CURRENT
    assert bms.max_battery_discharge_current == utils.MAX_BATTERY_DISCHARGE_CURRENT
    # the frame is still parsed for everything that is not a DVCC value
    assert bms.cell_count == 4


def test_bms_dvcc_values_are_used_raw_when_the_user_opts_in(monkeypatch):
    # Opted in: use what the BMS reports, unmodified. Matches battery_template
    # and the other drivers honouring this option - the driver does not invent
    # a clamping policy of its own.
    monkeypatch.setattr(humsienk_ble, "USE_BMS_DVCC_VALUES", True)
    bms = make_bms()
    bms._parse_and_update(
        frame(
            HumsiENK_Ble.CMD_CONFIG,
            config_payload(cell_count=4, cell_ovp_mv=3650, cell_uvp_mv=2500, charge_ocp_deci_a=1000, discharge_ocp_deci_a=1500),
        )
    )

    assert bms.max_battery_voltage == round(3.65 * 4, 2)
    assert bms.min_battery_voltage == round(2.5 * 4, 2)
    assert bms.max_battery_charge_current == 100.0
    assert bms.max_battery_discharge_current == 150.0


def test_a_short_config_frame_changes_nothing():
    bms = make_bms()
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_CONFIG, config_payload()[:40]))

    assert bms.cell_count is None


# ------------------------------------------------------------ 0xF5 version


def test_version_frame_decodes_the_ascii_string():
    bms = make_bms()
    bms._parse_and_update(frame(HumsiENK_Ble.CMD_VERSION, b"\x00HS30A3-1.07\x00"))

    assert bms.hardware_version == "HumsiENK vHS30A3-1.07"


def test_an_unknown_command_is_ignored():
    bms = make_bms()
    bms._parse_and_update(frame(0x40, b"\x01\x02\x03"))

    assert bms.voltage is None


# --------------------------------------------------- connection setup budget


def responding_handle():
    return FakeBleHandle(
        responses={
            HumsiENK_Ble.CMD_CELL_VOLTAGES: frame(HumsiENK_Ble.CMD_CELL_VOLTAGES, cell_payload([3300, 3310, 3320, 3330])),
            HumsiENK_Ble.CMD_BATTERY_INFO: frame(HumsiENK_Ble.CMD_BATTERY_INFO, battery_info_payload()),
            HumsiENK_Ble.CMD_CONFIG: frame(HumsiENK_Ble.CMD_CONFIG, config_payload()),
            HumsiENK_Ble.CMD_VERSION: frame(HumsiENK_Ble.CMD_VERSION, b"HS30A3-1.07"),
        }
    )


def test_test_connection_reads_the_settings_frame(monkeypatch):
    handle = responding_handle()
    monkeypatch.setattr("bms.humsienk_ble.HumsiENK_Syncron_Ble", lambda *args, **kwargs: handle)
    bms = make_bms(handle)

    assert bms.test_connection() is True
    # only reachable through get_settings(), which test_connection has to call.
    # Capacity and the version string come from the config and version frames;
    # the DVCC values are deliberately not asserted here because they are gated
    # on USE_BMS_DVCC_VALUES, which is off by default.
    assert bms.capacity == 100.0
    assert bms.hardware_version == "HumsiENK vHS30A3-1.07"
    assert [data[1] for data in handle.sent] == [
        HumsiENK_Ble.CMD_HANDSHAKE,
        HumsiENK_Ble.CMD_CELL_VOLTAGES,
        HumsiENK_Ble.CMD_BATTERY_INFO,
        HumsiENK_Ble.CMD_CONFIG,
        HumsiENK_Ble.CMD_VERSION,
    ]


def test_request_stops_waiting_at_the_shared_deadline():
    bms = make_bms()
    bms._deadline = time.time() + 0.3

    started = time.time()
    assert bms._request(HumsiENK_Ble.CMD_CONFIG, timeout=30.0) is False
    assert time.time() - started < 3.0


def test_request_does_not_even_send_once_the_budget_is_gone():
    bms = make_bms()
    bms._deadline = time.time() - 0.1

    assert bms._request(HumsiENK_Ble.CMD_CONFIG) is False
    assert bms.ble_handle.sent == []


def test_test_connection_gives_up_within_its_budget_on_a_silent_link(monkeypatch):
    handle = FakeBleHandle()  # link is up, BMS says nothing
    monkeypatch.setattr("bms.humsienk_ble.HumsiENK_Syncron_Ble", lambda *args, **kwargs: handle)
    bms = make_bms(handle)
    bms.STARTUP_TIMEOUT_SECONDS = 1.0

    started = time.time()
    assert bms.test_connection() is False
    assert time.time() - started < 4.0


def test_test_connection_fails_fast_when_the_link_never_comes_up(monkeypatch):
    handle = FakeBleHandle()
    handle.connected = False
    monkeypatch.setattr("bms.humsienk_ble.HumsiENK_Syncron_Ble", lambda *args, **kwargs: handle)
    bms = make_bms(handle)

    assert bms.test_connection() is False
    assert handle.sent == []


# ---------------------------------------------------------------- freshness


def test_refresh_data_fails_while_no_frame_has_ever_arrived():
    bms = make_bms()

    assert bms.refresh_data() is False


def test_refresh_data_succeeds_on_a_frame_that_just_arrived():
    bms = make_bms()
    bms.ble_handle.push(frame(HumsiENK_Ble.CMD_BATTERY_INFO, battery_info_payload()))

    assert bms.refresh_data() is True


def test_refresh_data_fails_again_once_the_data_has_aged_out():
    bms = make_bms()
    bms.ble_handle.push(frame(HumsiENK_Ble.CMD_BATTERY_INFO, battery_info_payload()))
    assert bms.refresh_data() is True

    bms._last_frame_time -= HumsiENK_Ble.DATA_FRESHNESS_SECONDS + 1
    assert bms.refresh_data() is False


def test_the_driver_carries_no_fallback_machinery():
    # Structural guard. This driver reports only what the radio delivered:
    # serving values during an outage belongs to the fallback layer, and an
    # earlier revision of this driver had grown a stale-data cache, an alarm
    # escalation ladder and on-disk persistence of its own. Keep it a plain
    # driver by making a relapse fail here.
    import inspect

    assert "fallback" not in inspect.getsource(humsienk_ble).lower()
