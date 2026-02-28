"""Module to support EG4 BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, BMSValue, MatcherPattern
from aiobmsble.basebms import BaseBMS, crc_modbus


class BMS(BaseBMS):
    """EG4 BMS implementation."""

    INFO: BMSInfo = {"default_manufacturer": "EG4 electronics", "default_model": "LL"}
    _HEAD: Final[bytes] = b"\x01\x03"  # dev addr, fct code (read)
    _MAX_CELLS: Final[int] = 16
    _MAX_TEMP: Final[int] = 6
    _MIN_LEN: Final[int] = 5
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 3, 2, False, lambda x: x / 100),
        BMSDp("current", 5, 2, True, lambda x: x / 10),
        BMSDp("battery_health", 49, 2, False),
        BMSDp("battery_level", 51, 2, False),
        BMSDp("cycle_charge", 45, 2, False, lambda x: x / 10),
        BMSDp("cycles", 61, 4, False),
        BMSDp("cell_count", 75, 2, False),
        BMSDp("design_capacity", 77, 2, False, lambda x: x // 10),
        BMSDp("temperature", 39, 2, True),
        BMSDp("problem_code", 55, 6, False),
        BMSDp("balancer", 79, 2, False),
    )
    _OPT_FIELDS: Final[tuple[BMSValue, ...]] = (
        "cycle_charge",
        "cycles",
        "design_capacity",
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._msg: bytes = b""
        self._exp_len: int = 0

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "service_uuid": BMS.uuid_services()[0],
                "manufacturer_id": 0x6F80,
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> tuple[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("1000"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "1002"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "1001"

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
            self._frame = bytearray()

        self._frame += data
        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data
        )

        # verify that data is long enough
        if len(self._frame) < self._exp_len:
            return

        del self._frame[self._exp_len :]

        if (crc := crc_modbus(self._frame[:-2])) != int.from_bytes(
            self._frame[-2:], byteorder="little"
        ):
            self._log.debug(
                "invalid checksum 0x%X != 0x%X",
                int.from_bytes(self._frame[-2:], byteorder="little"),
                crc,
            )
            return

        self._msg = bytes(self._frame)
        self._msg_event.set()

    @staticmethod
    @cache
    def _cmd(address: int, count: int) -> bytes:
        """Assemble a EG4 BMS command."""
        frame: bytearray = bytearray(BMS._HEAD)
        frame += int.to_bytes(address, 2, byteorder="big")
        frame += int.to_bytes(count, 2, byteorder="big")
        frame += int.to_bytes(crc_modbus(frame), 2, byteorder="little")
        return bytes(frame)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        await self._await_msg(BMS._cmd(0x0, 0x27))

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg)
        for field in BMS._OPT_FIELDS:
            if not result.get(field):
                del result[field]

        result["cell_voltages"] = BMS._cell_voltages(
            self._msg, cells=min(result.get("cell_count", 0), BMS._MAX_CELLS), start=7
        )
        result["temp_values"] = BMS._temp_values(
            self._msg, values=BMS._MAX_TEMP, start=69, size=1
        )
        return result
