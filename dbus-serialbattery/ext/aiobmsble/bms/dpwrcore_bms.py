"""Module to support D-powercore smart BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from enum import IntEnum
from functools import cache
from string import hexdigits
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS


class Cmd(IntEnum):
    """BMS operation codes."""

    UNLOCKACC = 0x32
    UNLOCKREJ = 0x33
    LEGINFO1 = 0x60
    LEGINFO2 = 0x61
    CELLVOLT = 0x62
    UNLOCK = 0x64
    UNLOCKED = 0x65
    GETINFO = 0xA0


class BMS(BaseBMS):
    """D-powercore smart BMS class implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "D-powercore",
        "default_model": "smart BMS",
    }
    _PAGE_LEN: Final[int] = 20
    _MAX_CELLS: Final[int] = 32
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 6, 2, False, lambda x: x / 10, Cmd.LEGINFO1),
        BMSDp("current", 8, 2, True, idx=Cmd.LEGINFO1),
        BMSDp("battery_level", 14, 1, False, idx=Cmd.LEGINFO1),
        BMSDp("cycle_charge", 12, 2, False, lambda x: x / 1000, Cmd.LEGINFO1),
        BMSDp(
            "temp_values",
            12,
            2,
            False,
            lambda x: [round(x / 10 - 273.15, 3)],
            Cmd.LEGINFO2,
        ),
        BMSDp(
            "cell_count", 6, 1, False, lambda x: min(x, BMS._MAX_CELLS), Cmd.CELLVOLT
        ),
        BMSDp("cycles", 8, 2, False, idx=Cmd.LEGINFO2),
        BMSDp("problem_code", 15, 1, False, lambda x: x & 0xFF, Cmd.LEGINFO1),
    )
    _CMDS: Final = frozenset({Cmd(field.idx) for field in _FIELDS})

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive)
        assert self._ble_device.name is not None  # required for unlock
        self._msg: dict[int, bytes] = {}

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": pattern,
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
            for pattern in ("DXB-*", "TBA-*")
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("fff0"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "fff4"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "fff3"

    # async def _fetch_device_info(self) -> BMSInfo: use default

    async def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        self._log.debug("RX BLE data: %s", data)

        if len(data) != BMS._PAGE_LEN:
            self._log.debug("invalid page length (%i)", len(data))
            return

        # ignore ACK responses
        if data[0] & 0x80:
            self._log.debug("ignore acknowledge message")
            return

        # acknowledge received frame
        await self._await_msg(bytes([data[0] | 0x80]) + data[1:], wait_for_notify=False)

        page: Final[int] = data[1] >> 4
        if page == 1:
            self._frame.clear()

        self._frame += data[2 : data[0] + 2]

        self._log.debug("(%s): %s", "start" if page == 1 else "cnt.", data)

        if page == data[1] & 0xF:  # check if last page
            if (crc := BMS._crc(self._frame[3:-4])) != int.from_bytes(
                self._frame[-4:-2], byteorder="big"
            ):
                self._log.debug(
                    "incorrect checksum: 0x%X != 0x%X",
                    int.from_bytes(self._frame[-4:-2], byteorder="big"),
                    crc,
                )
                self._frame.clear()
                self._msg = {}  # reset invalid data
                return

            self._msg[self._frame[3]] = bytes(self._frame)
            self._msg_event.set()

    @staticmethod
    def _crc(data: bytearray) -> int:
        return sum(data) + 8

    @staticmethod
    @cache
    def _cmd(cmd: Cmd, data: bytes) -> bytes:
        frame: bytearray = bytearray([cmd.value, 0x00, 0x00]) + data
        checksum: Final[int] = BMS._crc(frame)
        frame = (
            bytearray(b"\x3a\x03\x05")
            + frame
            + checksum.to_bytes(2, byteorder="big")
            + b"\x0d\x0a"
        )
        frame = bytearray([len(frame) + 2, 0x11]) + frame
        frame += bytes(BMS._PAGE_LEN - len(frame))

        return bytes(frame)

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Connect to the BMS and setup notification if not connected."""
        await super()._init_connection()

        # unlock BMS if not TBA version
        if self.name.startswith("TBA-"):
            return

        if not all(c in hexdigits for c in self.name[-4:]):
            self._log.debug("unable to unlock BMS")
            return

        pwd = int(self.name[-4:], 16)
        await self._await_msg(
            BMS._cmd(
                Cmd.UNLOCK,
                bytes([(pwd >> 8) & 0xFF, pwd & 0xFF]),
            ),
            wait_for_notify=False,
        )

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        for request in BMS._CMDS:
            await self._await_msg(self._cmd(request, b""))

        if not BMS._CMDS.issubset(set(self._msg.keys())):
            self._log.debug("Incomplete data set %s", self._msg.keys())
            raise ValueError("BMS data incomplete.")

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg)
        result["cell_voltages"] = BMS._cell_voltages(
            self._msg[Cmd.CELLVOLT],
            cells=result.get("cell_count", 0),
            start=7,
        )

        self._msg.clear()
        return result
