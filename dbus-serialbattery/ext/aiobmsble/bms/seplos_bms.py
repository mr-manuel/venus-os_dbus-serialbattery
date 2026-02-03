"""Module to support Seplos V3 smart BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from collections.abc import Callable
from functools import cache
from typing import Any, Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSpackvalue, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, crc_modbus, swap32


class BMS(BaseBMS):
    """Seplos V3 smart BMS class implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Seplos", "default_model": "smart BMS V3"}
    _CMD_READ: Final[list[int]] = [0x01, 0x04]
    _HEAD_LEN: Final[int] = 3
    _CRC_LEN: Final[int] = 2
    _PIA_LEN: Final[int] = 0x11
    _PIB_LEN: Final[int] = 0x1A
    _EIA_LEN: Final[int] = _PIB_LEN
    _EIB_LEN: Final[int] = 0x16
    _EIC_LEN: Final[int] = 0x5
    _TEMP_START: Final[int] = _HEAD_LEN + 32
    _QUERY: Final[dict[str, tuple[int, int, int]]] = {
        # name: cmd, reg start, length
        "EIA": (0x4, 0x2000, _EIA_LEN),
        "EIB": (0x4, 0x2100, _EIB_LEN),
        "EIC": (0x1, 0x2200, _EIC_LEN),
    }
    _PQUERY: Final[dict[str, tuple[int, int, int]]] = {
        "PIA": (0x4, 0x1000, _PIA_LEN),
        "PIB": (0x4, 0x1100, _PIB_LEN),
    }
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("temperature", 20, 2, True, lambda x: x / 10, _EIB_LEN),  # avg. ctemp
        BMSDp("voltage", 0, 4, False, lambda x: swap32(x) / 100, _EIA_LEN),
        BMSDp("current", 4, 4, True, lambda x: swap32(x, True) / 10, _EIA_LEN),
        BMSDp("cycle_charge", 8, 4, False, lambda x: swap32(x) / 100, _EIA_LEN),
        BMSDp("pack_count", 44, 2, False, idx=_EIA_LEN),
        BMSDp("cycles", 46, 2, False, idx=_EIA_LEN),
        BMSDp("battery_level", 48, 2, False, lambda x: x / 10, _EIA_LEN),
        BMSDp("battery_health", 50, 2, False, lambda x: x / 10, _EIA_LEN),
        BMSDp("problem_code", 1, 9, False, lambda x: x & 0xFFFF00FF00FF0000FF, _EIC_LEN),
        BMSDp("dischrg_mosfet", 7, 1, False, lambda x: bool(x & 1), _EIC_LEN),
        BMSDp("chrg_mosfet", 7, 1, False, lambda x: bool(x & 2), _EIC_LEN),
        BMSDp("heater", 7, 1, False, lambda x: bool(x & 8), _EIC_LEN),
        BMSDp("balancer", 7, 1, False, lambda x: bool(x & 4), _EIC_LEN),  # limit FET
    )  # Protocol Seplos V3
    _PFIELDS: Final[
        tuple[tuple[BMSpackvalue, int, bool, Callable[[int], Any]], ...]
    ] = (
        ("pack_voltages", 0, False, lambda x: x / 100),
        ("pack_currents", 2, True, lambda x: x / 100),
        ("pack_battery_levels", 10, False, lambda x: x / 10),
        ("pack_battery_health", 12, False, lambda x: x / 10),
        ("pack_cycles", 14, False, lambda x: x),
    )  # Protocol Seplos V3
    _CMDS: Final = frozenset(
        {field[2] for field in _QUERY.values()}
        | {field[2] for field in _PQUERY.values()}
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive)
        self._msg: dict[int, bytes] = {}
        self._pack_count: int = 0  # number of battery packs
        self._pkglen: int = 0  # expected packet length

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": pattern,
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
            for pattern in ("SP??B*", "XZHX*", "CSY*", "SP1??B*")
        ]

    # setup UUIDs
    #    serv 0000fff0-0000-1000-8000-00805f9b34fb
    # 	 char 0000fff1-0000-1000-8000-00805f9b34fb (#16): ['read', 'notify']
    # 	 char 0000fff2-0000-1000-8000-00805f9b34fb (#20): ['read', 'write-without-response', 'write']
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
        return "fff2"

    # async def _fetch_device_info(self) -> BMSInfo: use default, VIA msg useless

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Retrieve BMS data update."""

        if (
            len(data) > BMS._HEAD_LEN + BMS._CRC_LEN
            and data[0] <= self._pack_count
            and data[1] & 0x7F in BMS._CMD_READ  # include read errors
            and data[2] >= BMS._HEAD_LEN + BMS._CRC_LEN
        ):
            self._frame.clear()
            self._pkglen = data[2] + BMS._HEAD_LEN + BMS._CRC_LEN
        elif (  # error message
            len(data) == BMS._HEAD_LEN + BMS._CRC_LEN
            and data[0] <= self._pack_count
            and data[1] & 0x80
        ):
            self._log.debug("RX error: %X", data[2])
            self._frame.clear()
            self._pkglen = BMS._HEAD_LEN + BMS._CRC_LEN

        self._frame += data
        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data
        )

        # verify that data is long enough
        if len(self._frame) < self._pkglen:
            return

        if (crc := crc_modbus(self._frame[: self._pkglen - 2])) != int.from_bytes(
            self._frame[self._pkglen - 2 : self._pkglen], "little"
        ):
            self._log.debug(
                "invalid checksum 0x%X != 0x%X",
                int.from_bytes(self._frame[self._pkglen - 2 : self._pkglen], "little"),
                crc,
            )
            self._frame.clear()
            return

        if self._frame[2] >> 1 not in BMS._CMDS or self._frame[1] & 0x80:
            self._log.debug(
                "unknown message: %s, length: %s", self._frame[0:2], self._frame[2]
            )
            self._frame.clear()
            return

        if len(self._frame) != self._pkglen:
            self._log.debug(
                "wrong data length (%i!=%s): %s",
                len(self._frame),
                self._pkglen,
                self._frame,
            )

        self._msg[self._frame[0] << 8 | self._frame[2] >> 1] = bytes(self._frame)
        self._frame.clear()
        self._msg_event.set()

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Initialize RX/TX characteristics."""
        await super()._init_connection()
        self._pack_count = 0
        self._pkglen = 0

    @staticmethod
    @cache
    def _cmd(device: int, cmd: int, start: int, count: int) -> bytes:
        """Assemble a Seplos BMS command."""
        assert device >= 0x00 and (device <= 0x10 or device in (0xC0, 0xE0))
        assert cmd in (0x01, 0x04)  # allow only read commands
        assert start >= 0 and count > 0 and start + count <= 0xFFFF
        frame: bytearray = bytearray([device, cmd])
        frame += int.to_bytes(start, 2, byteorder="big")
        frame += int.to_bytes(count * (0x10 if cmd == 0x1 else 0x1), 2, byteorder="big")
        frame += int.to_bytes(crc_modbus(frame), 2, byteorder="little")
        return bytes(frame)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        for block in BMS._QUERY.values():
            await self._await_msg(BMS._cmd(0x0, *block))

        data: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg, start=BMS._HEAD_LEN)

        self._pack_count = min(data.get("pack_count", 0), 0x10)

        for pack in range(1, 1 + self._pack_count):
            for block in BMS._PQUERY.values():
                await self._await_msg(self._cmd(pack, *block))

            for key, idx, sign, func in BMS._PFIELDS:
                data.setdefault(key, []).append(
                    func(
                        int.from_bytes(
                            self._msg[pack << 8 | BMS._PIA_LEN][
                                BMS._HEAD_LEN + idx : BMS._HEAD_LEN + idx + 2
                            ],
                            byteorder="big",
                            signed=sign,
                        )
                    )
                )

            pack_cells: list[float] = BMS._cell_voltages(
                self._msg[pack << 8 | BMS._PIB_LEN], cells=16, start=BMS._HEAD_LEN
            )
            # update per pack delta voltage
            data["delta_voltage"] = max(
                data.get("delta_voltage", 0),
                round(max(pack_cells) - min(pack_cells), 3),
            )
            # add individual cell voltages
            data.setdefault("cell_voltages", []).extend(pack_cells)
            # add temperature sensors (4x cell temperature + 4 reserved)
            data.setdefault("temp_values", []).extend(
                BMS._temp_values(
                    self._msg[pack << 8 | BMS._PIB_LEN],
                    values=4,
                    start=BMS._TEMP_START,
                    signed=False,
                    offset=2731,
                    divider=10,
                )
            )
            # calculate cell_count instead of querying SPA
            data["cell_count"] = len(data.get("cell_voltages", [])) // self._pack_count

        self._msg.clear()

        return data
