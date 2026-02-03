"""Module to support LiPower BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, crc_modbus


class BMS(BaseBMS):
    """LiPower BMS implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Ective", "default_model": "LiPower BMS"}
    _HEADS: Final[tuple[bytes, ...]] = (b"\x22\x03", b"\x0b\x03")  # alternative heads
    _MIN_LEN: Final[int] = 5  # minimal frame length, including SOF and checksum
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 15, 2, False, lambda x: x / 10),
        BMSDp(
            "current", 12, 3, False, lambda x: (x & 0xFFFF) * -(1 ** (x >> 16)) / 100
        ),
        BMSDp("battery_level", 5, 2, False),
        BMSDp(
            "runtime",
            7,
            4,
            False,
            lambda x: (x >> 16) * BMS._HRS_TO_SECS + (x & 0xFFFF) * 60,
        ),
        BMSDp("cycle_charge", 3, 2, False),
        # BMSDp("power", 17, 2, False),  # disabled, due to precision
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._heads: tuple[bytes, ...] = BMS._HEADS
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [{"service_uuid": normalize_uuid_str("af30"), "connectable": True}]

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

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(self._heads) or len(data) < BMS._MIN_LEN:
            self._log.debug("incorrect SOF")
            return

        if len(data) != data[2] + BMS._MIN_LEN:
            self._log.debug("incorrect frame length")
            return

        if (crc := crc_modbus(data[:-2])) != int.from_bytes(
            data[-2:], byteorder="little"
        ):
            self._log.debug(
                "invalid checksum 0x%X != 0x%X",
                int.from_bytes(data[-2:], byteorder="little"),
                crc,
            )
            return

        self._msg = bytes(data)
        self._msg_event.set()

    @staticmethod
    @cache
    def _cmd(cmd: int, addr: int, words: int, head: bytes) -> bytes:
        """Assemble a LiPower BMS command (MODBUS)."""
        frame: bytearray = (
            bytearray(head)
            + cmd.to_bytes(1, "big")
            + addr.to_bytes(2, "big")
            + words.to_bytes(1, "big")
        )
        frame.extend(int.to_bytes(crc_modbus(frame), 2, byteorder="little"))
        return bytes(frame)

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        for head in self._heads:
            try:
                await self._await_msg(
                    BMS._cmd(cmd=0x4, addr=0x0, words=0x8, head=head)
                )
                if len(self._heads) > 1:
                    self._log.debug("detected frame head: %s", head.hex(" "))
                    self._heads = (head,)  # set to single head for further commands
                break
            except TimeoutError:
                ...  # try next frame head
        else:
            raise TimeoutError

        return BMS._decode_data(BMS._FIELDS, self._msg)
