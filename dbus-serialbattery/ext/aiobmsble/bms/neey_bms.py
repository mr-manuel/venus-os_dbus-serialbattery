"""Module to support Neey smart BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from collections.abc import Callable
from functools import cache
from struct import unpack_from
from typing import Any, Final, Literal

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSInfo, BMSSample, BMSValue, MatcherPattern
from aiobmsble.basebms import BaseBMS, b2str, crc_sum


class BMS(BaseBMS):
    """Neey smart BMS class implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Neey", "default_model": "Balancer"}
    _BT_MODULE_MSG: Final = b"\x41\x54\x0d\x0a"  # AT\r\n from BLE module
    _HEAD_RSP: Final = b"\x55\xaa\x11\x01"  # start, dev addr, read cmd
    _HEAD_CMD: Final = b"\xaa\x55\x11\x01"  # cmd header (endianness!)
    _TAIL: Final[int] = 0xFF  # end of message
    _TYPE_POS: Final[int] = 4  # frame type is right after the header
    _MIN_FRAME: Final[int] = 10  # header length
    _FIELDS: Final[tuple[tuple[BMSValue, int, str, Callable[[int], Any]], ...]] = (
        ("voltage", 201, "<f", lambda x: round(x, 3)),
        ("delta_voltage", 209, "<f", lambda x: round(x, 3)),
        ("problem_code", 216, "B", lambda x: x if x in {1, 3, 7, 8, 9, 10, 11} else 0),
        ("balancer", 216, "B", lambda x: (x == 0x5)),
        ("balance_current", 217, "<f", lambda x: round(x, 3)),
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive)
        self._msg: bytes = b""
        self._bms_info: dict[str, str] = {}
        self._exp_len: int = BMS._MIN_FRAME
        self._valid_reply: int = 0x02

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": pattern,
                "service_uuid": normalize_uuid_str("fee7"),
                "connectable": True,
            }
            for pattern in ("EK-*", "GW-*")
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("ffe0"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "ffe1"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "ffe1"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        self._valid_reply = 0x01
        await self._await_msg(self._cmd(b"\x01"))
        self._valid_reply = 0x02
        return {
            "model": b2str(self._msg[8:24]),
            "hw_version": b2str(self._msg[24:32]),
            "sw_version": b2str(self._msg[32:40]),
        }

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Retrieve BMS data update."""

        if (
            len(self._frame) >= self._exp_len
            or not self._frame.startswith(BMS._HEAD_RSP)
        ) and data.startswith(BMS._HEAD_RSP):
            self._frame.clear()
            self._exp_len = max(
                int.from_bytes(data[6:8], byteorder="little", signed=False),
                BMS._MIN_FRAME,
            )

        self._frame += data

        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data
        )

        # verify that data is long enough
        if len(self._frame) < self._exp_len:
            return

        if not self._frame.startswith(BMS._HEAD_RSP):
            self._log.debug("incorrect frame start.")
            return

        # trim message in case oversized
        if len(self._frame) > self._exp_len:
            self._log.debug("wrong data length (%i): %s", len(self._frame), self._frame)
            del self._frame[self._exp_len :]

        if self._frame[-1] != BMS._TAIL:
            self._log.debug("incorrect frame end.")
            return

        # check that message type is expected
        if self._frame[BMS._TYPE_POS] != self._valid_reply:
            self._log.debug(
                "unexpected message type 0x%X (length %i): %s",
                self._frame[BMS._TYPE_POS],
                len(self._frame),
                self._frame,
            )
            return

        if (crc := crc_sum(self._frame[:-2])) != self._frame[-2]:
            self._log.debug("invalid checksum 0x%X != 0x%X", self._frame[-2], crc)
            return

        self._msg = bytes(self._frame)
        self._msg_event.set()

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Initialize RX/TX characteristics and protocol state."""
        await super()._init_connection(char_notify)
        await self._fetch_device_info()
        self._valid_reply = 0x02  # cell information

    @staticmethod
    @cache
    def _cmd(cmd: bytes, reg: int = 0, value: list[int] | None = None) -> bytes:
        """Assemble a Neey BMS command."""
        value = [] if value is None else value
        assert len(value) <= 11
        frame: bytearray = bytearray(  # 0x14 frame length
            [*BMS._HEAD_CMD, cmd[0], reg & 0xFF, 0x14, *value]
        ) + bytes(11 - len(value))
        frame += bytes([crc_sum(frame), BMS._TAIL])
        return bytes(frame)

    @staticmethod
    def _cell_voltages(
        data: bytes,
        *,
        cells: int,
        start: int,
        size: int = 2,
        gap: int = 0,
        byteorder: Literal["little", "big"] = "little",
        divider: int = 1,
    ) -> list[float]:
        """Parse cell voltages from message."""
        return [
            round(value, 3)
            for idx in range(cells)
            if (value := unpack_from("<f", data, start + idx * size)[0])
        ]

    @staticmethod
    def _temp_sensors(data: bytes, sensors: int) -> list[int | float]:
        return [
            round(unpack_from("<f", data, 221 + idx * 4)[0], 2)
            for idx in range(sensors)
        ]

    @staticmethod
    def _conv_data(data: bytes) -> BMSSample:
        """Return BMS data from status message."""
        result: BMSSample = {}
        for key, idx, fmt, func in BMS._FIELDS:
            result[key] = func(unpack_from(fmt, data, idx)[0])

        return result

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        if not self._msg_event.is_set() or self._msg[4] != 0x02:
            # request cell info (only if data is not constantly published)
            self._log.debug("requesting cell info")
            await self._await_msg(data=BMS._cmd(b"\x02"))

        data: BMSSample = self._conv_data(self._msg)
        data["temp_values"] = BMS._temp_sensors(self._msg, 2)

        data["cell_voltages"] = BMS._cell_voltages(
            self._msg, cells=24, start=9, byteorder="little", size=4
        )

        self._msg_event.clear()  # clear event for next update
        return data
