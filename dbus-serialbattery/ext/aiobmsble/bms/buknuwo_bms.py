"""Module to support Buknuwo BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern, TempSensor
from aiobmsble.basebms import BaseBMS, crc_modbus


class BMS(BaseBMS):
    """Dummy BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Buknuwo",
        "default_model": "smart battery",
    }
    _HEAD: Final[bytes] = b"\x01\x03"  # dev, read (0x03)
    _MIN_LEN: Final[int] = 5  # length of frame, including SOF and checksum
    _MAX_TEMP: Final[int] = 10  # maximum number of cell temperatures
    _PRB_MASK: Final[int] = 0xFF3FFF7F007F
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("current", 3, 2, True, lambda x: x / 100),
        BMSDp("voltage", 5, 2, False, lambda x: x / 100),
        BMSDp("battery_level", 7, 2, False),
        BMSDp("battery_health", 9, 2, False),
        BMSDp("cycle_charge", 11, 2, False, lambda x: x / 100),
        BMSDp("design_capacity", 15, 2, False, lambda x: x // 100),
        BMSDp("cycles", 17, 2, False),
        BMSDp("chrg_mosfet", 25, 1, False, lambda x: bool(x & 0x4)),
        BMSDp("dischrg_mosfet", 25, 1, False, lambda x: bool(x & 0x8)),
        BMSDp("problem_code", 21, 6, False, lambda x: x & BMS._PRB_MASK),
    )

    def __init__(
        self,
        ble_device: BLEDevice,
        keep_alive: bool = True,
        secret: str = "",
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive, secret, logger_name)
        self._exp_len: int = 0
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [{"local_name": "CDZG*", "connectable": True}]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("00002760-08c2-11e1-9073-0e8ac72e1001"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return UUID of characteristic that provides notification/read property."""
        return "00002760-08c2-11e1-9073-0e8ac72e0002"

    @staticmethod
    def uuid_tx() -> str:
        """Return UUID of characteristic that provides write property."""
        return "00002760-08c2-11e1-9073-0e8ac72e0001"

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""

        if (
            len(data) > BMS._MIN_LEN
            and data.startswith(BMS._HEAD)
            and len(self._frame) >= self._exp_len
        ):
            self._exp_len = BMS._MIN_LEN + data[2]
            self._frame.clear()

        self._frame.extend(data)
        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data
        )

        if len(self._frame) < 3 or len(self._frame) < self._frame[2] + BMS._MIN_LEN:
            return

        if not self._check_integrity(
            self._frame,
            crc_modbus,
            slice(None, -2),
            slice(-2, None),
            "little",
        ):
            return

        self._msg = bytes(self._frame)
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._await_msg(BMS._cmd_modbus(dev_id=0x1, addr=0x0, count=0xD))
        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg)

        await self._await_msg(BMS._cmd_modbus(dev_id=0x1, addr=0x39, count=0x1))
        result["temp_values"] = BMS._temp_values(
            self._msg, start=3, divider=10, types=(TempSensor.T.MOSFET,)
        )

        await self._await_msg(
            BMS._cmd_modbus(dev_id=0x1, addr=0x2E, count=BMS._MAX_TEMP + 1)
        )
        result["temp_sensors"] = int.from_bytes(self._msg[3:5], "big")
        result["temp_values"].extend(
            BMS._temp_values(
                self._msg,
                values=result.get("temp_sensors", 0),
                start=5,
                divider=10,
                types=(TempSensor.T.CELL,) * result.get("temp_sensors", 0),
            )
        )

        return result
