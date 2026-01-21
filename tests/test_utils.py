"""
Tests for methods in utils.py. Currently only read_serialport_data() is tested.
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from utils import read_serialport_data
import serial


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_serial() -> MagicMock:
    """Create a mock serial port with default configuration."""
    mock_ser = MagicMock(spec=serial.Serial)
    type(mock_ser).in_waiting = PropertyMock(return_value=0)
    return mock_ser


@pytest.fixture
def mock_serial_with_waiting() -> MagicMock:
    """Create a mock serial port with data waiting."""
    mock_ser = MagicMock(spec=serial.Serial)
    type(mock_ser).in_waiting = PropertyMock(return_value=4)
    return mock_ser


# =============================================================================
# Tests for read_serialport_data()
# =============================================================================


class TestReadSerialportData:
    """Tests for read_serialport_data()"""

    @pytest.mark.parametrize(
        "payload_length_size,payload_length_pos,response_hex,extra_length",
        [
            # Message: [Header] [Length] [Payload] [Checksum]
            ("B", 2, "AABB 03 112233 CC", 4),
            ("H", 1, "AA 0004 11223344 CC", 4),
            # 4-byte length field at pos 0
            ("I", 0, "00000002 1122 CC", 5),
            ("B", 0, "02 1122 CC", 2),
            ("B", 1, "AA 00 CC", 3),
            ("B", 1, "AAFF" + "00" * 255 + "CC", 3),
        ],
        ids=["one_byte_length", "two_byte_length", "four_byte_length", "length_at_pos_0", "empty_payload", "max_single_byte_payload_length"],
    )
    def test_variable_response_length_returns_response(
        self,
        mock_serial: MagicMock,
        payload_length_size: str,
        payload_length_pos: int,
        response_hex: str,
        extra_length: int,
    ) -> None:
        request = bytearray([0x01])
        response = bytearray.fromhex(response_hex)
        mock_serial.read.return_value = response

        with patch("time.monotonic", side_effect=[0.0, 0.1]):
            with patch("utils.sleep"):
                result = read_serialport_data(
                    ser=mock_serial,
                    request=request,
                    timeout_seconds=1.0,
                    extra_length=extra_length,
                    payload_length_pos=payload_length_pos,
                    payload_length_size=payload_length_size,
                )

        assert result == response
        mock_serial.reset_input_buffer.assert_called_once()
        mock_serial.write.assert_called_once_with(request)

    @pytest.mark.parametrize(
        "length_fixed,response_hex",
        [
            (3, "112233"),
            (1, "11"),
        ],
        ids=["fixed_length", "minimal_fixed_length"],
    )
    def test_fixed_response_length_ignores_other_length_args_and_returns_response(self, mock_serial: MagicMock, length_fixed: int, response_hex: str) -> None:
        """Test reading when length_fixed is provided, ignoring length byte in data."""
        request = bytearray([0x01])
        response = bytearray.fromhex(response_hex)
        mock_serial.read.return_value = response

        with patch("time.monotonic", side_effect=[0.0, 0.1]):
            with patch("utils.sleep"):
                result = read_serialport_data(
                    ser=mock_serial,
                    request=request,
                    timeout_seconds=1.0,
                    extra_length=3,
                    payload_length_pos=2,
                    payload_length_size="H",
                    length_fixed=length_fixed,
                )

        assert result == response
        mock_serial.reset_input_buffer.assert_called_once()
        mock_serial.write.assert_called_once_with(request)

    @pytest.mark.parametrize(
        "read_side_effect",
        [
            ([bytearray([0xAA]), bytearray([0x00, 0x02]), bytearray([0x11, 0x22]), bytearray([0xCC])]),
            ([b"", b"", bytearray([0xAA, 0x00, 0x02, 0x11, 0x22, 0xCC])]),
            ([bytearray([0xAA, 0x00]), bytearray([0x02, 0x11, 0x22, 0xCC])]),
        ],
        ids=["multiple_chunks", "empty_chunks_before_data", "length_field_split_between_two_chunks"],
    )
    def test_multiple_chunks_returns_response(
        self,
        mock_serial: MagicMock,
        read_side_effect: list,
    ) -> None:
        mock_serial.read.side_effect = read_side_effect

        with patch("time.monotonic", side_effect=[0.0, 0.1, 0.2, 0.3, 0.4]):
            with patch("utils.sleep") as mock_sleep:
                result = read_serialport_data(
                    ser=mock_serial,
                    request=bytearray([0x01]),
                    timeout_seconds=1.0,
                    extra_length=4,
                    payload_length_pos=1,
                    payload_length_size="H",
                )

        expected = bytearray([0xAA, 0x00, 0x02, 0x11, 0x22, 0xCC])
        assert mock_sleep.call_count > 0
        assert result == expected

    @pytest.mark.parametrize(
        "read_side_effect,time_side_effect",
        [
            ([b""], [0.0, 0.5, 1.5]),
            ([bytearray([0xAA]), b"", b""], [0.0, 0.3, 0.6, 1.5]),
            ([bytearray([0xAA, 0xBB, 0x0A]), bytearray([0x11]), b""], [0.0, 0.3, 0.6, 1.5]),
        ],
        ids=["no_data", "incomplete_header", "incomplete_payload"],
    )
    def test_timeout_returns_none(
        self,
        mock_serial: MagicMock,
        read_side_effect: list,
        time_side_effect: list,
    ) -> None:
        mock_serial.read.side_effect = read_side_effect

        with patch("time.monotonic", side_effect=time_side_effect):
            with patch("utils.sleep"):
                result = read_serialport_data(
                    ser=mock_serial,
                    request=bytearray([0x01]),
                    timeout_seconds=1.0,
                    extra_length=4,
                    payload_length_pos=2,
                    payload_length_size="B",
                )

        assert result is None

    @pytest.mark.parametrize(
        "exception_source,exception_type",
        [
            ("write", serial.SerialException("Write failed")),
            ("read", serial.SerialException("Read failed")),
            ("reset_input_buffer", Exception("Buffer reset failed")),
            ("read", RuntimeError("Unexpected error")),
        ],
        ids=["write_serial_exc", "read_serial_exc", "reset_buffer_exc", "read_generic_exc"],
    )
    def test_exception_returns_none_and_logs(
        self,
        mock_serial: MagicMock,
        exception_source: str,
        exception_type: Exception,
    ) -> None:
        getattr(mock_serial, exception_source).side_effect = exception_type

        time_patch = patch("time.monotonic", return_value=0.0) if exception_source == "read" else patch("time.monotonic")

        with time_patch:
            with patch("utils.logger") as mock_logger:
                result = read_serialport_data(
                    ser=mock_serial,
                    request=bytearray([0x01]),
                    timeout_seconds=1.0,
                    extra_length=4,
                    payload_length_pos=2,
                    payload_length_size="B",
                )

        assert result is None
        mock_logger.exception.assert_called_once()
