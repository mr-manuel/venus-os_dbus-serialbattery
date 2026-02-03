"""Module to support Redodo BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import contextlib
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, crc_sum


class BMS(BaseBMS):
    """Redodo BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Redodo",
        "default_model": "Bluetooth battery",
    }
    _HEAD_LEN: Final[int] = 3
    _MAX_CELLS: Final[int] = 16
    _MAX_TEMP: Final[int] = 5
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 12, 2, False, lambda x: x / 1000),
        BMSDp("current", 48, 4, True, lambda x: x / 1000),
        BMSDp("battery_level", 90, 2, False),
        BMSDp("battery_health", 92, 4, False),
        BMSDp("cycle_charge", 62, 2, False, lambda x: x / 100),
        BMSDp("design_capacity", 64, 4, False, lambda x: x // 100),
        BMSDp("cycles", 96, 4, False),
        BMSDp("balancer", 84, 4, False, int),
        BMSDp("heater", 68, 4, False, bool),
        BMSDp("problem_code", 76, 4, False),
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._temp_sensors: int = 1  # default to 1 temp sensor
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {  # patterns required to exclude "BT-ROCC2440"
                "local_name": pattern,
                "service_uuid": BMS.uuid_services()[0],
                "manufacturer_id": 0x585A,
                "connectable": True,
            }
            for pattern in (
                "R-12*",
                "R-24*",
                "RO-12*",
                "RO-24*",
                "P-12*",
                "P-24*",
                "PQ-12*",
                "PQ-24*",
                "L-12*",  # vv *** LiTime *** vv
                "L-24*",
                "L-51*",
                "LT-12???BG-A0[7-9]*",  # LiTime based on serial #
                "LT-24???B-A00[3-9]*",
                "LT-24???B-A0[1-9]*",
                "LT-24???B-A[1-9]*",
                "LT-51*",
            )
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

    # async def _fetch_device_info(self) -> BMSInfo: use default

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if len(data) < 3 or not data.startswith(b"\x00\x00"):
            self._log.debug("incorrect SOF.")
            return

        if len(data) != data[2] + BMS._HEAD_LEN + 1:  # add header length and CRC
            self._log.debug("incorrect frame length (%i)", len(data))
            return

        if (crc := crc_sum(data[:-1])) != data[-1]:
            self._log.debug("invalid checksum 0x%X != 0x%X", data[len(data) - 1], crc)
            return

        self._msg = bytes(data)
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._await_msg(b"\x00\x00\x04\x01\x13\x55\xaa\x17")

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg, byteorder="little")
        result["cell_voltages"] = BMS._cell_voltages(
            self._msg, cells=BMS._MAX_CELLS, start=16, byteorder="little"
        )
        result["temp_values"] = BMS._temp_values(
            self._msg, values=BMS._MAX_TEMP, start=52, byteorder="little"
        )
        # Determine number of temp sensors by checking if value is persistently 0
        with contextlib.suppress(StopIteration):
            self._temp_sensors = max(
                self._temp_sensors,
                next(
                    i
                    for i in range(BMS._MAX_TEMP, 1, -1)
                    if result["temp_values"][i - 1] != 0
                ),
            )
        result["temp_values"] = result["temp_values"][: self._temp_sensors]
        result["temp_sensors"] = self._temp_sensors

        return result
