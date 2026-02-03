"""Module to support Wattstunde Nova BMS.

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
from aiobmsble.basebms import BaseBMS, b2str


class BMS(BaseBMS):
    """Wattstunde Nova Core BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Wattstunde",
        "default_model": "Nova Core",
    }
    _HEAD: Final[bytes] = b"\x3a"  # beginning of frame
    _TAIL: Final[bytes] = b"\x7e"  # end of frame
    _MIN_LEN: Final[int] = 238 # heater*2 + tail
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp(
            "current",
            10,
            4,
            False,
            lambda x: (x & 0x7FFF) / 1000 * (-1 if x >> 15 else 1),
        ),
        BMSDp("voltage", 18, 2, False, lambda x: x / 1000),
        BMSDp("cycles", 23, 2, False),
        BMSDp("battery_level", 25, 1, False),
        BMSDp("design_capacity", 26, 4, False, lambda x: x // 1000),
        BMSDp("cycle_charge", 30, 4, False, lambda x: x / 1000),
        BMSDp("heater", 115, 4, False, bool),
        BMSDp("problem_code", 0, 2, False, lambda x: x & 0x0FFC),
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "manufacturer_id": 28256,
                "manufacturer_data_start": [0x41],
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return [normalize_uuid_str("FFF0")]

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "FFF1"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "FFF1"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        await self._await_msg(
            self._cmd(b"\x30\x31\x35\x31\x35\x30\x30\x30\x30\x45\x46\x45")
        )
        self._msg_event.clear()
        return BMSInfo(serial_number=b2str(self._msg[91:107]))

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""

        if data.startswith(BMS._HEAD):
            self._frame.clear()

        self._frame += data

        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data
        )

        if not (self._frame.startswith(BMS._HEAD) and self._frame.endswith(BMS._TAIL)):
            return

        if len(self._frame) % 2 or len(self._frame) < BMS._MIN_LEN:
            self._log.debug("incorrect frame length (%i)", len(self._frame))
            return

        if not all(chr(c) in hexdigits for c in self._frame[1:-1]):
            self._log.debug("incorrect frame encoding.")
            self._frame.clear()
            return

        _key: Final[int] = int(self._frame[7:9], 16)
        _dec = bytes(b ^ _key for b in bytes.fromhex(self._frame[1:-3].decode("ascii")))
        # incoming frames seem to have invalid checksum, thus not checked here

        if not _dec.startswith(b"\x01\x54"):
            self._log.debug("incorrect frame type.")
            self._frame.clear()
            return

        self._msg = _dec
        self._msg_event.set()

    @staticmethod
    @cache
    def _cmd(cmd: bytes) -> bytes:
        """Assemble a Wattstunde Nova BMS command frame."""
        return BMS._HEAD + cmd + BMS._TAIL

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        if not self._msg_event.is_set():
            self._log.debug("requesting BMS data")
            await self._await_msg(
                self._cmd(b"\x30\x31\x35\x31\x35\x30\x30\x30\x30\x45\x46\x45")
            )

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg, start=44)
        result["cell_voltages"] = BMS._cell_voltages(self._msg, cells=16, start=12)
        result["temp_values"] = BMS._temp_values(
            self._msg, values=4, start=48, size=1, signed=False, offset=40
        )
        self._msg_event.clear()
        return result
