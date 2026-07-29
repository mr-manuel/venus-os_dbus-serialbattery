"""Module to support ABC BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import contextlib
from functools import lru_cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, b2str, crc8


class BMS(BaseBMS):
    """ABC BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Chunguang Song",
        "default_model": "ABC-BMS",
    }
    _HEAD_CMD: Final[int] = 0xEE
    _HEAD_RESP: Final[bytes] = b"\xcc"
    _INFO_LEN: Final[int] = 0x14
    _EXP_REPLY: Final[dict[int, set[int]]] = {  # wait for these replies
        0xC0: {0xF1},
        0xC1: {0xF0, 0xF2},
        0xC2: {0xF0, 0xF3, 0xF4},  # 4 cells per F4 message
        0xC3: {0xF5, 0xF6, 0xF7, 0xF8, 0xFA},
        0xC4: {0xF9},
    }
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("temp_sensors", 4, 1, False, idx=0xF2),
        BMSDp("voltage", 2, 3, False, lambda x: x / 1000, 0xF0),
        BMSDp("current", 5, 3, True, lambda x: x / 1000, 0xF0),
        BMSDp("design_capacity", 8, 3, False, lambda x: x // 1000, 0xF0),
        BMSDp("battery_level", 16, 1, False, idx=0xF0),
        BMSDp("cycle_charge", 11, 3, False, lambda x: x / 1000, 0xF0),
        BMSDp("cycles", 14, 2, False, idx=0xF0),
        BMSDp(  # only first bit per byte is used
            "problem_code",
            2,
            16,
            False,
            lambda x: sum(((x >> (i * 8)) & 1) << i for i in range(16)),
            0xF9,
        ),
        BMSDp("chrg_mosfet", 2, 1, False, bool, 0xF2),
        BMSDp("dischrg_mosfet", 3, 1, False, bool, 0xF2),
        BMSDp("heater", 8, 1, False, bool, 0xF3),
        BMSDp("balancer", 10, 1, False, idx=0xF3),
    )
    _RESPS: Final[set[int]] = {field.idx for field in _FIELDS} | {0xF4}  # cell voltages

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
        self._exp_reply: set[int] = set()

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": pattern,
                "service_uuid": normalize_uuid_str("fff0"),
                "connectable": True,
            }
            for pattern in ("ABC-*", "SOK-*", "NB-*", "Hoover")
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
        return "ffe2"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        info: BMSInfo = await super()._fetch_device_info()
        self._exp_reply = BMS._EXP_REPLY[0xC0].copy()
        await self._await_msg(BMS._cmd(0xC0))
        info.update({"model": b2str(self._msg[0xF1][2:-1])})
        return info

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(BMS._HEAD_RESP):
            self._log.debug("incorrect SOF")
            return

        if len(data) != BMS._INFO_LEN:
            self._log.debug("incorrect frame length")
            return

        if not self._check_integrity(data, crc8, slice(None, -1), slice(-1, None)):
            return

        if data[1] == 0xF4 and 0xF4 in self._msg:
            # expand cell voltage frame with all parts
            self._msg[0xF4] = bytes(self._msg[0xF4][:-2] + data[2:])
        else:
            self._msg[data[1]] = bytes(data)

        self._exp_reply.discard(data[1])

        if not self._exp_reply:  # check if all expected replies are received
            self._msg_event.set()

    @staticmethod
    @lru_cache(maxsize=32)
    def _cmd(cmd: int) -> bytes:
        """Assemble a ABC BMS command."""
        assert 0 <= cmd <= 0xFF
        frame = bytes([BMS._HEAD_CMD, cmd, 0x00, 0x00, 0x00])
        return frame + crc8(frame).to_bytes(1)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        self._msg.clear()
        self._exp_reply.clear()
        for cmd in (0xC1, 0xC2, 0xC4):
            self._exp_reply.update(BMS._EXP_REPLY[cmd])
            with contextlib.suppress(TimeoutError):
                await self._await_msg(BMS._cmd(cmd))

        # check all responses are here, 0xF9 is not mandatory (not all BMS report it)
        if not BMS._RESPS.issubset(self._msg.keys() | {0xF9}):
            self._log.debug("incomplete data set %s", self._msg.keys())
            raise ValueError("BMS data incomplete.")

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg, byteorder="little")
        return result | {
            "cell_voltages": BMS._cell_voltages(  # every second value is the cell idx
                self._msg[0xF4],
                cells=(len(self._msg[0xF4]) - 4) // 2,
                start=3,
                byteorder="little",
                size=2,
            )[::2],
            "temp_values": BMS._temp_values(
                self._msg[0xF2],
                start=5,
                values=result.get("temp_sensors", 0),
                byteorder="little",
            ),
        }
