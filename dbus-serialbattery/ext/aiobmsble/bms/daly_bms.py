"""Module to support Daly smart BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern, TempSensor
from aiobmsble.basebms import BaseBMS, b2str, crc_modbus


class BMS(BaseBMS):
    """Daly smart BMS class implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Daly", "default_model": "smart BMS"}
    _HEAD_READ: Final[bytes] = b"\xd2\x03"
    _HEAD_LEN: Final[int] = 3
    _CRC_LEN: Final[int] = 2
    _MAX_CELLS: Final[int] = 32
    _MAX_TEMP: Final[int] = 8
    _INFO_LEN: Final[int] = 84 + _HEAD_LEN + _CRC_LEN + _MAX_CELLS + _MAX_TEMP
    _MOSTEMP_POS: Final[int] = _HEAD_LEN + 8
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
        self._mos_avail: bool | None = None

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
        await self._await_msg(BMS._cmd_modbus(dev_id=0xD2, addr=0xA9, count=32))
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

        if not self._check_integrity(
            data,
            crc_modbus,
            slice(None, -2),
            slice(-2, None),
            "little",
        ):
            return

        self._msg = bytes(data)
        self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        result: BMSSample = {}
        if self._mos_avail in (True, None):
            try:
                # request MOS temperature (possible: response, stuck response, no response)
                await self._await_msg(BMS._cmd_modbus(dev_id=0xD2, addr=0x3E, count=9))

                if self._mos_avail is None and self._msg[
                    BMS._MOSTEMP_POS : BMS._MOSTEMP_POS + 2
                ] in (b"\x00\x00", b"\xff\xff"):
                    self._log.debug("MOS temperature invalid, deactivating")
                    self._mos_avail = False
                else:
                    result["temp_values"] = [
                        TempSensor(
                            int.from_bytes(
                                self._msg[BMS._MOSTEMP_POS : BMS._MOSTEMP_POS + 2],
                                byteorder="big",
                            )
                            - 40,
                            TempSensor.T.MOSFET,
                        )
                    ]
                    self._mos_avail = True
            except TimeoutError:
                self._log.debug("MOS temperature read failed, deactivating")
                self._mos_avail = False

        await self._await_msg(BMS._cmd_modbus(dev_id=0xD2, addr=0x0, count=62))

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
