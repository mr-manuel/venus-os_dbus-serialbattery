"""Module to support Pro BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Pro BMS Smart Shunt class implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Pro BMS", "default_model": "Smart Shunt"}
    _HEAD: Final[bytes] = b"\x55\xaa"
    _MIN_LEN: Final[int] = 5
    _INIT_RESP: Final[int] = 0x03
    _RT_DATA: Final[int] = 0x04

    _CMD_INIT: Final[bytes] = b"\x0a\x01\x01\x55\x80\x04\x07\x7f\x64\x8e\x68\x2b"
    _CMD_HWID: Final[bytes] = b"\x07\x01\x01\x55\x80\x40\x00\x00\x95"
    _CMD_DATA_STREAM: Final[bytes] = b"\x07\x01\x01\x55\x80\x42\x00\x00\x97"
    # command that triggers data streaming (fct. 0x43)
    _CMD_TRIGGER_DATA: Final[bytes] = b"\x09\x01\x01\x55\x80\x43\x00\x00\x12\x00\x84"

    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 8, 2, False, lambda x: x / 100),
        BMSDp(
            "current",
            12,
            4,
            False,
            lambda x: ((x & 0xFFFF) / 1000) * (-1 if (x >> 24) & 0x80 else 1),
        ),
        BMSDp("problem_code", 15, 4, False, lambda x: x & 0x7F),
        BMSDp(
            "temp_values",
            16,
            3,
            False,
            lambda x: [((x & 0xFFFF) / 10) * (-1 if x >> 16 else 1)],
        ),
        BMSDp("cycle_charge", 20, 4, False, lambda x: x / 100),
        BMSDp("battery_level", 24, 1, False),
        BMSDp("power", 32, 4, False, lambda x: x / 100),
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive)
        self._valid_reply: int = BMS._RT_DATA
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            MatcherPattern(
                local_name="Pro BMS",
                service_uuid=BMS.uuid_services()[0],
                connectable=True,
            )
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

    # async def _fetch_device_info(self) -> BMSInfo: unknown, use default

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        self._log.debug("RX BLE data: %s", data)

        if len(data) < BMS._MIN_LEN or not data.startswith(BMS._HEAD):
            self._log.debug("invalid packet header")
            return

        if data[3] != self._valid_reply:
            self._log.debug("unexpected response (type 0x%X)", data[3])
            return

        _exp_len: Final[int] = data[2] + BMS._MIN_LEN
        if len(data) != _exp_len:
            self._log.debug("incorrect frame length: %i != %i).", len(data), _exp_len)
            return

        self._msg = bytes(data)
        self._msg_event.set()

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Initialize RX/TX characteristics and protocol state."""
        await super()._init_connection()
        self._valid_reply = BMS._INIT_RESP

        # Send initialization command and await response
        await self._await_msg(BMS._HEAD + BMS._CMD_INIT)
        for cmd in (BMS._CMD_HWID, BMS._CMD_DATA_STREAM, BMS._CMD_TRIGGER_DATA):
            await self._await_msg(BMS._HEAD + cmd, wait_for_notify=False)

        self._valid_reply = BMS._RT_DATA

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        try:
            # Wait for new data packet
            await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)
        except TimeoutError:
            await self.disconnect()
            raise

        result: BMSSample = BMS._decode_data(
            BMS._FIELDS, self._msg, byteorder="little"
        )
        result["power"] = result.get("power", 0) * (
            -1 if result.get("current", 0) < 0 else 1
        )
        self._msg_event.clear()
        self._frame.clear()
        return result
