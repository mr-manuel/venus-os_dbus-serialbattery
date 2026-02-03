"""Module to support RoyPow BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """RoyPow BMS implementation."""

    INFO: BMSInfo = {"default_manufacturer": "RoyPow", "default_model": "smart BMS"}
    _HEAD: Final[bytes] = b"\xea\xd1\x01"
    _TAIL: Final[int] = 0xF5
    _BT_MODULE_MSG: Final[bytes] = b"AT+STAT\r\n"  # AT cmd from BLE module
    _MIN_LEN: Final[int] = len(_HEAD) + 1
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("battery_level", 7, 1, False, idx=0x4),
        BMSDp("voltage", 47, 2, False, lambda x: x / 100, 0x4),
        BMSDp(
            "current",
            6,
            3,
            False,
            lambda x: (x & 0xFFFF) * (-1 if (x >> 16) & 0x1 else 1) / 100,
            0x3,
        ),
        BMSDp("problem_code", 9, 3, False, idx=0x3),
        BMSDp(
            "cycle_charge",
            24,
            4,
            False,
            lambda x: ((x & 0xFFFF0000) | (x & 0xFF00) >> 8 | (x & 0xFF) << 8) / 1000,
            0x4,
        ),
        BMSDp("runtime", 30, 2, False, lambda x: x * 60, 0x4),
        BMSDp("temp_sensors", 13, 1, False, idx=0x3),
        BMSDp("cycles", 9, 2, False, idx=0x4),
        BMSDp("chrg_mosfet", 24, 1, False, lambda x: bool(x & 0x4), 0x3),
        BMSDp("dischrg_mosfet", 24, 1, False, lambda x: bool(x & 0x2), 0x3),
    )
    _CMDS: Final = frozenset({field.idx for field in _FIELDS}) | {0x2}

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._msg: dict[int, bytes] = {}
        self._exp_len: int = 0

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "service_uuid": BMS.uuid_services()[0],
                "manufacturer_id": manufacturer_id,
                "connectable": True,
            }
            for manufacturer_id in (0x01A8, 0x0B31, 0x8AFB)
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

    # async def _fetch_device_info(self) -> BMSInfo: unknown, use default

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        if not (data := data.removeprefix(BMS._BT_MODULE_MSG)):
            self._log.debug("filtering AT cmd")
            return

        if (
            data.startswith(BMS._HEAD)
            and not self._frame.startswith(BMS._HEAD)
            and len(data) > len(BMS._HEAD)
        ):
            self._exp_len = data[len(BMS._HEAD)]
            self._frame.clear()

        self._frame += data
        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data
        )

        if not self._frame.startswith(BMS._HEAD):
            self._frame.clear()
            return

        # verify that data is long enough
        if len(self._frame) < BMS._MIN_LEN + self._exp_len:
            return

        end_idx: Final[int] = BMS._MIN_LEN + self._exp_len - 1
        if self._frame[end_idx] != BMS._TAIL:
            self._log.debug("incorrect EOF: %s", self._frame)
            self._frame.clear()
            return

        if (crc := BMS._crc(self._frame[len(BMS._HEAD) : end_idx - 1])) != self._frame[
            end_idx - 1
        ]:
            self._log.debug(
                "invalid checksum 0x%X != 0x%X", self._frame[end_idx - 1], crc
            )
            self._frame.clear()
            return

        self._msg[self._frame[5]] = bytes(self._frame)
        self._frame.clear()
        self._msg_event.set()

    @staticmethod
    def _crc(frame: bytes | bytearray) -> int:
        """Calculate XOR of all frame bytes."""
        crc: int = 0
        for b in frame:
            crc ^= b
        return crc

    @staticmethod
    @cache
    def _cmd(cmd: bytes) -> bytes:
        """Assemble a RoyPow BMS command."""
        data: Final[bytes] = bytes([len(cmd) + 2, *cmd])
        return BMS._HEAD + data + bytes([BMS._crc(data), BMS._TAIL])

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        self._frame.clear()
        self._msg.clear()
        for cmd in BMS._CMDS:
            await self._await_msg(BMS._cmd(bytes([0xFF, cmd])))

        if not BMS._CMDS.issubset(self._msg.keys()):
            self._log.debug("Incomplete data set %s", self._msg.keys())
            raise ValueError("BMS data incomplete.")

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg)

        # remove remaining runtime if battery is charging
        if result.get("runtime") == 0xFFFF * 60:
            result.pop("runtime", None)

        result["cell_voltages"] = BMS._cell_voltages(
            self._msg.get(0x2, b""),
            cells=max(0, (len(self._msg.get(0x2, b"")) - 11) // 2),
            start=9,
        )
        result["temp_values"] = BMS._temp_values(
            self._msg.get(0x3, b""),
            values=result.get("temp_sensors", 0),
            start=14,
            size=1,
            signed=False,
            offset=40,
        )

        return result
