"""Module to support PACEEX BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, b2str, crc_modbus


class BMS(BaseBMS):
    """PACEEX BMS implementation."""

    # TODO: implement multi battery pack

    INFO: BMSInfo = {
        "default_manufacturer": "PeiCheng Technology",
        "default_model": "PACEEX Smart BMS",
    }
    _HEAD: Final[bytes] = b"\x9a"
    _TAIL: Final[bytes] = b"\x9d"
    _FRM_TYPE: Final[slice] = slice(1, 7)
    _MIN_LEN: Final[int] = 11  # minimal frame length
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("current", 1, 4, True, lambda x: x / 100),
        BMSDp("voltage", 5, 4, False, lambda x: x / 100),
        BMSDp("cycle_charge", 9, 4, False, lambda x: x / 100),
        BMSDp("design_capacity", 13, 4, False, lambda x: x // 100),
        BMSDp("battery_level", 21, 1, False),
        BMSDp("battery_health", 22, 1, False),
        BMSDp("pack_count", 0, 1, False),
        BMSDp("cycles", 23, 4, False),
        # BMSDp("problem_code", 1, 9, False, lambda x: x & 0xFFFF00FF00FF0000FF, EIC_LEN),
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._valid_reply: bytes = b""  # expected reply type
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [{"local_name": "PC-????", "connectable": True}]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("fff0"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "fff1"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "fff2"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        result: BMSInfo = BMSInfo()
        await self._await_msg(self._cmd(b"\x00\x00\x00\x02\x00\x00"))
        length: int = self._msg[8]
        result["serial_number"] = b2str(self._msg[9 : 9 + length])
        await self._await_msg(self._cmd(b"\x00\x00\x00\x01\x00\x00"))
        result["sw_version"] = b2str(self._msg[10 : 10 + self._msg[9]])
        result["hw_version"] = b2str(self._msg[65 : 65 + self._msg[64]])
        return result

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(BMS._HEAD):
            self._log.debug("incorrect SOF")
            return

        if len(data) < BMS._MIN_LEN or len(data) != BMS._MIN_LEN + data[7]:
            self._log.debug("incorrect frame length")
            return

        if (crc := crc_modbus(data[:-3])) != int.from_bytes(
            data[-3:-1], byteorder="big"
        ):
            self._log.debug(
                "invalid checksum 0x%X != 0x%X",
                int.from_bytes(data[-3:-1], byteorder="big"),
                crc,
            )
            return

        if data[BMS._FRM_TYPE] != self._valid_reply:
            self._log.debug("unexpected response")
            return

        self._msg = bytes(data)
        self._msg_event.set()

    @staticmethod
    @cache
    def _cmd(cmd: bytes, data: bytes = b"") -> bytes:
        """Assemble a Pace BMS command."""
        frame: bytearray = bytearray(BMS._HEAD) + cmd + len(data).to_bytes(1) + data
        frame += int.to_bytes(crc_modbus(frame), 2, byteorder="big") + BMS._TAIL
        return bytes(frame)

    async def _await_msg(
        self,
        data: bytes,
        char: int | str | None = None,
        wait_for_notify: bool = True,
        max_size: int = 0,
    ) -> None:
        """Send data to the BMS and wait for valid reply notification."""

        self._valid_reply = data[BMS._FRM_TYPE]  # expected reply type
        await super()._await_msg(data, char, wait_for_notify, max_size)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._await_msg(BMS._cmd(b"\x00\x00\x0a\x00\x00\x00"))
        result: BMSSample = BMS._decode_data(
            BMS._FIELDS, self._msg, byteorder="big", start=8
        )
        await self._await_msg(BMS._cmd(b"\x00\x00\x0a\x02\x00\x00", b"\x01\x01"))
        result["cell_count"] = self._msg[11]
        result["cell_voltages"] = BMS._cell_voltages(
            self._msg, cells=result["cell_count"], start=12, gap=2
        )
        result["temp_values"] = BMS._temp_values(
            self._msg,
            values=result["cell_count"],
            start=14,
            gap=2,
            signed=False,
            offset=2731,
            divider=10,
        )
        return result
