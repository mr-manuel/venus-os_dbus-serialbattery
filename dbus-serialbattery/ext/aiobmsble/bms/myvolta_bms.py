"""Module to support MyVolta BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from enum import IntEnum
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS
from aiobmsble.utils import StreamParser


class MsgT(IntEnum):
    """Message types in MyVolta BMS data stream."""

    METRICS = 0x0
    INFO = 0x1
    CELL_VOLTAGES1 = 0x11
    CELL_VOLTAGES2 = 0x12
    CELL_VOLTAGES3 = 0x13
    CELL_VOLTAGES4 = 0x14
    CELL_TEMPS1 = 0x21
    CELL_TEMPS2 = 0x22
    ADD_INFO = 0x23
    TEMPS3 = 0x24
    TEMPS4 = 0x25
    TEMPS5 = 0x26
    TEMPS6 = 0x27
    TEMPS7 = 0x28
    TEMPS8 = 0x29


class BMS(BaseBMS):
    """MyVolta BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Voltagen Power Solutions",
        "default_model": "MyVolta BLE HW",
    }
    _PRB_MASK: Final[int] = 0xFF00FFFF  # mask to extract problem code (byte 3 unused)
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 0, 2, False, lambda x: x / 1000, MsgT.METRICS),
        BMSDp("current", 2, 2, True, lambda x: x / 100, MsgT.METRICS),
        BMSDp("battery_level", 6, 2, False, lambda x: x / 10, MsgT.METRICS),
        BMSDp("heater", 2, 2, False, lambda x: bool(x & 0x8000), MsgT.INFO),
        BMSDp("problem_code", 1, 4, False, lambda x: x & BMS._PRB_MASK, MsgT.INFO),
    )

    _MSG_SET: Final[frozenset[int]] = frozenset(
        {
            MsgT.METRICS,
            MsgT.INFO,
        }
        | set(range(MsgT.CELL_VOLTAGES1, MsgT.CELL_VOLTAGES4 + 1))
        | set(range(MsgT.TEMPS3, MsgT.TEMPS5 + 1))
    )  # set of message types that must be received for a complete update

    def __init__(
        self,
        ble_device: BLEDevice,
        keep_alive: bool = True,
        secret: str = "",
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive, secret, logger_name)
        self._msg: dict[int, bytes] = {}
        self.parser: Final[StreamParser] = StreamParser(DLE=0x05, STX=0x55, ETX=0x04)

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": "VPS-*",
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("00035b03-58e6-07dd-021a-08123a000300"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "00035b03-58e6-07dd-021a-08123a000301"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        raise NotImplementedError

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not (frame := self.parser.feed(data)):
            return

        if len(frame) < 9:
            self._log.debug("frame too short: %s", frame)
            return

        # check command ID and pack ID, data length
        if frame[0] != 0x1 or frame[2] != 0x2 or frame[6] != 0x8:
            self._log.debug("incorrect frame header: %s", frame)
            return

        if not self._check_integrity(
            frame, self._crc_sum, slice(1, -1), slice(-1, None)
        ):
            return

        self._msg[frame[1]] = frame
        self._log.debug("received message type 0x%X", frame[1])
        if BMS._MSG_SET.issubset(self._msg.keys()):
            self._msg_event.set()

    def _crc_sum(self, data: bytes | bytearray) -> int:
        """Calculate checksum as simple sum of all bytes modulo 256."""
        return 0xFF ^ (sum(data) % 256)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)

        result: BMSSample = self._decode_data(
            BMS._FIELDS, self._msg, byteorder="little", start=7
        )
        for msg_type in (
            MsgT.CELL_VOLTAGES1,
            MsgT.CELL_VOLTAGES2,
            MsgT.CELL_VOLTAGES3,
            MsgT.CELL_VOLTAGES4,
        ):
            result.setdefault("cell_voltages", []).extend(
                self._cell_voltages(
                    self._msg[msg_type],
                    cells=4,
                    start=7,
                    divider=1000,
                    byteorder="little",
                )
            )

        for msg_type in (
            # MsgT.CELL_TEMPS1, MsgT.CELL_TEMPS2,
            MsgT.TEMPS3,
            MsgT.TEMPS4,
            MsgT.TEMPS5,
            # MsgT.TEMPS6, MsgT.TEMPS7, MsgT.TEMPS8,
        ):
            result.setdefault("temp_values", []).extend(
                self._temp_values(
                    self._msg[msg_type],
                    values=4,
                    start=7,
                    divider=10,
                    byteorder="little",
                )
            )

        self._msg.clear()
        self._msg_event.clear()
        return result
