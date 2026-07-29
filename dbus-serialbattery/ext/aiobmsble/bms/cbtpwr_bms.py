"""Module to support CBT Power smart BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import lru_cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern, TempSensor
from aiobmsble.basebms import BaseBMS, crc_sum


class BMS(BaseBMS):
    """CBT Power smart BMS class implementation."""

    INFO: BMSInfo = {"default_manufacturer": "CBT Power", "default_model": "smart BMS"}
    _HEAD: Final[bytes] = b"\xaa\x55"
    _TAIL_RX: Final[bytes] = b"\x0d\x0a"
    _TAIL_TX: Final[bytes] = b"\x0a\x0d"
    _MIN_FRAME: Final[int] = len(_HEAD) + len(_TAIL_RX) + 3  # + CMD, LEN, CRC
    _CRC_POS: Final[int] = -len(_TAIL_RX) - 1
    _LEN_POS: Final[int] = 3
    _CMD_POS: Final[int] = 2
    _CELLV_CMDS: Final[tuple[int, ...]] = (0x5, 0x6, 0x7, 0x8)
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 4, 4, False, lambda x: x / 1000, 0x0B),
        BMSDp("current", 8, 4, True, lambda x: x / 1000, 0x0B),
        BMSDp("temp_values", 4, 2, True, lambda x: [TempSensor(x)], idx=0x09),
        BMSDp("battery_level", 4, 1, False, idx=0x0A),
        BMSDp("design_capacity", 4, 2, False, idx=0x15),
        BMSDp("cycles", 6, 2, False, idx=0x15),
        BMSDp("runtime", 14, 2, False, lambda x: x * BMS._HRS_TO_SECS // 100, 0x0C),
        BMSDp("problem_code", 4, 4, False, idx=0x21),
    )
    _CMDS: Final = frozenset(field.idx for field in _FIELDS)

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

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {"service_uuid": BMS.uuid_services()[0], "connectable": True},
            {  # Creabest
                "local_name": "???[CR]??????",
                "service_uuid": normalize_uuid_str("fff0"),
                "connectable": True,
            },
            {
                "service_uuid": normalize_uuid_str("03c1"),
                "manufacturer_id": 0x5352,
                "connectable": True,
            },
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("ffe5"), normalize_uuid_str("ffe0"))

    @staticmethod
    def uuid_rx() -> str:
        """Return characteristic that provides notification/read property."""
        return "ffe4"

    @staticmethod
    def uuid_tx() -> str:
        """Return characteristic that provides write property."""
        return "ffe9"

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Retrieve BMS data update."""
        self._log.debug("RX BLE data: %s", data)

        # verify that data is long enough
        if (
            len(data) < BMS._MIN_FRAME
            or len(data) != BMS._MIN_FRAME + data[BMS._LEN_POS]
        ):
            self._log.debug("incorrect frame length (%i): %s", len(data), data)
            return

        if not data.startswith(BMS._HEAD) or not data.endswith(BMS._TAIL_RX):
            self._log.debug("incorrect SOF/EOF: %s", data)
            return

        if not self._check_integrity(
            data,
            crc_sum,
            slice(len(BMS._HEAD), len(data) + BMS._CRC_POS),
            slice(BMS._CRC_POS, BMS._CRC_POS + 1),
        ):
            return

        self._msg[data[2]] = bytes(data)
        self._msg_event.set()

    @staticmethod
    @lru_cache(maxsize=32)
    def _cmd(cmd: bytes, value: list[int] | None = None) -> bytes:
        """Assemble a CBT Power BMS command."""
        value = [] if value is None else value
        assert len(value) <= 255
        frame = bytearray([*BMS._HEAD, cmd[0], len(value), *value])
        frame.append(crc_sum(frame[len(BMS._HEAD) :]))
        frame.extend(BMS._TAIL_TX)
        return bytes(frame)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        for cmd in BMS._CMDS:
            await self._await_msg(BMS._cmd(cmd.to_bytes(1)))
        if not BMS._CMDS.issubset(set(self._msg.keys())):
            self._log.debug("incomplete data set %s", self._msg.keys())
            raise ValueError("BMS data incomplete.")

        voltages: list[float] = []
        for cmd in BMS._CELLV_CMDS:
            await self._await_msg(BMS._cmd(cmd.to_bytes(1)))
            cells: list[float] = BMS._cell_voltages(
                self._msg[cmd], cells=5, start=4, byteorder="little"
            )
            voltages.extend(cells)
            if len(voltages) % 5 or len(cells) == 0:
                break

        data: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg, byteorder="little")

        # remove runtime if not discharging
        if data.get("current", 0) >= 0:
            data.pop("runtime", None)

        return data | {"cell_voltages": voltages}
