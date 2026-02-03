"""Module to support Seplos v2 BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, b2str, crc_xmodem


class BMS(BaseBMS):
    """Seplos v2 BMS implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Seplos", "default_model": "smart BMS V2"}
    _HEAD: Final[bytes] = b"\x7e"
    _TAIL: Final[bytes] = b"\x0d"
    _CMD_VER: Final[int] = 0x10  # TX protocol version
    _RSP_VER: Final[int] = 0x14  # RX protocol version
    _MIN_LEN: Final[int] = 10
    _MAX_SUBS: Final[int] = 0xF
    _CELL_POS: Final[int] = 9
    _PRB_MAX: Final[int] = 8  # max number of alarm event bytes
    _PRB_MASK: Final[int] = 0x7DFFFFFFFFFF  # ignore byte 7-8 + byte 6 (bit 7,2)
    _PFIELDS: Final[tuple[BMSDp, ...]] = (  # Seplos V2: single machine data
        BMSDp("voltage", 2, 2, False, lambda x: x / 100),
        BMSDp("current", 0, 2, True, lambda x: x / 100),  # /10 for 0x62
        BMSDp("cycle_charge", 4, 2, False, lambda x: x / 100),  # /10 for 0x62
        BMSDp("cycles", 13, 2, False),
        BMSDp("battery_level", 9, 2, False, lambda x: x / 10),
        BMSDp("battery_health", 15, 2, False, lambda x: x / 10),
    )
    _GSMD_LEN: Final[int] = _CELL_POS + max((dp.pos + dp.size) for dp in _PFIELDS) + 3
    _CMDS: Final[frozenset[tuple[int, bytes]]] = frozenset(
        {(0x51, b""), (0x61, b"\x00"), (0x62, b"")}
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._msg: dict[int, bytes] = {}
        self._exp_len: int = BMS._MIN_LEN
        self._exp_reply: set[int] = set()

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": pattern,
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
            for pattern in ("BP0?", "BP1?", "BP2?")
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("ff00"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "ff01"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "ff02"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        self._exp_reply = {0x51}
        await self._await_msg(BMS._cmd(0x51))
        _dat: Final[bytes] = self._msg[0x51]
        return {
            "model": b2str(_dat[26:36]),
            "sw_version": f"{int(_dat[37])}.{int(_dat[38])}",
        }

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        if (
            len(data) > BMS._MIN_LEN
            and data.startswith(BMS._HEAD)
            and len(self._frame) >= self._exp_len
        ):
            self._exp_len = BMS._MIN_LEN + int.from_bytes(data[5:7])
            self._frame = bytearray()

        self._frame += data
        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data
        )

        # verify that data is long enough
        if len(self._frame) < self._exp_len:
            return

        if not self._frame.endswith(BMS._TAIL):
            self._log.debug("incorrect frame end: %s", self._frame)
            return

        if self._frame[1] != BMS._RSP_VER:
            self._log.debug("unknown frame version: V%.1f", self._frame[1] / 10)
            return

        if self._frame[4]:
            self._log.debug("BMS reported error code: 0x%X", self._frame[4])
            return

        if (crc := crc_xmodem(self._frame[1:-3])) != int.from_bytes(self._frame[-3:-1]):
            self._log.debug(
                "invalid checksum 0x%X != 0x%X",
                crc,
                int.from_bytes(self._frame[-3:-1]),
            )
            return

        self._log.debug(
            "address: 0x%X, function: 0x%X, return: 0x%X",
            self._frame[2],
            self._frame[3],
            self._frame[4],
        )

        self._msg[self._frame[3]] = bytes(self._frame)
        try:
            self._exp_reply.remove(self._frame[3])
            self._msg_event.set()
        except KeyError:
            self._log.debug("unexpected reply: 0x%X", self._frame[3])

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Initialize protocol state."""
        await super()._init_connection()
        self._exp_len = BMS._MIN_LEN

    @staticmethod
    @cache
    def _cmd(cmd: int, address: int = 0, data: bytes = b"") -> bytes:
        """Assemble a Seplos V2 BMS command."""
        assert cmd in (0x47, 0x51, 0x61, 0x62, 0x04)  # allow only read commands
        frame = bytearray([*BMS._HEAD, BMS._CMD_VER, address, 0x46, cmd])
        frame += len(data).to_bytes(2, "big", signed=False) + data
        frame += int.to_bytes(crc_xmodem(frame[1:]), 2, byteorder="big") + BMS._TAIL
        return bytes(frame)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        for cmd, data in BMS._CMDS:
            self._exp_reply.add(cmd)
            await self._await_msg(BMS._cmd(cmd, data=data))

        result: BMSSample = {}
        result["cell_count"] = self._msg[0x61][BMS._CELL_POS]
        result["temp_sensors"] = self._msg[0x61][
            BMS._CELL_POS + result["cell_count"] * 2 + 1
        ]
        ct_blk_len: Final[int] = (result["cell_count"] + result["temp_sensors"]) * 2 + 2

        if (BMS._GSMD_LEN + ct_blk_len) > len(self._msg[0x61]):
            raise ValueError("message too short to decode data")

        result |= BMS._decode_data(
            BMS._PFIELDS, self._msg[0x61], start=BMS._CELL_POS + ct_blk_len
        )

        # get extension pack count from parallel data (main pack)
        result["pack_count"] = self._msg[0x51][42]

        # get switches from parallel data (main pack)
        states: Final[int] = self._msg[0x62][45]
        result |= {
            "dischrg_mosfet": bool(states & 0x1),
            "chrg_mosfet": bool(states & 0x2),
            "balancer": bool(states & 0x4),
            "heater": bool(states & 0x8),
        }

        # get alarms from parallel data (main pack)
        alarm_evt: Final[int] = min(self._msg[0x62][46], BMS._PRB_MAX)
        result["problem_code"] = (
            int.from_bytes(self._msg[0x62][47 : 47 + alarm_evt], byteorder="big")
            & BMS._PRB_MASK
        )

        result["cell_voltages"] = BMS._cell_voltages(
            self._msg[0x61],
            cells=self._msg[0x61][BMS._CELL_POS],
            start=10,
        )
        result["temp_values"] = BMS._temp_values(
            self._msg[0x61],
            values=result.get("temp_sensors", 0),
            start=BMS._CELL_POS + result.get("cell_count", 0) * 2 + 2,
            signed=False,
            offset=2731,
            divider=10,
        )

        self._msg.clear()

        return result
