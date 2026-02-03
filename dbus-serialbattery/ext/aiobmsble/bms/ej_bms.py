"""Module to support E&J Technology BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from enum import IntEnum
from string import hexdigits
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, crc_sum


class Cmd(IntEnum):
    """BMS operation codes."""

    RT = 0x2
    CAP = 0x10


class BMS(BaseBMS):
    """E&J Technology BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "E&J Technology",
        "default_model": "smart BMS",
    }
    _BT_MODULE_MSG: Final[bytes] = bytes([0x41, 0x54, 0x0D, 0x0A])  # BLE module message
    _IGNORE_CRC: Final[str] = "libattU"
    _HEAD: Final[bytes] = b"\x3a"
    _TAIL: Final[bytes] = b"\x7e"
    _MAX_CELLS: Final[int] = 16
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp(
            "current", 44, 4, False, lambda x: ((x >> 16) - (x & 0xFFFF)) / 100, Cmd.RT
        ),
        BMSDp("battery_level", 61, 1, False, idx=Cmd.RT),
        BMSDp("cycle_charge", 7, 2, False, lambda x: x / 10, Cmd.CAP),
        BMSDp(
            "temp_values", 48, 1, False, lambda x: [x - 40], Cmd.RT
        ),  # only 1st sensor relevant
        BMSDp("cycles", 57, 2, False, idx=Cmd.RT),
        BMSDp(
            "problem_code", 52, 2, False, lambda x: x & 0x0FFC, Cmd.RT
        ),  # mask status bits
        BMSDp("dischrg_mosfet", 52, 1, False, lambda x: bool(x & 0x10), Cmd.RT),
        BMSDp("chrg_mosfet", 52, 1, False, lambda x: bool(x & 0x20), Cmd.RT),
        BMSDp("balancer", 55, 2, False, int, idx=Cmd.RT),
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return (
            [  # Lithtech Energy (2x), Volthium
                MatcherPattern(local_name=pattern, connectable=True)
                for pattern in ("L-12V???AH-*", "LT-12V-*", "V-12V???Ah-*")
            ]
            + [  # Fliteboard, Electronix battery
                {
                    "local_name": "libatt*",
                    "manufacturer_id": 21320,
                    "connectable": True,
                },
                {"local_name": "SV12V*", "manufacturer_id": 33384, "connectable": True},
            ]
            + [  # LiTime
                MatcherPattern(  # LiTime based on serial #
                    local_name="LT-12???BG-A0[0-6]*",
                    manufacturer_id=m_id,
                    connectable=True,
                )
                for m_id in (33384, 22618)
            ]
            + [  # LiTime based on serial #
                {
                    "local_name": "LT-24???B-A00[0-2]*",
                    "manufacturer_id": 22618,
                    "connectable": True,
                }
            ]
        )

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return ["6e400001-b5a3-f393-e0a9-e50e24dcca9e"]

    @staticmethod
    def uuid_rx() -> str:
        """Return 128-bit UUID of characteristic that provides notification/read property."""
        return "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

    @staticmethod
    def uuid_tx() -> str:
        """Return 128-bit UUID of characteristic that provides write property."""
        return "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""

        if data.startswith(BMS._BT_MODULE_MSG):
            self._log.debug("filtering AT cmd")
            if not (data := data.removeprefix(BMS._BT_MODULE_MSG)):
                return

        if data.startswith(BMS._HEAD):  # check for beginning of frame
            self._frame.clear()

        self._frame += data

        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data
        )

        exp_frame_len: Final[int] = (
            int(self._frame[7:11], 16)
            if len(self._frame) > 10
            and all(chr(c) in hexdigits for c in self._frame[7:11])
            else 0xFFFF
        )

        if not self._frame.startswith(BMS._HEAD) or (
            not self._frame.endswith(BMS._TAIL) and len(self._frame) < exp_frame_len
        ):
            return

        if not self._frame.endswith(BMS._TAIL):
            self._log.debug("incorrect EOF: %s", data)
            self._frame.clear()
            return

        if not all(chr(c) in hexdigits for c in self._frame[1:-1]):
            self._log.debug("incorrect frame encoding.")
            self._frame.clear()
            return

        if len(self._frame) != exp_frame_len:
            self._log.debug(
                "incorrect frame length %i != %i",
                len(self._frame),
                exp_frame_len,
            )
            self._frame.clear()
            return

        if not self.name.startswith(BMS._IGNORE_CRC) and (
            crc := crc_sum(self._frame[1:-3]) ^ 0xFF
        ) != int(self._frame[-3:-1], 16):
            # libattU firmware uses no CRC, so we ignore it
            self._log.debug(
                "invalid checksum 0x%X != 0x%X", int(self._frame[-3:-1], 16), crc
            )
            self._frame.clear()
            return

        self._log.debug(
            "address: 0x%X, command 0x%X, version: 0x%X, length: 0x%X",
            int(self._frame[1:3], 16),
            int(self._frame[3:5], 16) & 0x7F,
            int(self._frame[5:7], 16),
            len(self._frame),
        )
        self._msg = bytes.fromhex(self._frame[1:-1].decode())
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        raw_data: dict[int, bytes] = {}

        # query real-time information and capacity
        for cmd in (b":000250000E03~", b":001031000E05~"):
            await self._await_msg(cmd)
            rsp: int = self._msg[1] & 0x7F
            raw_data[rsp] = self._msg
            if rsp == Cmd.RT and len(self._msg) == 0x45:
                # handle metrisun version
                self._log.debug("single frame protocol detected")
                raw_data[Cmd.CAP] = bytes(7) + self._msg[62:]
                break

        if len(raw_data) != len(list(Cmd)) or not all(raw_data.values()):
            return {}

        return self._decode_data(BMS._FIELDS, raw_data) | BMSSample(
            cell_voltages=BMS._cell_voltages(
                raw_data[Cmd.RT], cells=BMS._MAX_CELLS, start=12
            )
        )
