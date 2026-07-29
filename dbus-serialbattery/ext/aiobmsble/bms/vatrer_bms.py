"""Module to support Vatrer BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern, TempSensor
from aiobmsble.basebms import BaseBMS, crc_modbus


class BMS(BaseBMS):
    """Vatrer BMS implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Vatrer", "default_model": "smart BMS"}
    _HEAD: Final[bytes] = b"\x02\x03"  # beginning of frame
    _FRAME_LEN: Final[int] = 5  # head + len + CRC
    _MAX_CELLS: Final[int] = 0x1F
    _MAX_TEMP: Final[int] = 6
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 3, 2, False, lambda x: x / 100, 0x28),
        BMSDp("current", 5, 4, True, lambda x: x / 100, 0x28),
        BMSDp("battery_level", 9, 2, False, idx=0x28),
        BMSDp("battery_health", 17, 2, False, idx=0x28),
        BMSDp("cycle_charge", 11, 2, False, lambda x: x / 100, 0x28),
        BMSDp("cell_count", 3, 2, False, lambda x: min(x, BMS._MAX_CELLS), 0x3E),
        BMSDp("temp_sensors", 3, 2, False, lambda x: min(x, BMS._MAX_TEMP), 0x24),
        BMSDp("cycles", 15, 2, False, idx=0x28),
        BMSDp("delta_voltage", 29, 2, False, lambda x: x / 1000, 0x28),
        BMSDp("problem", 17, 15, False, lambda x: (x != 0), 0x24),
        BMSDp("chrg_mosfet", 32, 1, False, lambda x: bool(x & 0x10), 0x24),
        BMSDp("dischrg_mosfet", 32, 1, False, lambda x: bool(x & 0x20), 0x24),
        BMSDp("balancer", 35, 4, False, idx=0x24),
    )
    _RESPS: Final = frozenset(field.idx for field in _FIELDS)
    _CMDS: Final[frozenset[tuple[int, int]]] = frozenset(
        {(0x0, 0x14), (0x34, 0x12), (0x15, 0x1F)}
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
        self._msg: dict[int, bytes] = {}

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {  # name is likely YYMMDDVVVAAAAxx (date, V, Ah)
                "local_name": "[2-9]???[0-3]?512??00??",
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return ("6e400001-b5a3-f393-e0a9-e50e24dcca9e",)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(BMS._HEAD):
            self._log.debug("incorrect SOF")
            return

        if len(data) < BMS._FRAME_LEN or len(data) != data[2] + BMS._FRAME_LEN:
            self._log.debug("incorrect frame length")
            return

        if not self._check_integrity(
            data,
            crc_modbus,
            slice(None, -2),
            slice(-2, None),
            "little",
        ):
            return

        self._msg[data[2]] = bytes(data)
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        for addr, length in BMS._CMDS:
            await self._await_msg(BMS._cmd_modbus(dev_id=0x2, addr=addr, count=length))
        if not BMS._RESPS.issubset(set(self._msg.keys())):
            self._log.debug("incomplete data set %s", self._msg.keys())
            raise TimeoutError("BMS data incomplete.")

        result: BMSSample = BMS._decode_data(BMS._FIELDS, self._msg)
        result["cell_voltages"] = BMS._cell_voltages(
            self._msg[0x3E], cells=result.get("cell_count", 0), start=5
        )
        result["temp_values"] = BMS._temp_values(
            self._msg[0x24],
            values=result.get("temp_sensors", 0) + 2,
            start=5,
            types=(TempSensor.T.GENERIC,) * (result.get("temp_sensors", 0) + 1)
            + (TempSensor.T.MOSFET,),
        )

        return result
