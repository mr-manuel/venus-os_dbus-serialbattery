"""Module to support Daly smart BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, b2str, crc_modbus


class BMS(BaseBMS):
    """Daly smart BMS class implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Daly", "default_model": "smart BMS"}
    _HEAD_READ: Final[bytes] = b"\xd2\x03"
    _CMD_INFO: Final[bytes] = b"\x00\x00\x00\x3e\xd7\xb9"
    _MOS_INFO: Final[bytes] = b"\x00\x3e\x00\x09\xf7\xa3"
    _VER_INFO: Final[bytes] = b"\x00\xa9\x00\x20\x87\x91"
    _HEAD_LEN: Final[int] = 3
    _CRC_LEN: Final[int] = 2
    _MAX_CELLS: Final[int] = 32
    _MAX_TEMP: Final[int] = 8
    _INFO_LEN: Final[int] = 84 + _HEAD_LEN + _CRC_LEN + _MAX_CELLS + _MAX_TEMP
    _MOS_TEMP_POS: Final[int] = _HEAD_LEN + 8
    MOS_NOT_AVAILABLE: Final[tuple[str]] = ("DL-FB4C2E0",)
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 80, 2, False, lambda x: x / 10),
        BMSDp("current", 82, 2, False, lambda x: (x - 30000) / 10),
        BMSDp("battery_level", 84, 2, False, lambda x: x / 10),
        BMSDp("cycle_charge", 96, 2, False, lambda x: x / 10),
        BMSDp("cell_count", 98, 2, False, lambda x: min(x, BMS._MAX_CELLS)),
        BMSDp("temp_sensors", 100, 2, False, lambda x: min(x, BMS._MAX_TEMP)),
        BMSDp("cycles", 102, 2, False),
        BMSDp("delta_voltage", 112, 2, False, lambda x: x / 1000),
        BMSDp("problem_code", 116, 8, False, lambda x: x % 2**64),
        BMSDp("balancer", 104, 2, False),
        BMSDp("chrg_mosfet", 106, 2, False, bool),
        BMSDp("dischrg_mosfet", 108, 2, False, bool),
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive)
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            MatcherPattern(
                local_name="DL-*",
                service_uuid=BMS.uuid_services()[0],
                connectable=True,
            )
        ] + [
            MatcherPattern(
                manufacturer_id=m_id,
                connectable=True,
            )
            for m_id in (0x102, 0x104, 0x0302, 0x0303, 0x0402)
        ]

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

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        await self._await_msg(BMS._HEAD_READ + BMS._VER_INFO)
        return {
            "sw_version": b2str(self._msg[3:19]),
            "hw_version": b2str(self._msg[19:35]),
            # "manuf.date": barr2str(self._msg[35:51]),
        }

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        self._log.debug("RX BLE data: %s", data)

        if (
            len(data) < BMS._HEAD_LEN
            or data[0:2] != BMS._HEAD_READ
            or data[2] + 1 != len(data) - len(BMS._HEAD_READ) - BMS._CRC_LEN
        ):
            self._log.debug("response data is invalid")
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

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        result: BMSSample = {}
        if (  # do not query devices that do not support MOS temperature, e.g. Bulltron
            not self.name.startswith(BMS.MOS_NOT_AVAILABLE)
        ):
            try:
                # request MOS temperature (possible outcome: response, empty response, no response)
                await self._await_msg(BMS._HEAD_READ + BMS._MOS_INFO)

                if sum(self._msg[BMS._MOS_TEMP_POS :][:2]):
                    self._log.debug("MOS info: %s", self._msg)
                    result["temp_values"] = [
                        int.from_bytes(
                            self._msg[BMS._MOS_TEMP_POS :][:2],
                            byteorder="big",
                            signed=True,
                        )
                        - 40
                    ]
            except TimeoutError:
                self._log.debug("no MOS temperature available.")

        await self._await_msg(BMS._HEAD_READ + BMS._CMD_INFO)

        if len(self._msg) != BMS._INFO_LEN:
            self._log.debug("incorrect frame length: %i", len(self._msg))
            return {}

        result |= BMS._decode_data(BMS._FIELDS, self._msg, start=BMS._HEAD_LEN)

        # add temperature sensors
        result.setdefault("temp_values", []).extend(
            BMS._temp_values(
                self._msg,
                values=result.get("temp_sensors", 0),
                start=64 + BMS._HEAD_LEN,
                offset=40,
            )
        )

        # get cell voltages
        result["cell_voltages"] = BMS._cell_voltages(
            self._msg, cells=result.get("cell_count", 0), start=BMS._HEAD_LEN
        )

        return result
