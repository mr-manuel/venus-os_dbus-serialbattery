"""Module to support Super-B BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from struct import unpack_from
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Super-B BMS implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Super-B", "default_model": "Epsilon"}
    _INFO_LEN: Final[int] = 20
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("battery_level", 2, 1, False),
        # BMSDp("health", 3, 1, False), // or SoH?
        BMSDp("runtime", 4, 4, False, float),
        BMSDp("problem_code", 1, 1, False, lambda x: (x & 0x1) ^ 0x1),
        BMSDp("balancer", 1, 1, False, lambda x: bool(x & 0x80)),
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [MatcherPattern(local_name="Epsilon-*", connectable=True)]

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return ["74b9c2d1-dc6d-42cf-a2e9-7398b8fc2e70"]

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "6edadbe4-4f53-4a5a-96ed-02f93db93790"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        raise NotImplementedError

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if len(data) != BMS._INFO_LEN:
            self._log.debug("incorrect frame length")
            return

        self._msg = bytes(data)
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""

        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)
        result: BMSSample = self._decode_data(BMS._FIELDS, self._msg)

        result["current"] = round(unpack_from(">f", self._msg, 8)[0], 3)
        result["voltage"] = round(unpack_from(">f", self._msg, 12)[0], 3)

        # remove runtime if not discharging
        if result.get("current", 0) >= 0:
            result.pop("runtime", None)

        return result
