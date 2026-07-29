"""Module to support Lithionics BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSInfo, BMSSample, MatcherPattern, TempSensor
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Lithionics BMS implementation (ASCII stream protocol)."""

    INFO: BMSInfo = {
        "default_manufacturer": "Lithionics",
        "default_model": "NeverDie smart BMS",
    }
    _HEAD_STATUS: Final[str] = "&,"
    _MIN_FIELDS_PRIMARY: Final[int] = 10
    _MIN_FIELDS_STATUS: Final[int] = 3

    def __init__(
        self,
        ble_device: BLEDevice,
        keep_alive: bool = True,
        secret: str = "",
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive, secret, logger_name)
        self._stream_data: dict[str, list[str]] = {}

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            # Seen on Lithionics Li3 packs: "Li3-061322094"
            MatcherPattern(
                local_name="Li[0-9]-*",
                service_uuid=BMS.uuid_services()[0],
                manufacturer_id=19784,
                connectable=True,
            ),
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
        raise NotImplementedError

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        self._frame.extend(data)
        while (idx := self._frame.find(b"\r\n")) >= 0:
            line: str = self._frame[:idx].decode("ascii", errors="ignore").strip()
            del self._frame[: idx + 2]

            if not line:
                continue

            if line == "ERROR":
                self._log.debug("ignoring command response: %s", line)
                continue

            fields: list[str] = line.split(",")
            if (
                line.startswith(BMS._HEAD_STATUS)
                and len(fields) >= BMS._MIN_FIELDS_STATUS
            ):
                self._stream_data["status"] = fields
            elif line[0].isdigit() and len(fields) >= BMS._MIN_FIELDS_PRIMARY:
                self._stream_data["primary"] = fields

            if self._stream_data.keys() >= {"primary", "status"}:
                self._msg_event.set()

        if len(self._frame) > BMS.BLE_MAX_ATTR_SIZE:
            self._log.debug("invalid frame")
            self._frame.clear()

    @staticmethod
    def _parse_primary(fields: list[str]) -> BMSSample:
        # BMS reports temperatures in Fahrenheit.
        temp_values: Final[list[TempSensor]] = [
            TempSensor(round((int(fields[idx]) - 32) * 5 / 9, 3)) for idx in (5, 6)
        ]

        return {
            "voltage": int(fields[0]) / 100,
            "cell_voltages": [int(value) / 100 for value in fields[1:5]],
            "temp_values": temp_values,
            "temp_sensors": 2,
            "current": float(fields[7]),
            "battery_level": int(fields[8]),
            "problem_code": int(fields[9], 16),
        }

    @staticmethod
    def _parse_status(fields: list[str]) -> BMSSample:

        result: BMSSample = {"cycle_charge": float(fields[2])}
        if len(fields) > 3:
            result["total_charge"] = int(fields[3])

        return result

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        self._stream_data.clear()
        self._msg_event.clear()
        await asyncio.wait_for(self._wait_event(), timeout=BMS.TIMEOUT)

        result: BMSSample = BMS._parse_primary(
            self._stream_data["primary"]
        ) | BMS._parse_status(self._stream_data["status"])

        return result
