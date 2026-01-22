# -*- coding: utf-8 -*-
"""
Tests for LltJbd_Up16s battery management system driver.
"""

from __future__ import annotations

import logging
import pytest
import serial
import time
import termios
from battery import Protection
from contextlib import contextmanager
from typing import Any, Generator, List, Optional, Type
from unittest.mock import MagicMock, patch

import bms.lltjbd_up16s
from bms.lltjbd_up16s import (
    CommandAvailability,
    LltJbd_Up16s,
    MASTER_AGGREGATED_VALUE_TIMEOUT_SECONDS,
    MAX_AVAILABILITY_RETRIES,
    MAX_INTERFERENCE_RETRY_SECONDS,
    MAX_SET_SOC_RETRIES,
    PackParams1,
    PackStatus,
    SharedData,
)

logging.basicConfig()
logger = logging.getLogger("test_lltjbd_up16s")


# =============================================================================
# Test Data Constants
# =============================================================================

PACK_STATUS_RESPONSE = bytes.fromhex(
    # Header: addr=1, func=0x78, start=0x1000, end=0x10a0, len=156
    "78 1000 10a0 009c"
    # pack_voltage=5314 (53.14V), unknown1, current=300312 (3.12A)
    "14c2 0000 00049518"
    # soc=6200 (62.00%), remaining_cap=19736, full_cap=32000, rated_cap=31400
    "1838 4d18 7d00 7aa8"
    # mosfet_temp=634, ambient_temp=643, operation_status, soh=100
    "027a 0283 0001 0064"
    # fault_flags (cell overvoltage), alarm_flags (total overvoltage), mosfet_flags=discharge, connection_state_flags
    "00000001 00000004 0001 0004"
    # charge_cycles=3, max_v_cell_num=10, max_cell_v=3323
    "0003 000a 0cfb"
    # min_v_cell_num=1, min_cell_v=3318, avg_cell_v=3321
    "0001 0cf6 0cf9"
    # max_t_sensor=1, max_cell_temp=625, min_t_sensor=4, min_cell_temp=621
    "0001 0271 0004 026d"
    # avg_cell_temp=623, max_charge_v=576, ccl=2400, min_discharge_v=432, dcl=5500
    "026f 0240 0960 01b0 157c"
    # cell_count=16, 16 cell voltages
    "0010"
    "0cf6 0cf9 0cfa 0cfa 0cf9 0cf8 0cfa 0cfa"
    "0cf9 0cfb 0cfa 0cfb 0cf9 0cfb 0cfa 0cf9"
    # temp_count=4, 4 temperatures
    "0004"
    "0271 026f 026f 026d"
    # unknown2, balancing_flags, firmware_version
    "0000 0004 0c01"
    # pack_serial_number (30 bytes): "JBD87654321"
    "4a 42 44 38 37 36 35 34 33 32 31 00 0000 0000 0000 0000 0000 0000 0000 0000 0000"
    # trailing fields
    "0003 0007 0000 0004 0000"
)
PACK_STATUS_ADDR1_REQUEST = bytes.fromhex("01 78 1000 10a0 0000 7fb2")
PACK_STATUS_ADDR2_REQUEST = bytes.fromhex("02 78 1000 10a0 0000 3fa7")
# Prepend battery address and append CRC
PACK_STATUS_ADDR1_RESPONSE = bytes.fromhex("01") + PACK_STATUS_RESPONSE + bytes.fromhex("52e7")
PACK_STATUS_ADDR2_RESPONSE = bytes.fromhex("02") + PACK_STATUS_RESPONSE + bytes.fromhex("86ff")


PACK_STATUS_DIFFERENT_RESPONSE = bytes.fromhex(
    # Header: addr=1, func=0x78, start=0x1000, end=0x10a0, len=156
    "78 1000 10a0 009c"
    # pack_voltage, unknown1, current
    "1422 0000 00049510"
    # soc, remaining_cap, full_cap=32000, rated_cap=31400
    "1220 3d00 7d00 7aa8"
    # mosfet_temp, ambient_temp, operation_status, soh=100
    "0270 0280 0000 0063"
    # fault_flags, alarm_flags, mosfet_flags, connection_state_flags
    "00000000 00000000 0000 0000"
    # charge_cycles, max_v_cell_num, max_cell_v
    "0002 000b 0cf0"
    # min_v_cell_num, min_cell_v, avg_cell_v
    "0003 0ce0 0ce5"
    # max_t_sensor, max_cell_temp, min_t_sensor, min_cell_temp
    "0002 0270 0003 0265"
    # avg_cell_temp, max_charge_v, ccl, min_discharge_v, dcl
    "026e 0242 0900 01b5 1000"
    # cell_count=16, 16 cell voltages
    "0010"
    "0cf0 0ce5 0ce0 0ce5 0ce5 0ce5 0ce5 0ce5"
    "0ce8 0cf0 0cf0 0cf0 0cf0 0cf0 0cf0 0cf0"
    # temp_count=4, 4 temperatures
    "0004"
    "026f 0270 0265 026d"
    # unknown2, balancing_flags, firmware_version
    "0000 00ff 0c01"
    # pack_serial_number (30 bytes): "JBD87654321"
    "4a 42 44 38 37 36 35 34 33 32 31 00 0000 0000 0000 0000 0000 0000 0000 0000 0000"
    # trailing fields
    "0002 0004 0000 0004 0000"
)
PACK_STATUS_ADDR2_DIFFERENT_RESPONSE = bytes.fromhex("02") + PACK_STATUS_DIFFERENT_RESPONSE + bytes.fromhex("c3cf")


