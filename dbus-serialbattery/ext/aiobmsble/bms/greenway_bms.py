"""Module to support Greenway BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from enum import IntEnum
from functools import cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, b2str, crc_sum


class MsgT(IntEnum):
    """Message types in Greenway BMS data stream."""

    TEMP = 0x8
    VOLTAGE = 0x9
    CURRENT = 0xA
    SOC = 0xD
    SOH = 0xE
    CYC_CHRG = 0xF
    STATUS = 0x16
    CYCLES = 0x17
    DCAP = 0x18
    DVOL = 0x19
    VERSION = 0x1A
    MDATE = 0x1B
    WDATE = 0x1C
    RTC = 0x1D
    MANUF = 0x20
    BMS_TYPE = 0x21
    CELL_TYPE = 0x22
    SERIAL = 0x23
    CELL_VOLTAGES1 = 0x24
    CELL_VOLTAGES2 = 0x25


class BMS(BaseBMS):
    """Greenway BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Greenway",
        "default_model": "BMS",
    }
    _HEAD_CMD: Final[bytes] = b"\x46\x16\x01"
    _HEAD_RSP: Final[bytes] = b"\x47\x16\x01"
    _LEN_POS: Final[int] = 4
    _MIN_LEN: Final[int] = 6
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 0, 4, False, lambda x: x / 1000, MsgT.VOLTAGE),
        BMSDp("current", 0, 4, True, lambda x: x / 1000, MsgT.CURRENT),
        BMSDp("battery_level", 0, 4, False, idx=MsgT.SOC),
        BMSDp("battery_health", 0, 4, False, idx=MsgT.SOH),
        BMSDp("cycles", 0, 4, False, idx=MsgT.CYCLES),
        BMSDp("cycle_charge", 0, 4, False, lambda x: x / 1000, MsgT.CYC_CHRG),
        BMSDp("design_capacity", 0, 4, False, lambda x: x // 1000, MsgT.DCAP),
        BMSDp("problem_code", 2, 8, False, idx=MsgT.STATUS),
    )
    _INIT_SET: Final[frozenset[int]] = frozenset(
        (MsgT.VERSION, MsgT.MANUF, MsgT.CELL_TYPE, MsgT.SERIAL)
    )
    _MSG_SET: Final[frozenset[int]] = frozenset(
        [field.idx for field in _FIELDS]
        + [MsgT.TEMP, MsgT.CELL_VOLTAGES1, MsgT.CELL_VOLTAGES2]
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
        self._msg: dict[int, bytes] = {}
        self._exp_reply: int = 0

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "oui": "C4:A9:B8",
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
        ]

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
        return "fff1"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""

        for addr in (MsgT.VERSION, MsgT.MANUF, MsgT.BMS_TYPE, MsgT.SERIAL):
            self._exp_reply = addr
            await self._await_msg(BMS._cmd(addr))

        ver: bytes = self._msg[MsgT.VERSION][BMS._LEN_POS + 1 : -1]
        return BMSInfo(
            manufacturer=b2str(self._msg[MsgT.MANUF][BMS._LEN_POS + 1 : -1]),
            model=b2str(self._msg[MsgT.BMS_TYPE][BMS._LEN_POS + 1 : -1]),
            serial_number=b2str(self._msg[MsgT.SERIAL][BMS._LEN_POS + 1 : -1]),
            fw_version=b2str(ver[4:]),
            hw_version=f"{ver[3]}.{ver[2]}",
            sw_version=f"{ver[1]}.{ver[0]}",
        )

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if data.startswith(BMS._HEAD_RSP):  # check for beginning of frame
            self._frame.clear()

        self._frame.extend(data)

        if (
            len(self._frame) < BMS._MIN_LEN
            or len(self._frame) < self._frame[BMS._LEN_POS] + BMS._MIN_LEN
        ):
            return

        if not self._frame.startswith(BMS._HEAD_RSP):
            self._log.debug("incorrect frame header")
            self._frame.clear()
            return

        if self._frame[3] != self._exp_reply:
            self._log.debug(
                "received message type 0x%X, expected 0x%X",
                self._frame[3],
                self._exp_reply,
            )
            return

        if not self._check_integrity(
            self._frame, crc_sum, slice(None, -1), slice(-1, None)
        ):
            return

        self._msg[self._frame[3]] = bytes(self._frame)
        self._msg_event.set()

    @staticmethod
    @cache
    def _cmd(addr: int) -> bytes:
        """Assemble a Greenway BMS command."""
        assert addr > 0 and addr < 256
        length: Final[dict[int, int]] = {
            8: 32,
            9: 4,
            10: 4,
            13: 4,
            14: 4,
            15: 4,
            16: 4,
            20: 4,
            22: 16,
            23: 4,
            24: 4,
            25: 4,
            26: 8,
            27: 4,
            28: 4,
            29: 6,
            30: 6,
            32: 16,
            33: 32,
            34: 16,
            35: 32,
            36: 32,
            37: 32,
            38: 14,
        }

        return bytes(
            [
                *BMS._HEAD_CMD,
                addr,
                length[addr],
                0xFF & (sum(BMS._HEAD_CMD) + addr + length.get(addr, 0)),
            ]
        )

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        for addr in BMS._MSG_SET:
            self._exp_reply = addr
            await self._await_msg(BMS._cmd(addr))

        result: BMSSample = self._decode_data(
            BMS._FIELDS, self._msg, byteorder="little", start=BMS._LEN_POS + 1
        )
        for msg_type in (MsgT.CELL_VOLTAGES1, MsgT.CELL_VOLTAGES2):
            result.setdefault("cell_voltages", []).extend(
                self._cell_voltages(
                    self._msg[msg_type],
                    cells=16,
                    start=BMS._LEN_POS + 1,
                    divider=1000,
                    byteorder="little",
                )
            )

        result.setdefault("temp_values", []).extend(
            self._temp_values(
                self._msg[MsgT.TEMP],
                values=7,
                start=BMS._LEN_POS + 1,
                size=1,
            )
        )

        self._msg.clear()
        self._msg_event.clear()
        return result
