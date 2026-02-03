"""Module to support Gobel Power BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/

This module implements support for Gobel Power BMS devices that use Modbus RTU
protocol over Bluetooth Low Energy.
"""

from functools import cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, b2str, crc_modbus


class BMS(BaseBMS):
    """Gobel Power BLE BMS class implementation using Modbus RTU over BLE."""

    INFO: BMSInfo = {"default_manufacturer": "Gobel Power", "default_model": "BLE BMS"}

    # Modbus constants
    _SLAVE_ADDR: Final[int] = 0x01
    _FUNC_READ: Final[int] = 0x03

    # Frame constants
    _MIN_FRAME_LEN: Final[int] = 5  # addr + func + len + 2*crc minimum
    _MAX_CELLS: Final[int] = 32
    _MAX_TEMP: Final[int] = 8

    # Each command: (slave_addr, func_code, start_address, register_count)
    _RD_CMD_STATUS: Final[tuple[int, int, int, int]] = (
        _SLAVE_ADDR,
        _FUNC_READ,
        0x0000,
        0x003B,  # 59 registers
    )
    _RD_CMD_DEV_INFO: Final[tuple[int, int, int, int]] = (
        _SLAVE_ADDR,
        _FUNC_READ,
        0x00AA,
        0x0023,  # 35 registers
    )

    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("current", 0, 2, True, lambda x: x / 100),
        BMSDp("voltage", 2, 2, False, lambda x: x / 100),
        BMSDp("battery_level", 4, 2, False),
        BMSDp("battery_health", 6, 2, False),
        BMSDp("cycle_charge", 8, 2, False, lambda x: x / 100),
        BMSDp("design_capacity", 10, 2, False, lambda x: x // 100),
        BMSDp("cycles", 14, 2, False),
        BMSDp("problem_code", 16, 6, False),
        BMSDp("chrg_mosfet", 28, 2, False, lambda x: bool(x & 0x4000)),
        BMSDp("dischrg_mosfet", 28, 2, False, lambda x: bool(x & 0x8000)),
        BMSDp("cell_count", 30, 2, False, lambda x: x & 0xFF),
        BMSDp("temp_sensors", 92, 2, False, lambda x: x & 0xFF),
    )

    _CELLV_START: Final[int] = 35
    _TEMP_START: Final[int] = 97
    _TEMP_MOS_OFFSET: Final[int] = 117

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive)
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [MatcherPattern(local_name="BMS-????????????????*", connectable=True)]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return ("00002760-08c2-11e1-9073-0e8ac72e1001",)

    @staticmethod
    def uuid_rx() -> str:
        """Return UUID of characteristic that provides notification/read property."""
        return "00002760-08c2-11e1-9073-0e8ac72e0002"

    @staticmethod
    def uuid_tx() -> str:
        """Return UUID of characteristic that provides write property."""
        return "00002760-08c2-11e1-9073-0e8ac72e0001"

    @staticmethod
    @cache
    def _cmd(addr: int, func: int, start: int, regs: int) -> bytes:
        """Build Modbus read command with CRC (cached)."""
        cmd: Final[bytes] = (
            addr.to_bytes(1, "big")
            + func.to_bytes(1, "big")
            + start.to_bytes(2, "big")
            + regs.to_bytes(2, "big")
        )
        return cmd + crc_modbus(cmd).to_bytes(2, "little")

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug(
            "RX BLE data (%s): %s", "start" if not self._frame else "cnt.", data
        )

        # Start of a new frame - check for valid Modbus response header
        if len(data) >= 2 and data[0] == BMS._SLAVE_ADDR:
            # Check if it's a valid read response or error response
            if data[1] == BMS._FUNC_READ or data[1] == (BMS._FUNC_READ | 0x80):
                # Start new frame (clear any old data)
                self._frame = bytearray(data)
            else:
                self._log.debug("unexpected function code: 0x%02X", data[1])
                return
        elif self._frame:
            # Continuation of existing frame
            self._frame.extend(data)
        else:
            self._log.debug("unexpected data, ignoring: %s", data.hex(" "))
            return

        # Check if we have enough data for minimum frame
        if len(self._frame) < BMS._MIN_FRAME_LEN:
            return

        # Check for error response
        if self._frame[1] == (BMS._FUNC_READ | 0x80):
            self._log.warning("Modbus error response: 0x%02X", self._frame[2])
            self._frame.clear()
            return

        # Get expected frame length from byte count field
        expected_len: Final[int] = BMS._MIN_FRAME_LEN + self._frame[2]

        if len(self._frame) < expected_len:
            return

        # Truncate if we received extra data
        del self._frame[expected_len:]

        # Verify CRC
        received_crc: Final[int] = int.from_bytes(self._frame[-2:], byteorder="little")
        calculated_crc: Final[int] = crc_modbus(self._frame[:-2])

        if received_crc != calculated_crc:
            self._log.debug(
                "invalid CRC: 0x%04X != 0x%04X", received_crc, calculated_crc
            )
            self._frame.clear()
            return

        self._log.debug("valid frame received: %d bytes", len(self._frame))
        self._msg = bytes(self._frame)
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._await_msg(BMS._cmd(*BMS._RD_CMD_STATUS))

        if self._msg[2] != BMS._RD_CMD_STATUS[3] * 2:
            self._log.debug(
                "incorrect response: %d bytes, expected %d",
                self._msg[2],
                BMS._RD_CMD_STATUS[3] * 2,
            )
            return {}

        result: BMSSample = BMS._decode_data(
            BMS._FIELDS, self._msg, byteorder="big", start=3
        )

        result["cell_voltages"] = BMS._cell_voltages(
            self._msg,
            cells=min(result.get("cell_count", 0), BMS._MAX_CELLS),
            start=BMS._CELLV_START,
            byteorder="big",
        )

        result["temp_values"] = BMS._temp_values(
            self._msg,
            values=min(result.get("temp_sensors", 0), BMS._MAX_TEMP),
            start=BMS._TEMP_START,
            byteorder="big",
            signed=True,
            divider=10,
        )

        # Append MOSFET temperature if valid (0xFFFF indicates no sensor)
        mos_temp: list[int | float] = BMS._temp_values(
            self._msg,
            values=1,
            start=BMS._TEMP_MOS_OFFSET,
            byteorder="big",
            signed=True,
            divider=10,
        )
        if mos_temp[0] != -0.1:
            result["temp_values"].append(mos_temp[0])

        return result

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch device info from BMS via Modbus."""
        # First get standard BLE device info (may contain generic values)
        info: BMSInfo = await super()._fetch_device_info()

        # Read device info registers via Modbus
        try:
            await self._await_msg(BMS._cmd(*BMS._RD_CMD_DEV_INFO))
        except TimeoutError:
            return info

        if len(self._msg) >= 65:
            info.update(
                {
                    "sw_version": b2str(self._msg[3:21]),
                    "serial_number": b2str(self._msg[23:43]),
                    "model_id": b2str(self._msg[43:63]),
                }
            )

        return info
