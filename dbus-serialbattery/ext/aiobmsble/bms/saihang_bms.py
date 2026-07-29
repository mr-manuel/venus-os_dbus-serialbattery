"""Module to support Saihang BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern, TempSensor
from aiobmsble.basebms import BaseBMS, crc_modbus


class BMS(BaseBMS):
    """Saihang BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Saihang Technology",
        "default_model": "intelligent BMS",
    }
    _HEAD: Final[bytes] = b"\xa5\xa5"  # beginning of frame
    _MIN_FRAME_LEN: Final[int] = 7  # min frame length, including SOF and CRC
    _MAX_TEMP: Final[int] = 10
    _MAX_CELLS: Final[int] = 20
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("current", 5, 4, True, lambda x: x / 100),
        BMSDp("voltage", 9, 4, False, lambda x: x / 100),
        BMSDp("battery_level", 13, 2, False),
        BMSDp("battery_health", 15, 2, False),
        BMSDp("cycle_charge", 17, 4, False, lambda x: x / 100),
        BMSDp("design_capacity", 25, 4, False, lambda x: x // 100),
        BMSDp("cycles", 29, 2, False),
        BMSDp("problem_code", 31, 2, False, lambda x: ~x & 0xFFFF),
        BMSDp("chrg_mosfet", 37, 2, False, lambda x: bool(x & 0x0200)),
        BMSDp("dischrg_mosfet", 37, 2, False, lambda x: bool(x & 0x0400)),
        BMSDp("balancer", 41, 2, False),
        BMSDp("cell_count", 43, 2, False, lambda x: min(x, BMS._MAX_CELLS)),
        BMSDp("temp_sensors", 85, 2, False, lambda x: min(x, BMS._MAX_TEMP)),
    )

    def __init__(
        self,
        ble_device: BLEDevice,
        keep_alive: bool = True,
        secret: str = "",
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive, secret, logger_name)
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": "SH*",
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("fffa"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "fffc"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "fffb"

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(BMS._HEAD):
            self._log.debug("incorrect SOF")
            return

        if len(data) < BMS._MIN_FRAME_LEN or len(data) != BMS._MIN_FRAME_LEN + data[4]:
            self._log.debug("incorrect frame length %d", len(data))
            return

        if not self._check_integrity(
            data,
            crc_modbus,
            slice(2, -2),
            slice(-2, None),
            "little",
        ):
            return

        self._msg = bytes(data)
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        await self._await_msg(BMS._HEAD + BMS._cmd_modbus(count=0x48))

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg)
        result["cell_voltages"] = BMS._cell_voltages(
            self._msg, cells=result.get("cell_count", 0), start=45
        )
        result["temp_values"] = BMS._temp_values(
            self._msg,
            values=result.get("temp_sensors", 0),
            start=87,
            offset=2730,
            divider=10,
            types=(TempSensor.T.CELL,) * result.get("temp_sensors", 0),
        ) + BMS._temp_values(
            self._msg,
            values=2,
            start=107,
            offset=2730,
            divider=10,
            types=(TempSensor.T.MOSFET, TempSensor.T.AMBIENT),
        )
        result["temp_sensors"] = len(result["temp_values"])

        return result
