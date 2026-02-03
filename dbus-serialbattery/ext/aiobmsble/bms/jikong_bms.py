"""Module to support Jikong smart BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from functools import cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSMode, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, b2str, crc_sum, lstr2int


class BMS(BaseBMS):
    """Jikong smart BMS class implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Jikong", "default_model": "smart BMS"}
    HEAD_RSP: Final = bytes([0x55, 0xAA, 0xEB, 0x90])  # header for responses
    HEAD_CMD: Final = bytes([0xAA, 0x55, 0x90, 0xEB])  # cmd header (endianness!)
    _READY_MSG: Final = HEAD_CMD + bytes([0xC8, 0x01, 0x01] + [0x00] * 12 + [0x44])
    _BT_MODULE_MSG: Final = bytes([0x41, 0x54, 0x0D, 0x0A])  # AT\r\n from BLE module
    TYPE_POS: Final[int] = 4  # frame type is right after the header
    INFO_LEN: Final[int] = 300
    _FIELDS: Final[tuple[BMSDp, ...]] = (  # Protocol: JK02_32S; JK02_24S has offset -32
        BMSDp("voltage", 150, 4, False, lambda x: x / 1000),
        BMSDp("current", 158, 4, True, lambda x: x / 1000),
        BMSDp("problem_code", 166, 4, False),
        BMSDp("balance_current", 170, 2, True, lambda x: x / 1000),
        BMSDp("balancer", 201, 1, False, bool),
        BMSDp("battery_level", 173, 1, False),
        BMSDp("cycle_charge", 174, 4, False, lambda x: x / 1000),
        BMSDp("cycles", 182, 4, False),
        BMSDp("battery_health", 190, 1, False),
        BMSDp("chrg_mosfet", 198, 1, False, bool),
        BMSDp("dischrg_mosfet", 199, 1, False, bool),
        BMSDp("temp_sensors", 214, 2, True),
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive)
        self._msg: bytes = b""
        self._char_write_handle: int = -1
        self._sw_version: int = 0
        self._prot_offset: int = 0
        self._valid_reply: int = 0x02
        self._bms_ready: bool = False

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
                "manufacturer_id": 0x0B65,
            },
        ]

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return [normalize_uuid_str("ffe0")]

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
        self._valid_reply = 0x03
        await self._await_msg(self._cmd(b"\x97"), char=self._char_write_handle)
        self._valid_reply = 0x02
        return {
            "model": b2str(self._msg[6:22]),
            "hw_version": b2str(self._msg[22:30]),
            "sw_version": b2str(self._msg[30:38]),
            "name": b2str(self._msg[46:62]),
            "serial_number": b2str(self._msg[86:94]),
        }

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Retrieve BMS data update."""

        if data.startswith(BMS._BT_MODULE_MSG):
            self._log.debug("filtering AT cmd")
            if not (data := data.removeprefix(BMS._BT_MODULE_MSG)):
                return

        if (
            len(self._frame) >= self.INFO_LEN
            and (data.startswith((BMS.HEAD_RSP, BMS.HEAD_CMD)))
        ) or not self._frame.startswith(BMS.HEAD_RSP):
            self._frame.clear()

        self._frame += data

        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data
        )

        # verify that data is long enough
        if (
            len(self._frame) < BMS.INFO_LEN and self._frame.startswith(BMS.HEAD_RSP)
        ) or len(self._frame) < BMS.TYPE_POS + 1:
            return

        # check that message type is expected
        if self._frame[BMS.TYPE_POS] != self._valid_reply:
            self._log.debug(
                "unexpected message type 0x%X (length %i): %s",
                self._frame[BMS.TYPE_POS],
                len(self._frame),
                self._frame,
            )
            return

        # trim AT\r\n message from the end
        if self._frame.endswith(BMS._BT_MODULE_MSG):
            self._log.debug("trimming AT cmd")
            self._frame = self._frame.removesuffix(BMS._BT_MODULE_MSG)

        # set BMS ready if msg is attached to last responses (v19.05)
        if self._frame[BMS.INFO_LEN :].startswith(BMS._READY_MSG):
            self._log.debug("BMS ready.")
            self._bms_ready = True
            self._frame = self._frame[: BMS.INFO_LEN]

        # trim message in case oversized
        if len(self._frame) > BMS.INFO_LEN:
            self._log.debug("wrong data length (%i): %s", len(self._frame), self._frame)
            self._frame = self._frame[: BMS.INFO_LEN]

        if (crc := crc_sum(self._frame[:-1])) != self._frame[-1]:
            self._log.debug("invalid checksum 0x%X != 0x%X", self._frame[-1], crc)
            return

        self._msg = bytes(self._frame)
        self._msg_event.set()

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Initialize RX/TX characteristics and protocol state."""
        char_notify_handle: int = -1
        self._char_write_handle = -1
        self._bms_ready = False

        for service in self._client.services:
            for char in service.characteristics:
                self._log.debug(
                    "discovered %s (#%i): %s", char.uuid, char.handle, char.properties
                )
                if char.uuid == normalize_uuid_str(
                    BMS.uuid_rx()
                ) or char.uuid == normalize_uuid_str(BMS.uuid_tx()):
                    if "notify" in char.properties:
                        char_notify_handle = char.handle
                    if (
                        "write" in char.properties
                        or "write-without-response" in char.properties
                    ):
                        self._char_write_handle = char.handle
        if char_notify_handle == -1 or self._char_write_handle == -1:
            self._log.debug("failed to detect characteristics.")
            await self._client.disconnect()
            raise ConnectionError(f"Failed to detect characteristics from {self.name}.")
        self._log.debug(
            "using characteristics handle #%i (notify), #%i (write).",
            char_notify_handle,
            self._char_write_handle,
        )

        await super()._init_connection()

        # wait for BMS ready (0xC8)
        _bms_info: BMSInfo = await self._fetch_device_info()
        self._sw_version = lstr2int(_bms_info.get("sw_version", "0"))
        self._log.debug("device information: %s", _bms_info)
        self._prot_offset = -32 if self._sw_version < 11 else 0
        if not self._bms_ready:
            self._valid_reply = 0xC8  # BMS ready confirmation
            await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)
        self._valid_reply = 0x02  # cell information

    @staticmethod
    @cache
    def _cmd(cmd: bytes, value: list[int] | None = None) -> bytes:
        """Assemble a Jikong BMS command."""
        value = [] if value is None else value
        assert len(value) <= 13
        frame: bytearray = bytearray(
            [*BMS.HEAD_CMD, cmd[0], len(value), *value]
        ) + bytes(13 - len(value))
        frame.append(crc_sum(frame))
        return bytes(frame)

    def _temp_pos(self) -> list[tuple[int, int]]:
        if self._sw_version >= 14:
            return [(0, 144), (1, 162), (2, 164), (3, 254), (4, 256), (5, 258)]
        if self._sw_version >= 11:
            return [(0, 144), (1, 162), (2, 164), (3, 254)]
        return [(0, 130), (1, 132), (2, 134)]

    @staticmethod
    def _temp_sensors(
        data: bytes, temp_pos: list[tuple[int, int]], mask: int
    ) -> list[int | float]:
        return [
            (value / 10)
            for idx, pos in temp_pos
            if mask & (1 << idx)
            and (
                value := int.from_bytes(
                    data[pos : pos + 2], byteorder="little", signed=True
                )
            )
            != -2000
        ]

    @staticmethod
    def _conv_data(data: bytes, offs: int, sw_majv: int) -> BMSSample:
        """Return BMS data from status message."""

        result: BMSSample = BMS._decode_data(
            BMS._FIELDS, data, byteorder="little", start=offs
        )
        result["cell_count"] = int.from_bytes(
            data[70 + (offs >> 1) : 74 + (offs >> 1)], byteorder="little"
        ).bit_count()

        result["delta_voltage"] = (
            int.from_bytes(
                data[76 + (offs >> 1) : 78 + (offs >> 1)], byteorder="little"
            )
            / 1000
        )

        if sw_majv >= 15:
            result["battery_mode"] = (
                BMSMode(data[280 + offs])
                if data[280 + offs] in BMSMode
                else BMSMode.UNKNOWN
            )

        return result

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        if not self._msg_event.is_set() or self._msg[4] != 0x02:
            # request cell info (only if data is not constantly published)
            self._log.debug("requesting cell info")
            await self._await_msg(
                data=BMS._cmd(b"\x96"), char=self._char_write_handle
            )

        data: BMSSample = self._conv_data(
            self._msg, self._prot_offset, self._sw_version
        )
        data["temp_values"] = BMS._temp_sensors(
            self._msg, self._temp_pos(), data.get("temp_sensors", 0)
        )

        data["problem_code"] = (
            ((data.get("problem_code", 0)) >> 16)
            if self._prot_offset
            else (data.get("problem_code", 0) & 0xFFFF)
        )

        data["cell_voltages"] = BMS._cell_voltages(
            self._msg,
            cells=data.get("cell_count", 0),
            start=6,
            byteorder="little",
        )

        self._msg_event.clear()
        return data
