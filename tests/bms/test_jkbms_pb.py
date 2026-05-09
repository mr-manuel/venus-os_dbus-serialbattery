# -*- coding: utf-8 -*-
"""Tests for JKBMS PB deterministic serial protocol."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery"))

from bms.jkbms_pb import Jkbms_pb  # noqa: E402

# -- Test data from LA1010 capture (Monitor polling bat3, 2026-04-03) --

STATUS_RESPONSE = bytes.fromhex(
    "55aaeb900200dd0cdd0cdd0cdd0cdd0cdd0cde0cdd0cde0cde0cde0cde0cde0cdd0cde0cdd0c000000000000000000000000"
    "0000000000000000000000000000000000000000ffff0000dd0c01000100330034003f0042004d0058006600710077007100"
    "660062005a004400400036000000000000000000000000000000000000000000000000000000000000000000cb0000000000"
    "d7cd00000000000000000000c300c6000000000000000037535e0200c04504003e00000086b70901640000000422e5020101"
    "0000000000000000000000000000ff00010000009703000000001671404000000000951400000001010100060000b4e3af00"
    "00000000cb00c200c7009703863ec40b100900008051010000000302000000000000000001feff7fdc2f0101b0cf07000021"
)

FC16_ACK = bytes.fromhex("03101620000105a9")

SETTINGS_RESPONSE = bytes.fromhex(
    "55aaeb900100ac0d00008c0a0000550b0000420e0000740d000005000000750d0000540b00007a0d0000160d0000c4090000"
    "60ea0000030000003c000000a08601002c0100003c00000005000000d00700005e010000400100005e010000400100003200"
    "00004600000020030000bc02000010000000010000000100000001000000c0450400dc050000700d00000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000030000000000000060e316000033000a18feffffff9fe99d030000000034"
)

ABOUT_RESPONSE = bytes.fromhex(
    "55aaeb9003004a4b5f50423241313653323050000000313541000000000031352e34310000001c29e5021600000042423032"
    "0000000000000000000000003132333400000000000000000000000032343039313400003430313139343931343830003030"
    "30004a4b2d424d5300000000000000000000313336393133000000000000000000004a4b2d424d5300000000000000000000"
    "ffffffff8fe99d0300000000901f00000000c0d8e7fe3f00000100000000000000000004ff67000000000000000000000000"
    "0000ff0f000000000000000000000000000001ff670000000000000000000000000009080001640000005f0000003c000000"
    "320000000000000000000000002f00000a78011e0000000000000000000000000000000000fe9fe9ff0f00000000000000f6"
)

FC16_ACK_SETTINGS = bytes.fromhex("0310161e00016465")
FC16_ACK_ABOUT = bytes.fromhex("0310161c0001c5a5")

# FC16 request the driver sends for addr=3, command_status
FC16_REQUEST_STATUS = bytes.fromhex("031016200001020000cf91")


def _make_bms(addr=0x03):
    """Create a Jkbms_pb instance without opening a serial port."""
    bms = Jkbms_pb.__new__(Jkbms_pb)
    bms.address = bytes([addr])
    bms.command_status = b"\x10\x16\x20\x00\x01\x02\x00\x00"
    bms.command_settings = b"\x10\x16\x1e\x00\x01\x02\x00\x00"
    bms.command_about = b"\x10\x16\x1c\x00\x01\x02\x00\x00"
    bms.online = True
    return bms


class TestChecksum:
    def test_valid_status(self):
        assert Jkbms_pb._verify_checksum(STATUS_RESPONSE) is True

    def test_valid_settings(self):
        assert Jkbms_pb._verify_checksum(SETTINGS_RESPONSE) is True

    def test_valid_about(self):
        assert Jkbms_pb._verify_checksum(ABOUT_RESPONSE) is True

    def test_corrupted_checksum_byte(self):
        bad = bytearray(STATUS_RESPONSE)
        bad[299] ^= 0xFF
        assert Jkbms_pb._verify_checksum(bytes(bad)) is False

    def test_corrupted_payload_byte(self):
        bad = bytearray(STATUS_RESPONSE)
        bad[50] ^= 0x01
        assert Jkbms_pb._verify_checksum(bytes(bad)) is False

    def test_too_short(self):
        assert Jkbms_pb._verify_checksum(STATUS_RESPONSE[:299]) is False

    def test_too_long(self):
        assert Jkbms_pb._verify_checksum(STATUS_RESPONSE + b"\x00") is False


class TestAckValidation:
    def test_valid_status_ack(self):
        bms = _make_bms(addr=0x03)
        assert bms._verify_ack(FC16_ACK, bms.command_status) is True

    def test_valid_settings_ack(self):
        bms = _make_bms(addr=0x03)
        assert bms._verify_ack(FC16_ACK_SETTINGS, bms.command_settings) is True

    def test_valid_about_ack(self):
        bms = _make_bms(addr=0x03)
        assert bms._verify_ack(FC16_ACK_ABOUT, bms.command_about) is True

    def test_wrong_address(self):
        bad = bytearray(FC16_ACK)
        bad[0] = 0x01
        bms = _make_bms(addr=0x03)
        crc = bms.modbusCrc(bytes(bad[:6]))
        bad[6:8] = crc
        assert bms._verify_ack(bytes(bad), bms.command_status) is False

    def test_wrong_register(self):
        bms = _make_bms(addr=0x03)
        assert bms._verify_ack(FC16_ACK, bms.command_settings) is False

    def test_bad_crc(self):
        bad = bytearray(FC16_ACK)
        bad[7] ^= 0xFF
        bms = _make_bms(addr=0x03)
        assert bms._verify_ack(bytes(bad), bms.command_status) is False

    def test_wrong_length(self):
        bms = _make_bms(addr=0x03)
        assert bms._verify_ack(FC16_ACK[:7], bms.command_status) is False

    def test_modbus_exception_response(self):
        # FC = 0x90 (0x10 | 0x80) = exception
        exc = bytes([0x03, 0x90, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00])
        bms = _make_bms(addr=0x03)
        assert bms._verify_ack(exc, bms.command_status) is False


class MockSerial:
    """Simulates a serial port returning pre-loaded data.

    Data becomes available only after write() is called, simulating
    the real protocol: command TX triggers BMS response RX.
    """

    def __init__(self, response_bytes):
        self._response = bytearray(response_bytes)
        self._buf = bytearray()  # empty until write triggers response
        self._written = bytearray()

    def write(self, data):
        self._written.extend(data)
        self._buf.extend(self._response)  # BMS "responds" after command

    def read(self, size):
        chunk = bytes(self._buf[:size])
        self._buf = self._buf[size:]
        return chunk

    @property
    def in_waiting(self):
        return len(self._buf)

    def reset_input_buffer(self):
        self._buf.clear()

    def flush(self):
        pass


class TestReadResponse:
    def setup_method(self):
        Jkbms_pb._last_command_time = 0.0
        Jkbms_pb.COMMAND_GAP = 0  # no gap in tests — MockSerial is instantaneous

    def test_clean_response(self):
        """300-byte payload + 0x00 padding + 8-byte ACK."""
        bms = _make_bms(addr=0x03)
        ser = MockSerial(STATUS_RESPONSE + b"\x00" + FC16_ACK)
        result = bms._read_response(ser, bms.command_status, timeout=0.5)
        assert result is not False
        assert len(result) == 300
        assert result[:4] == b"\x55\xaa\xeb\x90"

    def test_tx_echo_prefix(self):
        """CH341 TX echo (11 bytes) prepended before 0x55AA."""
        bms = _make_bms(addr=0x03)
        ser = MockSerial(FC16_REQUEST_STATUS + STATUS_RESPONSE + b"\x00" + FC16_ACK)
        result = bms._read_response(ser, bms.command_status, timeout=0.5)
        assert result is not False
        assert len(result) == 300
        assert result[:4] == b"\x55\xaa\xeb\x90"

    def test_checksum_failure_returns_false(self):
        """Corrupted payload must return False."""
        bms = _make_bms(addr=0x03)
        bad = bytearray(STATUS_RESPONSE)
        bad[100] ^= 0xFF
        ser = MockSerial(bytes(bad) + b"\x00" + FC16_ACK)
        result = bms._read_response(ser, bms.command_status, timeout=0.5)
        assert result is False

    def test_no_data_returns_false(self):
        """Empty bus — no response at all."""
        bms = _make_bms(addr=0x03)
        bms.online = True
        ser = MockSerial(b"")
        result = bms._read_response(ser, bms.command_status, timeout=0.1)
        assert result is False

    def test_no_header_returns_false(self):
        """Data arrives but no 0x55AA."""
        bms = _make_bms(addr=0x03)
        ser = MockSerial(b"\xff" * 400)
        result = bms._read_response(ser, bms.command_status, timeout=0.1)
        assert result is False

    def test_command_written_correctly(self):
        """Verify FC16 command bytes sent to serial."""
        bms = _make_bms(addr=0x03)
        ser = MockSerial(STATUS_RESPONSE + b"\x00" + FC16_ACK)
        bms._read_response(ser, bms.command_status, timeout=0.5)
        assert ser._written == FC16_REQUEST_STATUS

    def test_missing_ack_still_returns_payload(self):
        """If ACK is missing, still return payload (checksum validates it)."""
        bms = _make_bms(addr=0x03)
        ser = MockSerial(STATUS_RESPONSE)  # no ACK
        result = bms._read_response(ser, bms.command_status, timeout=0.5)
        assert result is not False
        assert len(result) == 300

    def test_settings_response(self):
        """Settings command returns settings payload."""
        bms = _make_bms(addr=0x03)
        ser = MockSerial(SETTINGS_RESPONSE + b"\x00" + FC16_ACK_SETTINGS)
        result = bms._read_response(ser, bms.command_settings, timeout=0.5)
        assert result is not False
        assert len(result) == 300
        assert result[4] | result[5] << 8 == 1  # ftype=1 = settings
