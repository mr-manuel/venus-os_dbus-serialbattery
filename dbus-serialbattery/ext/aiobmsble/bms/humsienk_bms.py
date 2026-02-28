"""Module to support Humsienk BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, b2str, crc_sum


class BMS(BaseBMS):
    """Humsienk BMS implementation.

    Protocol verified against a live device. See docs/humsienk_bms.md for
    the full register map, frame format, and bit-level field definitions.
    """

    INFO: BMSInfo = {
        "default_manufacturer": "Humsienk",
        "default_model": "BMC",
    }
    _HEAD: Final[bytes] = b"\xaa"  # beginning of frame
    _MIN_LEN: Final[int] = 5  # minimal frame len
    _ALARM_MASK: Final[int] = 0xFF7F7F7F  # exclude MOSFET, balance status bits
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 3, 4, False, lambda x: x / 1000, 0x21),
        BMSDp("current", 7, 4, True, lambda x: x / 1000, 0x21),
        BMSDp("battery_level", 11, 1, False, idx=0x21),
        BMSDp("battery_health", 12, 1, False, idx=0x21),
        BMSDp("cycle_charge", 13, 4, False, lambda x: x / 1000, 0x21),
        BMSDp("design_capacity", 17, 4, False, lambda x: round(x / 1000), 0x21),
        BMSDp("cycles", 21, 2, False, idx=0x21),
        BMSDp("chrg_mosfet", 7, 1, False, lambda x: bool(x & 0x80), 0x20),
        BMSDp("dischrg_mosfet", 9, 1, False, lambda x: bool(x & 0x80), 0x20),
        BMSDp("balancer", 8, 1, False, lambda x: bool(x & 0x80), 0x20),
        BMSDp("problem_code", 7, 4, False, lambda x: x & BMS._ALARM_MASK, 0x20),
    )
    _CMDS: Final = frozenset({b"\x20", b"\x21", b"\x22"})

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._msg: dict[int, bytes] = {}
        self._valid_reply: int = 0x00

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": "HS*",
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("0001"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "0003"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "0002"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        for cmd in (b"\x11", b"\xf5"):
            await self._await_msg(BMS._cmd(cmd))
        return {
            "model": b2str(self._msg[0x11][3:-2]),
            "hw_version": b2str(self._msg[0xF5][3:-2]),
        }

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Initialize RX/TX characteristics and protocol state."""
        await super()._init_connection(char_notify)
        await self._await_msg(BMS._cmd(b"\x00"))  # init

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(BMS._HEAD) or ((length := len(data)) < BMS._MIN_LEN):
            self._log.debug("incorrect SOF")
            return

        if length != data[2] + BMS._MIN_LEN:
            self._log.debug("invalid frame length %d != %d", length, data[2])
            return

        if data[1] != self._valid_reply:
            self._log.debug("unexpected response (type 0x%X)", data[1])
            return

        if (crc := crc_sum(data[1:-2], 2)) != int.from_bytes(
            data[-2:], byteorder="little"
        ):
            self._log.debug(
                "invalid checksum 0x%X != 0x%X",
                int.from_bytes(data[-2:], byteorder="little"),
                crc,
            )
            return

        self._msg[data[1]] = bytes(data)
        self._msg_event.set()

    @staticmethod
    @cache
    def _cmd(cmd: bytes) -> bytes:
        """Assemble a Humsienk BMS command."""
        frame: Final[bytes] = cmd[:1] + b"\x00"
        return BMS._HEAD + frame + crc_sum(frame).to_bytes(2, byteorder="little")

    async def _await_msg(
        self,
        data: bytes,
        char: int | str | None = None,
        wait_for_notify: bool = True,
        max_size: int = 0,
    ) -> None:
        """Send data to the BMS and wait for valid reply notification."""

        self._valid_reply = data[1]  # expected reply type
        await super()._await_msg(data, char, wait_for_notify, max_size)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        for cmd in BMS._CMDS:
            await self._await_msg(BMS._cmd(cmd))

        result: BMSSample = BMS._decode_data(
            BMS._FIELDS, data=self._msg, byteorder="little"
        )
        result["cell_voltages"] = BMS._cell_voltages(
            self._msg[0x22], cells=24, start=3, byteorder="little"
        )
        result["temp_values"] = BMS._temp_values(
            self._msg[0x21], values=6, start=23, size=1, byteorder="little"
        )

        # Add problem for cell disconnect bitmap
        if any(self._msg[0x20][14:17]):
            result["problem"] = True

        return result