INDIVIDUAL_PACK_STATUS_RESPONSE = bytes.fromhex(
    "45 0000 0054 0074"
    "00 10 0c f7 0c f9 0c fa 0c fa 0c f9 0c f8 0c fa"
    "0c fa 0c fa 0c fb 0c fa 0c fb 0c f9 0c fb 0c fa"
    "0c f9 0c fb 0c f7 14 c2 00 00 01 33 0b 28 0b 25"
    "7a a8 4d 19 00 03 00 3e 00 64 00 00 00 00 00 0b"
    "00 00 42 4a 38 44 36 37 34 35 32 33 00 31 00 00"
    "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"
    "03 e8"  # charge_current_limit = 1000 (100A)
    "07 d0"  # discharge_current_limit = 2000 (200A)
    "00 07 0b 31 0b 3b 04 01 0b 28 0b 25 0b 25 0b 25"
)
INDIVIDUAL_PACK_STATUS_ADDR1_REQUEST = bytes.fromhex("01 45 0000 0054 0000 d4d3")
INDIVIDUAL_PACK_STATUS_ADDR2_REQUEST = bytes.fromhex("02 45 0000 0054 0000 94c6")
INDIVIDUAL_PACK_STATUS_ADDR1_RESPONSE = bytes.fromhex("01") + INDIVIDUAL_PACK_STATUS_RESPONSE + bytes.fromhex("5927")
INDIVIDUAL_PACK_STATUS_ADDR2_RESPONSE = bytes.fromhex("02") + INDIVIDUAL_PACK_STATUS_RESPONSE + bytes.fromhex("5d67")


PACK_PARAMS1_RESPONSE = bytes.fromhex(
    "78 1c00 1ca0 0086"
    "00 00 00 00 0d 16 00 0f 01 f4 02 58 15 90 07 d0"
    "55 50 31 36 53 30 31 35 30 30 30 30 30 30 30 30"  # "UP16S015000000000000000000"
    "30 30 30 30 30 30 30 30 30 30 00 00 00 00"
    "07 e9"  # bms_year = 2025
    "00 05"  # bms_month = 5
    "00 07"  # bms_day = 7
    "4a 42 44 38 37 36 35 34 33 32 31 00 00 00 00 00"  # "JBD87654321"
    "00 00 00 00 00 00 00 00 00 00 00 00 00 00"
    "07 e9"  # pack_year = 2025
    "00 04"  # pack_month = 4
    "00 06"  # pack_day = 6
    "38 38 38 38 38 38 00 00 00 00 00 00 00 00 00 00"
    "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 04"
    "0b b8 0b 40 00 01 00 00 00 00 00 00 00 0a"
)
PACK_PARAMS1_ADDR1_REQUEST = bytes.fromhex("01 78 1c00 1ca0 0000 7c2e")
PACK_PARAMS1_ADDR2_REQUEST = bytes.fromhex("02 78 1c00 1ca0 0000 3c3b")
PACK_PARAMS1_ADDR1_RESPONSE = bytes.fromhex("01") + PACK_PARAMS1_RESPONSE + bytes.fromhex("7b2d")
PACK_PARAMS1_ADDR2_RESPONSE = bytes.fromhex("02") + PACK_PARAMS1_RESPONSE + bytes.fromhex("0bc8")


PACK_PARAMS2_RESPONSE = bytes.fromhex(
    "78 2006 2018 0012"
    "18 8d"  # high_res_soc = 6285 (62.85%)
    "00 64 00 03 00 96 00 50"
    "00 00 19 74"  # total_charge = 6516 (651.6 Ah)
    "00 00 1e ea"  # total_discharge = 7914 (791.4 Ah)
)
PACK_PARAMS2_ADDR1_REQUEST = bytes.fromhex("01 78 2006 2018 0000 7d67")
PACK_PARAMS2_ADDR2_REQUEST = bytes.fromhex("02 78 2006 2018 0000 3d72")
PACK_PARAMS2_ADDR1_RESPONSE = bytes.fromhex("01") + PACK_PARAMS2_RESPONSE + bytes.fromhex("98b0")
PACK_PARAMS2_ADDR2_RESPONSE = bytes.fromhex("02") + PACK_PARAMS2_RESPONSE + bytes.fromhex("93f0")


PRODUCT_INFORMATION_RESPONSE = bytes.fromhex(
    "78 2810 283c 002c"
    "00 21"  # maybe_model_id = 33
    "00 03"  # maybe_hardware_revision = 3
    "00 0c"  # firmware_major_version = 12
    "00 01"  # firmware_minor_version = 1
    "00 07"  # firmware_patch_version = 7
    "00 24"  # unknown1 = 36
    "55 50 31 36 53 30 31 35 2e 31 36 53 32 30 30 41"  # model = "UP16S015.16S200A"
    "4a 42 44 00 00 00 00 00 00 00 00 00 00 00 00 00"  # project_code = "JBD"
)
PRODUCT_INFORMATION_ADDR1_REQUEST = bytes.fromhex("01 78 2810 283c 0000 7787")
PRODUCT_INFORMATION_ADDR2_REQUEST = bytes.fromhex("02 78 2810 283c 0000 3792")
PRODUCT_INFORMATION_ADDR1_RESPONSE = bytes.fromhex("01") + PRODUCT_INFORMATION_RESPONSE + bytes.fromhex("dd99")
PRODUCT_INFORMATION_ADDR2_RESPONSE = bytes.fromhex("02") + PRODUCT_INFORMATION_RESPONSE + bytes.fromhex("4a73")


SET_SOC_TO_100_ADDR1_REQUEST = bytes.fromhex("01 79 2006 2008 0006 114a4244 2710 427a")
SET_SOC_TO_98_ADDR1_REQUEST = bytes.fromhex("01 79 2006 2008 0006 114a4244 2648 4210")
SET_SOC_TO_100_ADDR2_REQUEST = bytes.fromhex("02 79 2006 2008 0006 114a4244 2710 4179")
SET_SOC_ADDR1_RESPONSE = bytes.fromhex("01 79 2006 2008 0000 6c62")
SET_SOC_ADDR2_RESPONSE = bytes.fromhex("02 79 2006 2008 0000 2c77")


