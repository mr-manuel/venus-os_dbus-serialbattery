"""Module to support ANT BMS."""

import contextlib
from enum import IntEnum
from functools import cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, crc_sum


class BMS(BaseBMS):
    """ANT BMS (legacy) implementation."""

    class CMD(IntEnum):
        """Command codes for ANT BMS."""

        GET = 0xDB
        SET = 0xA5

    class ADR(IntEnum):
        """Address codes for ANT BMS."""

        STATUS = 0x00

    INFO: BMSInfo = {"default_manufacturer": "ANT", "default_model": "legacy smart BMS"}
    _RX_HEADER: Final[bytes] = b"\xaa\x55\xaa"
    _RX_HEADER_RSP_STAT: Final[bytes] = b"\xaa\x55\xaa\xff"

    _RSP_STAT: Final[int] = 0xFF
    _RSP_STAT_LEN: Final[int] = 140

    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 4, 2, False, lambda x: x / 10),
        BMSDp("current", 70, 4, True, lambda x: x / -10),
        BMSDp("battery_level", 74, 1, False),
        BMSDp("design_capacity", 75, 4, False, lambda x: x // 1e6),
        BMSDp("cycle_charge", 79, 4, False, lambda x: x / 1e6),
        BMSDp("total_charge", 83, 4, False, lambda x: x // 1000),
        BMSDp("runtime", 87, 4, False),
        BMSDp("cell_count", 123, 1, False),
        BMSDp(
            "problem_code",
            103,
            2,
            False,
            lambda x: ((x & 0xF00) if (x >> 8) not in (0x1, 0x4, 0xF) else 0)
            | ((x & 0xF) if (x & 0xF) not in (0x1, 0x4, 0xB, 0xF) else 0),
        ),
        BMSDp("chrg_mosfet", 103, 1, False, lambda x: x == 0x1),
        BMSDp("dischrg_mosfet", 104, 1, False, lambda x: x == 0x1),
        BMSDp("balancer", 105, 1, False, lambda x: bool(x & 0x4)),
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
                "local_name": "ANT-BLE*",
                "service_uuid": BMS.uuid_services()[0],
                "manufacturer_id": 1623,
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("ffe0"),)  # change service UUID here!

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

        self._log.debug("RX BLE data: %s", data)

        if data.startswith(BMS._RX_HEADER_RSP_STAT):
            self._frame = bytearray()
        elif not self._frame:
            self._log.debug("invalid start of frame")
            return

        self._frame += data

        _data_len: Final[int] = len(self._frame)
        if _data_len < BMS._RSP_STAT_LEN:
            return

        if _data_len > BMS._RSP_STAT_LEN:
            self._log.debug("invalid length %d > %d", _data_len, BMS._RSP_STAT_LEN)
            self._frame.clear()
            return

        if (local_crc := crc_sum(self._frame[4:-2], 2)) != (
            remote_crc := int.from_bytes(self._frame[-2:], byteorder="big", signed=False)
        ):
            self._log.debug("invalid checksum 0x%X != 0x%X", local_crc, remote_crc)
            self._frame.clear()
            return

        self._msg = bytes(self._frame)
        self._frame.clear()
        self._msg_event.set()

    @staticmethod
    @cache
    def _cmd(cmd: CMD, adr: ADR, value: int = 0x0000) -> bytes:
        """Assemble a ANT BMS command."""
        _frame = bytearray((cmd, cmd, adr))
        _frame += value.to_bytes(2, "big")
        _frame += crc_sum(_frame[2:], 1).to_bytes(1, "big")
        return bytes(_frame)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._await_msg(BMS._cmd(BMS.CMD.GET, BMS.ADR.STATUS))

        result: BMSSample = BMS._decode_data(
            BMS._FIELDS, self._msg, byteorder="big"
        )

        result["cell_voltages"] = BMS._cell_voltages(
            self._msg,
            cells=result.get("cell_count", 0),
            start=6,
            size=2,
            byteorder="big",
            divider=1000,
        )

        if not result.get("design_capacity", 1):
            # Workaround for some BMS always reporting 0 for design_capacity
            result.pop("design_capacity")
            with contextlib.suppress(ZeroDivisionError):
                result["design_capacity"] = int(
                    round(
                        result.get("cycle_charge", 0)
                        / result.get("battery_level", 0)
                        * 100,
                        -1,
                    )
                )  # leads to `cycles` not available when level == 0

        # ANT-BMS carries 6 slots for temp sensors but only 4 looks like being connected by default
        result["temp_values"] = BMS._temp_values(
            self._msg, values=4, start=91, size=2, byteorder="big", signed=True
        )

        return result
