"""Module to support Offgridtec Smart Pro BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from collections.abc import Callable
from string import digits, hexdigits
from typing import Any, Final, NamedTuple

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSInfo, BMSSample, BMSValue, MatcherPattern
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Offgridtec LiFePO4 Smart Pro type A and type B BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Offgridtec",
        "default_model": "LiFePo4 Smart Pro",
    }
    _IDX_NAME: Final = 0
    _IDX_LEN: Final = 1
    _IDX_FCT: Final = 2
    # magic crypt sequence of length 16
    _CRY_SEQ: Final[tuple[int, ...]] = (2, 5, 4, 3, 1, 4, 1, 6, 8, 3, 7, 2, 5, 8, 9, 3)

    class _Response(NamedTuple):
        valid: bool
        reg: int
        value: int

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive)
        self._type: str = (
            self.name[9]
            if len(self.name) >= 10 and set(self.name[10:]).issubset(digits)
            else "?"
        )
        self._key: int = (
            sum(BMS._CRY_SEQ[int(c, 16)] for c in (f"{int(self.name[10:]):0>4X}"))
            if self._type in "AB"
            else 0
        ) + (5 if (self._type == "A") else 8)
        self._log.info(
            "%s type: %c, ID: %s, key: 0x%X",
            self.bms_id(),
            self._type,
            self.name[10:],
            self._key,
        )
        self._exp_reply: int = 0x0
        self._response: BMS._Response = BMS._Response(False, 0, 0)
        self._REGISTERS: dict[int, tuple[BMSValue, int, Callable[[int], Any]]]
        if self._type == "A":
            self._REGISTERS = {
                # SOC (State of Charge)
                2: ("battery_level", 1, lambda x: x),
                4: ("cycle_charge", 3, lambda x: x / 1000),
                8: ("voltage", 2, lambda x: x / 1000),
                # MOS temperature
                12: ("temp_values", 2, lambda x: [round(x / 10 - 273.15, 3)]),
                # 3rd byte of current is 0 (should be 1 as for B version)
                16: ("current", 3, lambda x: x / 100),
                24: ("runtime", 2, lambda x: x * 60),
                44: ("cycles", 2, lambda x: x),
                # Type A batteries have no cell voltage registers
            }
            self._HEADER = "+RAA"
        elif self._type == "B":
            self._REGISTERS = {
                # MOS temperature
                8: ("temp_values", 2, lambda x: [round(x / 10 - 273.15, 3)]),
                9: ("voltage", 2, lambda x: x / 1000),
                10: ("current", 3, lambda x: x / 1000),
                # SOC (State of Charge)
                13: ("battery_level", 1, lambda x: x),
                15: ("cycle_charge", 3, lambda x: x / 1000),
                18: ("runtime", 2, lambda x: x * 60),
                23: ("cycles", 2, lambda x: x),
            }
            # add cell voltage registers, note: need to be last!
            self._HEADER = "+R16"
        else:
            self._REGISTERS = {}
            self._log.exception("unknown device type '%c'", self._type)

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Return a list of Bluetooth matchers."""
        return [
            {
                "local_name": "SmartBat-[AB]*",
                "service_uuid": BMS.uuid_services()[0],
                "connectable": True,
            }
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("fff0"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "fff4"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "fff6"

    async def _fetch_device_info(self) -> BMSInfo:  # char "180a" contains garbage
        """Fetch the device information via BLE."""
        return {"serial_number": self.name[10:]}

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        self._log.debug("RX BLE data: %s", data)

        self._response = self._ogt_response(data)

        # check that descrambled message is valid
        if not self._response.valid:
            self._log.debug("response data is invalid")
            return

        if self._response.reg not in (-1, self._exp_reply):
            self._log.debug("wrong register response")
            return

        self._exp_reply = -1
        self._msg_event.set()

    def _ogt_response(self, resp: bytearray) -> _Response:
        """Descramble a response from the BMS."""

        try:
            msg: Final[str] = bytes(
                (resp[x] ^ self._key) for x in range(len(resp))
            ).decode(encoding="ascii")
        except UnicodeDecodeError:
            return BMS._Response(False, -1, 0)

        self._log.debug("response: %s", msg.rstrip("\r\n"))
        # verify correct response
        if len(msg) < 8 or not msg.startswith("+RD,"):
            return BMS._Response(False, -1, 0)
        if msg[4:7] == "Err":
            return BMS._Response(True, -1, 0)
        if not msg.endswith("\r\n") or not all(c in hexdigits for c in msg[4:-2]):
            return BMS._Response(False, -1, 0)

        # 16-bit value in network order (plus optional multiplier for 24-bit values)
        # multiplier has 1 as minimum due to current value in A type battery
        signed: bool = len(msg) > 12
        value: int = int.from_bytes(
            bytes.fromhex(msg[6:10]), byteorder="little", signed=signed
        ) * (max(int(msg[10:12], 16), 1) if signed else 1)
        return BMS._Response(True, int(msg[4:6], 16), value)

    def _ogt_command(self, reg: int, length: int) -> bytes:
        """Put together an scambled query to the BMS."""

        cmd: Final[str] = f"{self._HEADER}{reg:0>2X}{length:0>2X}"
        self._log.debug("command: %s", cmd)

        return bytes(ord(cmd[i]) ^ self._key for i in range(len(cmd)))

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        result: BMSSample = {}

        for reg in list(self._REGISTERS):
            self._exp_reply = reg
            await self._await_msg(
                data=self._ogt_command(reg, self._REGISTERS[reg][BMS._IDX_LEN])
            )
            if self._response.reg < 0:
                raise TimeoutError

            name, _length, func = self._REGISTERS[self._response.reg]
            result[name] = func(self._response.value)
            self._log.debug(
                "decoded data: reg: %s (#%i), raw: %i, value: %s",
                name,
                reg,
                self._response.value,
                result.get(name),
            )

        # read cell voltages for type B battery
        if self._type == "B":
            for cell_reg in range(16):
                self._exp_reply = 63 - cell_reg
                await self._await_msg(data=self._ogt_command(63 - cell_reg, 2))
                if self._response.reg < 0:
                    self._log.debug("cell count: %i", cell_reg)
                    break
                result.setdefault("cell_voltages", []).append(
                    self._response.value / 1000
                )

        # remove remaining runtime if battery is charging
        if result.get("runtime") == 0xFFFF * 60:
            del result["runtime"]

        return result