RESPONSE_MAP = {
    PACK_STATUS_ADDR1_REQUEST: PACK_STATUS_ADDR1_RESPONSE,
    PACK_STATUS_ADDR2_REQUEST: PACK_STATUS_ADDR2_RESPONSE,
    INDIVIDUAL_PACK_STATUS_ADDR1_REQUEST: INDIVIDUAL_PACK_STATUS_ADDR1_RESPONSE,
    INDIVIDUAL_PACK_STATUS_ADDR2_REQUEST: INDIVIDUAL_PACK_STATUS_ADDR2_RESPONSE,
    PACK_PARAMS1_ADDR1_REQUEST: PACK_PARAMS1_ADDR1_RESPONSE,
    PACK_PARAMS1_ADDR2_REQUEST: PACK_PARAMS1_ADDR2_RESPONSE,
    PACK_PARAMS2_ADDR1_REQUEST: PACK_PARAMS2_ADDR1_RESPONSE,
    PACK_PARAMS2_ADDR2_REQUEST: PACK_PARAMS2_ADDR2_RESPONSE,
    PRODUCT_INFORMATION_ADDR1_REQUEST: PRODUCT_INFORMATION_ADDR1_RESPONSE,
    PRODUCT_INFORMATION_ADDR2_REQUEST: PRODUCT_INFORMATION_ADDR2_RESPONSE,
    SET_SOC_TO_100_ADDR1_REQUEST: SET_SOC_ADDR1_RESPONSE,
    SET_SOC_TO_98_ADDR1_REQUEST: SET_SOC_ADDR1_RESPONSE,
    SET_SOC_TO_100_ADDR2_REQUEST: SET_SOC_ADDR2_RESPONSE,
}

REFRESH_DATA_MASTER_REQUESTS = [
    PACK_STATUS_ADDR1_REQUEST,
    PACK_PARAMS2_ADDR1_REQUEST,
    INDIVIDUAL_PACK_STATUS_ADDR1_REQUEST,
]

REFRESH_DATA_MASTER_RESPONSES = [
    PACK_STATUS_ADDR1_RESPONSE,
    PACK_PARAMS2_ADDR1_RESPONSE,
    INDIVIDUAL_PACK_STATUS_ADDR1_RESPONSE,
]

REFRESH_DATA_SLAVE_REQUESTS = [
    PACK_STATUS_ADDR2_REQUEST,
    PACK_PARAMS2_ADDR2_REQUEST,
]

REFRESH_DATA_SLAVE_RESPONSES = [
    PACK_STATUS_ADDR2_RESPONSE,
    PACK_PARAMS2_ADDR2_RESPONSE,
]

TEST_CONNECTION_MASTER_REQUESTS = REFRESH_DATA_MASTER_REQUESTS + [
    PACK_PARAMS1_ADDR1_REQUEST,
    PRODUCT_INFORMATION_ADDR1_REQUEST,
]

TEST_CONNECTION_MASTER_RESPONSES = REFRESH_DATA_MASTER_RESPONSES + [
    PACK_PARAMS1_ADDR1_RESPONSE,
    PRODUCT_INFORMATION_ADDR1_RESPONSE,
]

TEST_CONNECTION_SLAVE_REQUESTS = REFRESH_DATA_SLAVE_REQUESTS + [
    PACK_PARAMS1_ADDR2_REQUEST,
    PRODUCT_INFORMATION_ADDR2_REQUEST,
]


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def fresh_shared_data() -> Generator[SharedData, None, None]:
    # Reset shared data before and after each test to ensure isolation.
    bms.lltjbd_up16s.shared_data = SharedData()
    yield bms.lltjbd_up16s.shared_data
    bms.lltjbd_up16s.shared_data = SharedData()


@pytest.fixture
def mock_serial_port() -> MagicMock:
    """Create a mock serial port context manager."""
    mock_ser = MagicMock(spec=serial.Serial)
    mock_ser.__enter__ = MagicMock(return_value=mock_ser)
    mock_ser.__exit__ = MagicMock(return_value=False)
    return mock_ser


@pytest.fixture
def battery_master(fresh_shared_data: SharedData) -> LltJbd_Up16s:
    """Create a battery instance at address 1 (master)."""
    return LltJbd_Up16s("/dev/ttyUSB0", 9600, b"\x01")


@pytest.fixture
def battery_slave(fresh_shared_data: SharedData) -> LltJbd_Up16s:
    """Create a battery instance at address 2 (slave)."""
    return LltJbd_Up16s("/dev/ttyUSB0", 9600, b"\x02")


@pytest.fixture
def termios_settings_ok() -> List[int]:
    """Return termios settings indicating no interference."""
    return [0, 0, termios.CS8, 0, termios.B9600, termios.B9600]


@pytest.fixture
def termios_settings_interference() -> List[int]:
    """Return termios settings indicating baud rate interference."""
    return [0, 0, termios.CS8, 0, termios.B19200, termios.B19200]


def read_serialport_data_emulator(
    ser: serial.Serial,
    request: bytearray,
    timeout_seconds: float,
    extra_length: int,
    payload_length_pos: int,
    payload_length_size: str = "B",
    length_fixed: Optional[int] = None,
) -> Optional[bytearray]:
    """Emulates responses to known commands."""
    if request in RESPONSE_MAP:
        return RESPONSE_MAP[request]
    raise ValueError(f"Unexpected request not emulated in read_serialport_data_emulator(): {request.hex(' ')}")


@contextmanager
def serial_communication_patches(
    mock_serial: MagicMock,
    require_direct_connection: bool = False,
    responses: Optional[List[bytes]] = None,
) -> Generator[tuple[MagicMock, MagicMock], None, None]:
    """Context manager for common patches."""
    with patch("bms.lltjbd_up16s.UP16S_REQUIRE_DIRECT_CONNECTION", require_direct_connection):
        with patch("serial.Serial") as mock_serial_class:
            mock_serial_class.return_value.__enter__.return_value = mock_serial
            with patch("bms.lltjbd_up16s.read_serialport_data") as mock_read_serialport_data:
                mock_read_serialport_data.side_effect = read_serialport_data_emulator if responses is None else responses
                with patch("termios.tcgetattr", side_effect=lambda _: [0, 0, termios.CS8, 0, termios.B9600, termios.B9600]):
                    with patch("time.sleep"):
                        yield mock_read_serialport_data


# =============================================================================
# test_connection() tests
# =============================================================================


def verify_fallback_unique_identifier(battery):
    """Verifies that unique identifier is in the fallback format: when the unique serial number couldn't be retrieved"""
    assert battery.unique_identifier() == "JBD87654321_314.0"


