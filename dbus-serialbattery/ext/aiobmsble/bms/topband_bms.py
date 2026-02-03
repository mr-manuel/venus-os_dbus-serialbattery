"""Module to support Ective BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from string import hexdigits
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, crc_sum


class BMS(BaseBMS):
    """Ective BMS implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Topband", "default_model": "smart BMS"}
    _HEAD_RSP: Final[tuple[bytes, ...]] = (b"\x5e", b"\x83", b"\xb0")  # header for responses
    _MAX_CELLS: Final[int] = 16
    _INFO_LEN: Final[int] = 113
    _CRC_LEN: Final[int] = 4
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 0, 4, False, lambda x: x / 1000),
        BMSDp("current", 4, 4, True, lambda x: x / 1000),
        BMSDp("battery_level", 14, 2, False),
        BMSDp("cycle_charge", 8, 4, False, lambda x: x / 1000),
        BMSDp("cycles", 12, 2, False),
        BMSDp("temp_values", 16, 2, False, lambda x: [round(x / 10 - 273.15, 3)]),
        BMSDp("problem_code", 18, 1, False),
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
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
                "manufacturer_id": m_id,
            }
            for m_id in (0, 0xFFFF)
        ]

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return [normalize_uuid_str("ffe0")]

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "ffe4"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        raise NotImplementedError

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""

        if (
            start := next(
                (i for i, b in enumerate(data) if bytes([b]) in BMS._HEAD_RSP), -1
            )
        ) != -1:  # check for beginning of frame
            data = data[start:]
            self._frame.clear()

        self._frame += data
        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data
        )

        if len(self._frame) < BMS._INFO_LEN:
            return

        self._frame = self._frame[: BMS._INFO_LEN]  # cut off exceeding data

        if not (
            self._frame.startswith(BMS._HEAD_RSP)
            and set(self._frame.decode(errors="replace")[1:]).issubset(hexdigits)
        ):
            self._log.debug("incorrect frame coding: %s", self._frame)
            self._frame.clear()
            return

        _dec: Final[bytes] = bytes.fromhex(
            self._frame.strip(b"".join(BMS._HEAD_RSP)).decode()
        )

        if (crc := crc_sum(_dec[:-2], 2)) != int.from_bytes(_dec[-2:]):
            self._log.debug(
                "invalid checksum 0x%X != 0x%X", int.from_bytes(_dec[-2:]), crc
            )
            self._frame.clear()
            return

        self._msg = _dec
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)
        return self._decode_data(BMS._FIELDS, self._msg, byteorder="little") | {
            "cell_voltages": BMS._cell_voltages(
                self._msg, cells=BMS._MAX_CELLS, start=22, byteorder="little"
            )
        }
