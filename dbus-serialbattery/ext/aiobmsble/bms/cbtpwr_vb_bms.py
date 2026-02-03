"""Module to support CBT Power VB series BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import cache
from string import hexdigits
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, lrc_modbus


class BMS(BaseBMS):
    """CBT Power VB series battery class implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Creabest", "default_model": "VB series"}
    _HEAD: Final[bytes] = b"\x7e"
    _TAIL: Final[bytes] = b"\x0d"
    _CMD_VER: Final[int] = 0x11  # TX protocol version
    _RSP_VER: Final[int] = 0x22  # RX protocol version
    _LEN_POS: Final[int] = 9
    _MIN_LEN: Final[int] = _LEN_POS + 3 + len(_HEAD) + len(_TAIL) + 4
    _MAX_LEN: Final[int] = 255
    _CELL_POS: Final[int] = 6

    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 2, 2, False, lambda x: x / 10),
        BMSDp("current", 0, 2, True, lambda x: x / 10),
        BMSDp("battery_level", 4, 2, False, lambda x: min(x, 100)),
        BMSDp("cycles", 7, 2, False),
        BMSDp("problem_code", 15, 6, False, lambda x: x & 0xFFF000FF000F),
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
            {  # Creabest
                "local_name": "VB?????????",
                "service_uuid": normalize_uuid_str("fff0"),
                "connectable": True,
            },
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("ffe0"), normalize_uuid_str("ffe5"))

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "ffe4"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "ffe9"

    # async def _fetch_device_info(self) -> BMSInfo: unknown, use default

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""

        if len(data) > BMS._LEN_POS + 4 and data.startswith(BMS._HEAD):
            self._frame = bytearray()
            try:
                length: Final[int] = int(data[BMS._LEN_POS : BMS._LEN_POS + 4], 16)
                self._exp_len = length & 0xFFF
                if BMS.lencs(length) != length >> 12:
                    self._exp_len = 0
                    self._log.debug("incorrect length checksum.")
            except ValueError:
                self._exp_len = 0

        self._frame += data
        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data
        )

        if len(self._frame) < self._exp_len + BMS._MIN_LEN:
            return

        if not self._frame.endswith(BMS._TAIL):
            self._log.debug("incorrect EOF: %s", data)
            self._frame.clear()
            return

        if not all(chr(c) in hexdigits for c in self._frame[1:-1]):
            self._log.debug("incorrect frame encoding.")
            self._frame.clear()
            return

        if (ver := bytes.fromhex(self._frame[1:3].decode())) != BMS._RSP_VER.to_bytes():
            self._log.debug("unknown response frame version: 0x%X", int.from_bytes(ver))
            self._frame.clear()
            return

        if (crc := lrc_modbus(self._frame[1:-5])) != int(self._frame[-5:-1], 16):
            self._log.debug(
                "invalid checksum 0x%X != 0x%X", crc, int(self._frame[-5:-1], 16)
            )
            self._frame.clear()
            return

        self._msg = bytes.fromhex(self._frame.strip(BMS._HEAD + BMS._TAIL).decode())
        self._msg_event.set()

    @staticmethod
    def lencs(length: int) -> int:
        """Calculate the length checksum."""
        return (sum((length >> (i * 4)) & 0xF for i in range(3)) ^ 0xF) + 1 & 0xF

    @staticmethod
    @cache
    def _cmd(cmd: int, dev_id: int = 1, data: bytes = b"") -> bytes:
        """Assemble a Seplos VB series command."""
        assert len(data) <= 0xFFF
        cdat: Final[bytes] = data + int.to_bytes(dev_id)
        frame = bytearray([BMS._CMD_VER, dev_id, 0x46, cmd])
        frame.extend(
            int.to_bytes(len(cdat) * 2 + (BMS.lencs(len(cdat) * 2) << 12), 2, "big")
        )
        frame.extend(cdat)
        frame.extend(int.to_bytes(lrc_modbus(frame.hex().upper().encode()), 2, "big"))
        return BMS._HEAD + frame.hex().upper().encode() + BMS._TAIL

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        await self._await_msg(BMS._cmd(0x42))
        result: BMSSample = {"cell_count": self._msg[BMS._CELL_POS]}
        temp_pos: Final[int] = BMS._CELL_POS + result.get("cell_count", 0) * 2 + 1
        result["temp_sensors"] = self._msg[temp_pos]
        result["cell_voltages"] = BMS._cell_voltages(
            self._msg, cells=result.get("cell_count", 0), start=BMS._CELL_POS + 1
        )
        result["temp_values"] = BMS._temp_values(
            self._msg,
            values=result.get("temp_sensors", 0),
            start=temp_pos + 1,
            divider=10,
        )

        result |= BMS._decode_data(
            BMS._FIELDS,
            self._msg,
            start=temp_pos + 2 * result["temp_sensors"] + 1,
        )

        await self._await_msg(BMS._cmd(0x81, 1, b"\x01\x00"), max_size=20)
        result["design_capacity"] = (
            int.from_bytes(self._msg[6:8], byteorder="big", signed=False) // 10
        )

        return result