class TestConnection:
    """Tests for test_connection() method."""

    def test_master_indirect_success_parses_data(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        """Successful master connection without requiring direct connection."""
        with serial_communication_patches(mock_serial_port, require_direct_connection=False) as mock_read_serialport_data:
            result = battery_master.test_connection()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == TEST_CONNECTION_MASTER_REQUESTS
        assert result is True
        self.verify_parsed_indirect_connection_fields(battery_master)
        self.verify_parsed_direct_or_forwarded_connection_fields(battery_master)

    def test_slave_indirect_success_parses_data_and_populates_soc_reset_callback_and_does_not_request_individual_pack_status(
        self,
        battery_slave: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        """Successful slave connection without requiring direct connection."""
        with serial_communication_patches(mock_serial_port, require_direct_connection=False) as mock_read_serialport_data:
            result = battery_slave.test_connection()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == TEST_CONNECTION_SLAVE_REQUESTS
        assert result is True
        assert battery_slave.callbacks_available == ["callback_soc_reset_to"]
        self.verify_parsed_indirect_connection_fields(battery_slave)
        self.verify_parsed_direct_or_forwarded_connection_fields(battery_slave)

    def test_slave_direct_success_requests_individual_pack_status_and_parses_data(
        self,
        battery_slave: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        """Successful slave connection with direct connection requirement."""
        with serial_communication_patches(mock_serial_port, require_direct_connection=True) as mock_read_serialport_data:
            result = battery_slave.test_connection()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == [INDIVIDUAL_PACK_STATUS_ADDR2_REQUEST] + TEST_CONNECTION_SLAVE_REQUESTS
        assert result is True
        self.verify_parsed_indirect_connection_fields(battery_slave)
        self.verify_parsed_direct_or_forwarded_connection_fields(battery_slave)

    def test_slave_indirect_only_pack_status_success_retries_and_does_not_populate_soc_reset_callback(
        self,
        battery_slave: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        """SOC reset callback should not be populated if PackParams2 call was unsuccessful."""
        with serial_communication_patches(
            mock_serial_port,
            responses=[PACK_STATUS_ADDR2_RESPONSE, None] + [None] * MAX_AVAILABILITY_RETRIES,
        ) as mock_read_serialport_data:
            result = battery_slave.test_connection()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == (
            REFRESH_DATA_SLAVE_REQUESTS + [PACK_PARAMS1_ADDR2_REQUEST] * MAX_AVAILABILITY_RETRIES
        )
        assert result is True
        assert battery_slave.callbacks_available == []
        self.verify_parsed_indirect_connection_fields(battery_slave)
        verify_fallback_unique_identifier(battery_slave)

    def test_slave_direct_unavailable_failure(
        self,
        battery_slave: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        """test_connection() should fail if direct connection is required but IndividualPackStatus fails."""
        with serial_communication_patches(mock_serial_port, require_direct_connection=True, responses=[None]) as mock_read_serialport_data:
            result = battery_slave.test_connection()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == [
            INDIVIDUAL_PACK_STATUS_ADDR2_REQUEST,
        ]
        assert result is False

    def test_pack_status_unavailable_failure(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        """test_connection() should fail if PackStatus cannot be read."""
        with serial_communication_patches(
            mock_serial_port,
            responses=[None],
        ) as mock_read_serialport_data:
            result = battery_master.test_connection()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == [
            PACK_STATUS_ADDR1_REQUEST,
        ]
        assert result is False

    @staticmethod
    def verify_parsed_indirect_connection_fields(battery) -> None:
        TestRefreshData.verify_parsed_indirect_connection_fields(battery)

    @staticmethod
    def verify_parsed_direct_or_forwarded_connection_fields(battery) -> None:
        assert battery.bms_model_and_serial_number == "UP16S015000000000000000000"
        TestRefreshData.verify_parsed_direct_or_forwarded_connection_fields(battery)


# =============================================================================
# refresh_data() tests
# =============================================================================


class TestRefreshData:
    """Tests for refresh_data() method."""

    def test_master_on_success_requests_individual_pack_status_and_populates_direct_connection_data(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        with serial_communication_patches(mock_serial_port) as mock_read_serialport_data:
            battery_master.test_connection()
            result = battery_master.refresh_data()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == TEST_CONNECTION_MASTER_REQUESTS + REFRESH_DATA_MASTER_REQUESTS
        assert result is True
        self.verify_master_ccl_and_dcl_are_from_individual_pack_status(battery_master)
        self.verify_parsed_indirect_connection_fields(battery_master)
        self.verify_parsed_direct_or_forwarded_connection_fields(battery_master)

    def test_slave_on_success_does_not_request_individual_pack_status_and_populates_direct_connection_data(
        self,
        battery_slave: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        with serial_communication_patches(mock_serial_port) as mock_read_serialport_data:
            battery_slave.test_connection()
            result = battery_slave.refresh_data()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == TEST_CONNECTION_SLAVE_REQUESTS + REFRESH_DATA_SLAVE_REQUESTS
        assert result is True
        self.verify_ccl_and_dcl_from_pack_status(battery_slave)
        self.verify_parsed_indirect_connection_fields(battery_slave)
        self.verify_parsed_direct_or_forwarded_connection_fields(battery_slave)

    def test_multiple_refresh_data_parses_data_and_adds_total_ah_drawn_to_exclusions_list_only_once(
        self,
        battery_slave: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        with serial_communication_patches(mock_serial_port) as mock_read_serialport_data:
            battery_slave.test_connection()
            battery_slave.refresh_data()
            result = battery_slave.refresh_data()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == TEST_CONNECTION_SLAVE_REQUESTS + REFRESH_DATA_SLAVE_REQUESTS * 2
        assert result is True
        self.verify_charge_cycles_and_total_ah_drawn_are_added_once_to_calculation_exclusions_list(battery_slave)
        self.verify_ccl_and_dcl_from_pack_status(battery_slave)
        self.verify_parsed_indirect_connection_fields(battery_slave)
        self.verify_parsed_direct_or_forwarded_connection_fields(battery_slave)

    def test_slave_indirect_only_pack_status_success_parses_data_and_does_not_exclude_calculation_of_total_ah_drawn(
        self,
        battery_slave: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        with serial_communication_patches(
            mock_serial_port,
            require_direct_connection=False,
            responses=[PACK_STATUS_ADDR2_RESPONSE, None] + [None] * MAX_AVAILABILITY_RETRIES + [PACK_STATUS_ADDR2_RESPONSE, None],
        ) as mock_read_serialport_data:
            battery_slave.test_connection()
            result = battery_slave.refresh_data()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == (
            REFRESH_DATA_SLAVE_REQUESTS + [PACK_PARAMS1_ADDR2_REQUEST] * MAX_AVAILABILITY_RETRIES + REFRESH_DATA_SLAVE_REQUESTS
        )
        assert result is True
        self.verify_charge_cycles_is_excluded_and_total_ah_drawn_is_not_excluded_from_calculation(battery_slave)
        self.verify_ccl_and_dcl_from_pack_status(battery_slave)
        self.verify_soc_is_from_latest_pack_status(battery_slave)
        self.verify_parsed_indirect_connection_fields(battery_slave)
        verify_fallback_unique_identifier(battery_slave)

    def test_on_success_updates_stale_pack_status_data(
        self,
        battery_slave: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        with serial_communication_patches(
            mock_serial_port,
            responses=[PACK_STATUS_ADDR2_DIFFERENT_RESPONSE, PACK_PARAMS2_ADDR2_RESPONSE, PACK_PARAMS1_ADDR2_RESPONSE, PRODUCT_INFORMATION_ADDR2_RESPONSE]
            + REFRESH_DATA_SLAVE_RESPONSES,
        ) as mock_read_serialport_data:
            # test_connection() fetches PACK_STATUS_ADDR2_DIFFERENT_RESPONSE
            battery_slave.test_connection()
            # refresh_data() fetches PACK_STATUS_ADDR2_RESPONSE
            result = battery_slave.refresh_data()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == TEST_CONNECTION_SLAVE_REQUESTS + REFRESH_DATA_SLAVE_REQUESTS
        assert result is True
        # Verify the fields contain data specifically from PACK_STATUS_ADDR2_RESPONSE
        self.verify_ccl_and_dcl_from_pack_status(battery_slave)
        self.verify_parsed_indirect_connection_fields(battery_slave)
        self.verify_parsed_direct_or_forwarded_connection_fields(battery_slave)

    def test_on_pack_status_failure_returns_false(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        """refresh_data should return False when PackStatus fails."""
        with serial_communication_patches(
            mock_serial_port,
            responses=TEST_CONNECTION_MASTER_RESPONSES + [None],
        ) as mock_read_serialport_data:
            battery_master.test_connection()
            result = battery_master.refresh_data()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == TEST_CONNECTION_MASTER_REQUESTS + [
            PACK_STATUS_ADDR1_REQUEST,
        ]
        assert result is False

    def test_on_master_pack_status_success_with_individual_pack_status_failure_returns_true(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        """refresh_data() should still return True if IndividualPackStatus fails, since it's not a critical error."""
        with serial_communication_patches(
            mock_serial_port,
            responses=TEST_CONNECTION_MASTER_RESPONSES + [PACK_STATUS_ADDR1_RESPONSE, PACK_PARAMS2_ADDR1_RESPONSE, None],
        ) as mock_read_serialport_data:
            battery_master.test_connection()
            result = battery_master.refresh_data()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == TEST_CONNECTION_MASTER_REQUESTS + REFRESH_DATA_MASTER_REQUESTS
        # IndividualPackStatus response is not available, so CCL and DCL must be taken from PackStatus
        self.verify_ccl_and_dcl_from_pack_status(battery_master)
        self.verify_parsed_indirect_connection_fields(battery_master)
        self.verify_parsed_direct_or_forwarded_connection_fields(battery_master)
        assert result is True

    def test_on_pack_status_success_with_temporary_pack_params2_failure_preserves_high_res_soc_and_returns_true(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        """refresh_data() should still return True if PackParams2 fails, since it's not a critical error.
        It should also preserve the previously parsed high-res SOC and wait until PackParams2 succeeds, to avoid causing noise in SOC readings."""
        with serial_communication_patches(
            mock_serial_port,
            responses=TEST_CONNECTION_MASTER_RESPONSES + [PACK_STATUS_ADDR1_RESPONSE, None, INDIVIDUAL_PACK_STATUS_ADDR1_RESPONSE],
        ) as mock_read_serialport_data:
            battery_master.test_connection()
            result = battery_master.refresh_data()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == TEST_CONNECTION_MASTER_REQUESTS + REFRESH_DATA_MASTER_REQUESTS
        self.verify_soc_is_high_resolution(battery_master)
        self.verify_master_ccl_and_dcl_are_from_individual_pack_status(battery_master)
        self.verify_parsed_indirect_connection_fields(battery_master)
        self.verify_parsed_direct_or_forwarded_connection_fields(battery_master)
        assert result is True

    def test_on_pack_status_success_with_persistent_pack_params2_failure_uses_non_high_res_soc_and_returns_true(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        """When PackParams2 fails, refresh_data() should use non-high-res SOC when it differs more than 1% from the last SOC reading."""
        with serial_communication_patches(
            mock_serial_port,
            responses=TEST_CONNECTION_MASTER_RESPONSES + [PACK_STATUS_ADDR1_RESPONSE, None, INDIVIDUAL_PACK_STATUS_ADDR1_RESPONSE],
        ) as mock_read_serialport_data:
            battery_master.test_connection()
            battery_master.soc = 61  # SOC value that differs more than 1% compared to what refresh_data() will fetch in the next line
            result = battery_master.refresh_data()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == TEST_CONNECTION_MASTER_REQUESTS + REFRESH_DATA_MASTER_REQUESTS
        self.verify_soc_is_from_latest_pack_status(battery_master)
        self.verify_master_ccl_and_dcl_are_from_individual_pack_status(battery_master)
        self.verify_parsed_indirect_connection_fields(battery_master)
        assert result is True

    def test_master_updates_shared_aggregated_ccl_dcl(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
        fresh_shared_data: SharedData,
    ) -> None:
        """Master should update shared data with aggregated current limits."""
        with serial_communication_patches(mock_serial_port):
            battery_master.test_connection()
            fresh_shared_data.master_aggregated_charge_current_limit_amps = 0
            fresh_shared_data.master_aggregated_discharge_current_limit_amps = 0
            battery_master.refresh_data()

        assert fresh_shared_data.master_aggregated_charge_current_limit_amps == pytest.approx(240.0)
        assert fresh_shared_data.master_aggregated_discharge_current_limit_amps == pytest.approx(550.0)

    @pytest.mark.parametrize(
        "master_ccl,master_dcl,expected_ccl,expected_dcl",
        [
            (0.0, 900.0, 0.0, 550.0),
            (900.0, 0.0, 240.0, 0.0),
        ],
        ids=["master_ccl_lower", "master_dcl_lower"],
    )
    def test_slave_uses_aggregated_minimum(
        self,
        battery_slave: LltJbd_Up16s,
        mock_serial_port: MagicMock,
        fresh_shared_data: SharedData,
        master_ccl: float,
        master_dcl: float,
        expected_ccl: float,
        expected_dcl: float,
    ) -> None:
        """Slave should use minimum of its own and master's aggregated limits."""
        fresh_shared_data.master_aggregated_charge_current_limit_amps = master_ccl
        fresh_shared_data.master_aggregated_discharge_current_limit_amps = master_dcl
        fresh_shared_data.master_aggregated_last_update_timestamp = time.monotonic()

        with serial_communication_patches(mock_serial_port):
            battery_slave.test_connection()
            battery_slave.refresh_data()

        assert battery_slave.max_battery_charge_current == pytest.approx(expected_ccl)
        assert battery_slave.max_battery_discharge_current == pytest.approx(expected_dcl)

    def test_slave_ignores_stale_aggregated_values(
        self,
        battery_slave: LltJbd_Up16s,
        mock_serial_port: MagicMock,
        fresh_shared_data: SharedData,
    ) -> None:
        fresh_shared_data.master_aggregated_charge_current_limit_amps = 10.0
        fresh_shared_data.master_aggregated_discharge_current_limit_amps = 20.0
        fresh_shared_data.master_aggregated_last_update_timestamp = time.monotonic() - MASTER_AGGREGATED_VALUE_TIMEOUT_SECONDS * 2  # Stale

        with serial_communication_patches(mock_serial_port):
            battery_slave.test_connection()
            battery_slave.refresh_data()

        assert battery_slave.max_battery_charge_current == pytest.approx(240.0)
        assert battery_slave.max_battery_discharge_current == pytest.approx(550.0)

    @staticmethod
    def verify_parsed_indirect_connection_fields(battery) -> None:
        assert battery.min_battery_voltage == pytest.approx(43.2)
        assert battery.max_battery_voltage == pytest.approx(57.6)
        assert battery.voltage == pytest.approx(53.14)
        assert battery.current == pytest.approx(3.12)
        assert battery.soh == 100
        assert battery.capacity == pytest.approx(320.0)
        assert battery.rated_capacity == pytest.approx(314.0)
        assert battery.capacity_remain == pytest.approx(197.36)
        assert battery.discharge_fet is True
        assert battery.charge_fet is False
        assert battery.pack_serial_number == "JBD87654321"
        assert battery.history.charge_cycles == 3

        assert battery.protection.high_cell_voltage == Protection.ALARM
        assert battery.protection.high_voltage == Protection.WARNING
        assert battery.protection.low_cell_voltage == Protection.OK
        assert battery.protection.low_voltage == Protection.OK
        assert battery.protection.high_charge_current == Protection.OK
        assert battery.protection.high_discharge_current == Protection.OK
        assert battery.protection.high_charge_temperature == Protection.OK
        assert battery.protection.low_charge_temperature == Protection.OK
        assert battery.protection.high_temperature == Protection.OK
        assert battery.protection.low_temperature == Protection.OK
        assert battery.protection.high_internal_temperature == Protection.OK
        assert battery.protection.cell_imbalance == Protection.OK
        assert battery.protection.low_soc == Protection.OK
        assert battery.protection.internal_failure == Protection.OK

        assert battery.temperature_mos == pytest.approx(13.4)
        assert battery.temperature_1 == pytest.approx(12.5)
        assert battery.cell_min_voltage == pytest.approx(3.318)
        assert battery.cell_max_voltage == pytest.approx(3.323)
        assert battery.cell_count == 16
        assert len(battery.cells) == 16
        assert battery.cells[0].voltage == pytest.approx(3.318)
        for i in range(16):
            # Only cell 3 is balancing, and cells[] is using 0-based indexing.
            is_3rd_cell = i == 2
            assert battery.cells[i].balance == is_3rd_cell

    @staticmethod
    def verify_parsed_direct_or_forwarded_connection_fields(battery) -> None:
        """Verifies the field values that could only be retrieved either over direct connection, or over Wifi/Bluetooth UART port
        on which master is able to forward this data from slaves."""
        TestRefreshData.verify_charge_cycles_and_total_ah_drawn_are_added_once_to_calculation_exclusions_list(battery)
        TestRefreshData.verify_soc_is_high_resolution(battery)
        assert battery.history.total_ah_drawn == pytest.approx(-791.4)
        # Verifies that the unique identifier is in the non-fallback format (since the proper unique serial number could be retrieved)
        assert battery.unique_identifier() == "UP16S015000000000000000000"

    @staticmethod
    def verify_charge_cycles_and_total_ah_drawn_are_added_once_to_calculation_exclusions_list(battery) -> None:
        # Charge cycles value is always available. Total Ah drawn value is available when it was fetched via PackParams2 command.
        assert battery.history.exclude_values_to_calculate == ["charge_cycles", "total_ah_drawn"]

    @staticmethod
    def verify_charge_cycles_is_excluded_and_total_ah_drawn_is_not_excluded_from_calculation(battery) -> None:
        # Total Ah drawn value should be calculated by battery.py when it cannot be fetched via PackParams2.
        assert battery.history.exclude_values_to_calculate == ["charge_cycles"]

    @staticmethod
    def verify_soc_is_high_resolution(battery) -> None:
        assert battery.soc == pytest.approx(62.85)

    @staticmethod
    def verify_soc_is_from_latest_pack_status(battery) -> None:
        assert battery.soc == pytest.approx(62.00)

    @staticmethod
    def verify_master_ccl_and_dcl_are_from_individual_pack_status(battery_master) -> None:
        # Master CCL and DCL must be from IndividualPackStatus, not the aggregated values from PackStatus.
        assert battery_master.max_battery_charge_current == pytest.approx(100.0)
        assert battery_master.max_battery_discharge_current == pytest.approx(200.0)

    @staticmethod
    def verify_ccl_and_dcl_from_pack_status(battery) -> None:
        assert battery.max_battery_charge_current == pytest.approx(240.0)
        assert battery.max_battery_discharge_current == pytest.approx(550.0)


# =============================================================================
# Tests for callback_soc_reset_to() and trigger_soc_reset()
# =============================================================================


class SocResetTests:
    @patch("bms.lltjbd_up16s.AUTO_RESET_SOC", True)
    def test_trigger_soc_reset_sets_soc(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        with serial_communication_patches(mock_serial_port) as mock_read_serialport_data:
            battery_master.test_connection()
            battery_master.trigger_soc_reset()
            battery_master.refresh_data()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == TEST_CONNECTION_MASTER_REQUESTS + [
            SET_SOC_TO_100_ADDR1_REQUEST
        ] + REFRESH_DATA_MASTER_REQUESTS

    @patch("bms.lltjbd_up16s.AUTO_RESET_SOC", False)
    def test_trigger_soc_reset_with_auto_reset_soc_disabled_does_not_set_soc(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        with serial_communication_patches(mock_serial_port) as mock_read_serialport_data:
            battery_master.test_connection()
            battery_master.trigger_soc_reset()
            battery_master.refresh_data()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == TEST_CONNECTION_MASTER_REQUESTS + REFRESH_DATA_MASTER_REQUESTS

    @patch("bms.lltjbd_up16s.AUTO_RESET_SOC", True)
    def test_trigger_soc_reset_with_multiple_refresh_data_sets_soc_once(
        self,
        battery_slave: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        with serial_communication_patches(mock_serial_port) as mock_read_serialport_data:
            battery_slave.test_connection()
            battery_slave.trigger_soc_reset()
            battery_slave.refresh_data()
            battery_slave.refresh_data()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == TEST_CONNECTION_SLAVE_REQUESTS + [
            SET_SOC_TO_100_ADDR2_REQUEST
        ] + REFRESH_DATA_SLAVE_REQUESTS * 2

    @patch("bms.lltjbd_up16s.AUTO_RESET_SOC", True)
    def test_trigger_soc_reset_failure_retries_only_max_set_soc_times(
        self,
        battery_slave: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        with serial_communication_patches(mock_serial_port) as mock_read_serialport_data:
            battery_slave.test_connection()
            battery_slave.trigger_soc_reset()
            battery_slave.refresh_data()
            battery_slave.refresh_data()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == TEST_CONNECTION_SLAVE_REQUESTS + [
            [SET_SOC_TO_100_ADDR2_REQUEST] * MAX_SET_SOC_RETRIES
        ] + REFRESH_DATA_SLAVE_REQUESTS * 2

    def test_callback_soc_reset_to(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
    ) -> None:
        with serial_communication_patches(mock_serial_port) as mock_read_serialport_data:
            battery_master.test_connection()
            battery_master.callback_soc_reset_to(None, 98)
            battery_master.refresh_data()

        assert [call[0][1] for call in mock_read_serialport_data.call_args_list] == TEST_CONNECTION_MASTER_REQUESTS + [
            SET_SOC_TO_98_ADDR1_REQUEST
        ] + REFRESH_DATA_MASTER_REQUESTS


# =============================================================================
# Tests for command availability logic
# =============================================================================


class TestCommandAvailability:
    """Tests for command availability tracking."""

    def test_unknown_on_success_becomes_available(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
        fresh_shared_data: SharedData,
    ) -> None:
        """Command should be marked available after successful response."""
        availability = fresh_shared_data.get_command_availability(1, PackParams1)
        assert availability.status == CommandAvailability.Status.UNKNOWN

        with serial_communication_patches(mock_serial_port):
            battery_master.read_and_populate_pack_params_1(mock_serial_port)

        availability = fresh_shared_data.get_command_availability(1, PackParams1)
        assert availability.status == CommandAvailability.Status.AVAILABLE

    def test_unknown_before_max_retries_is_reached_stays_unknown(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
        fresh_shared_data: SharedData,
    ) -> None:
        with serial_communication_patches(
            mock_serial_port,
            responses=[None] * MAX_AVAILABILITY_RETRIES,
        ):
            for _ in range(MAX_AVAILABILITY_RETRIES - 1):
                battery_master.send_request_and_parse_response(mock_serial_port, PackParams1)

        availability = fresh_shared_data.get_command_availability(1, PackParams1)
        assert availability.status == CommandAvailability.Status.UNKNOWN

    def test_unknown_after_max_retries_becomes_unavailable(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
        fresh_shared_data: SharedData,
    ) -> None:
        """Command should be marked unavailable after max retries with no response."""
        with serial_communication_patches(
            mock_serial_port,
            responses=[None] * MAX_AVAILABILITY_RETRIES,
        ):
            for _ in range(MAX_AVAILABILITY_RETRIES):
                battery_master.send_request_and_parse_response(mock_serial_port, PackParams1)

        availability = fresh_shared_data.get_command_availability(1, PackParams1)
        assert availability.status == CommandAvailability.Status.UNAVAILABLE

    def test_unavailable_command_is_skipped(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
        fresh_shared_data: SharedData,
    ) -> None:
        """Commands marked unavailable should not be sent."""
        availability = fresh_shared_data.get_command_availability(1, PackParams1)
        availability.status = CommandAvailability.Status.UNAVAILABLE

        with serial_communication_patches(mock_serial_port) as mock_read_serialport_data:
            result = battery_master.send_request_and_parse_response(mock_serial_port, PackParams1)

        assert result is None
        mock_read_serialport_data.assert_not_called()

    def test_pack_status_always_available(
        self,
        fresh_shared_data: SharedData,
    ) -> None:
        """PackStatus should always be treated as available (default status)."""
        availability = fresh_shared_data.get_command_availability(1, PackStatus)
        assert availability.status == CommandAvailability.Status.AVAILABLE

    def test_availability_isolated_per_address(
        self,
        fresh_shared_data: SharedData,
    ) -> None:
        """SharedData should maintain separate availability per address."""
        availability_1 = fresh_shared_data.get_command_availability(1, PackParams1)
        availability_2 = fresh_shared_data.get_command_availability(2, PackParams1)

        availability_1.status = CommandAvailability.Status.AVAILABLE

        assert availability_2.status == CommandAvailability.Status.UNKNOWN


# =============================================================================
# Tests for interference detection and retry logic
# =============================================================================


class TestCheckForInterference:
    """Tests for check_for_interference()"""

    def test_check_for_interference_without_interference_returns_false(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
        termios_settings_ok: List[int],
    ) -> None:
        with patch("termios.tcgetattr", return_value=termios_settings_ok):
            result = battery_master.check_for_interference(mock_serial_port)

        assert result is False

    def test_check_for_interference_baud_rate_changed_returns_true(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
        termios_settings_interference: List[int],
    ) -> None:
        with patch("termios.tcgetattr", return_value=termios_settings_interference):
            result = battery_master.check_for_interference(mock_serial_port)

        assert result is True


class TestOpenSerialConnectionWithRetryOnInterference:
    """Tests for open_serial_connection_with_retry_on_interference()"""

    def test_on_interference_retries_until_success(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
        termios_settings_ok: List[int],
        termios_settings_interference: List[int],
    ) -> None:
        call_count = [0]

        def mock_fn(ser: Any) -> bool:
            call_count[0] += 1
            return call_count[0] >= 3

        interference_sequence = [
            termios_settings_interference,
            termios_settings_interference,
            termios_settings_ok,
        ]

        with patch("serial.Serial") as mock_serial_class:
            mock_serial_class.return_value.__enter__.return_value = mock_serial_port
            with patch("termios.tcgetattr", side_effect=interference_sequence):
                with patch("time.sleep") as mock_sleep:
                    result = battery_master.open_serial_connection_with_retry_on_interference(mock_fn)

        assert result is True
        assert call_count[0] == 3
        assert mock_sleep.call_count == 2

    def test_on_non_interference_failures_stops_after_max_non_interference_retries(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
        termios_settings_ok: List[int],
    ) -> None:
        call_count = [0]

        def mock_fn(ser: Any) -> bool:
            call_count[0] += 1
            return False

        with patch("serial.Serial") as mock_serial_class:
            mock_serial_class.return_value.__enter__.return_value = mock_serial_port
            with patch("termios.tcgetattr", return_value=termios_settings_ok):
                with patch("time.sleep") as mock_sleep:
                    result = battery_master.open_serial_connection_with_retry_on_interference(mock_fn, max_non_interference_retries=3)

        assert result is False
        assert call_count[0] == 3
        assert mock_sleep.call_count == 2

    def test_on_persistent_interference_retries_until_deadline(
        self,
        battery_master: LltJbd_Up16s,
        mock_serial_port: MagicMock,
        termios_settings_ok: List[int],
    ) -> None:
        """Should stop retrying after max non-interference failures."""
        call_count = [0]

        def mock_fn(ser: Any) -> bool:
            call_count[0] += 1
            return False

        with patch("serial.Serial") as mock_serial_class:
            mock_serial_class.return_value.__enter__.return_value = mock_serial_port
            with patch("termios.tcgetattr", return_value=termios_settings_ok):
                with patch("time.sleep") as mock_sleep:
                    with patch("time.monotonic", side_effect=[0, 1, 2, MAX_INTERFERENCE_RETRY_SECONDS + 1]):
                        result = battery_master.open_serial_connection_with_retry_on_interference(mock_fn, max_non_interference_retries=3)

        assert result is False
        assert call_count[0] == 2
        assert mock_sleep.call_count == 2


# =============================================================================
# parse_frame() tests
# =============================================================================


class TestParseFrame:
    """Tests for parse_frame()"""

    @pytest.mark.parametrize(
        "response,cmd,should_succeed",
        [
            (PACK_STATUS_ADDR2_RESPONSE, bms.lltjbd_up16s.PackStatus, False),
            (PACK_STATUS_ADDR1_RESPONSE, bms.lltjbd_up16s.IndividualPackStatus, False),
            (bytes.fromhex("0178100010a000"), bms.lltjbd_up16s.PackStatus, False),
            (bytes.fromhex("0178100010a000010000"), bms.lltjbd_up16s.PackStatus, False),
            (bytes.fromhex("0178100010a00001000000"), bms.lltjbd_up16s.PackStatus, False),
            (PACK_STATUS_ADDR1_RESPONSE, bms.lltjbd_up16s.PackStatus, True),
        ],
        ids=["wrong_address", "wrong_func_code", "header_too_short", "payload_or_crc_too_short", "crc_mismatch", "valid"],
    )
    def test_parse_frame_validation(
        self,
        battery_master: LltJbd_Up16s,
        response: bytes,
        cmd: Type[bms.lltjbd_up16s.CommandT],
        should_succeed: bool,
    ) -> None:
        """Test frame validation for various error conditions."""
        result = battery_master.parse_frame(response, cmd)
        assert (result is not None) == should_succeed


# =============================================================================
# serial_connection() tests
# =============================================================================


class TestSerialConnection:
    """Tests for serial_connection()"""

    def test_serial_exception_yields_none(self, battery_master: LltJbd_Up16s) -> None:
        """Serial exception should yield None instead of raising."""
        with patch("serial.Serial") as mock_serial_class:
            mock_serial_class.side_effect = Exception("This exception in the logs is normal as long as the test passes")

            with battery_master.serial_connection() as ser:
                assert ser is None

    def test_successful_serial_connection(self, battery_master: LltJbd_Up16s) -> None:
        """Successful connection should yield serial object."""
        mock_ser = MagicMock()

        with patch("serial.Serial") as mock_serial_class:
            mock_serial_class.return_value.__enter__.return_value = mock_ser

            with battery_master.serial_connection() as ser:
                assert ser is mock_ser
