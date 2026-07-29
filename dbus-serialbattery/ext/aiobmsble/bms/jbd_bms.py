"""Module to support JBD smart BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import lru_cache
from typing import Final

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS, b2str, crc_sum, swap32


class BMS(BaseBMS):
    """JBD smart BMS class implementation."""

    INFO: BMSInfo = {"default_manufacturer": "Jiabaida", "default_model": "smart BMS"}
    _HEAD_INIT: Final[bytes] = b"\xff\xaa"  # header for initialization
    _HEAD_RSP: Final[bytes] = b"\xdd"  # header for responses
    _HEAD_CMD: Final[bytes] = b"\xdd\xa5"  # read header for commands
    _TAIL: Final[int] = 0x77  # tail for command
    _INIT_LEN: Final[int] = 5  # initialization frame size
    _INFO_LEN: Final[int] = 7  # minimum frame size
    _BASIC_INFO: Final[int] = 23  # basic info data length
    _FIELDS: Final[tuple[BMSDp, ...]] = (
        BMSDp("voltage", 4, 2, False, lambda x: x / 100),
        BMSDp("current", 6, 2, True, lambda x: x / 100),
        BMSDp("cycle_charge", 8, 2, False, lambda x: x / 100),
        BMSDp("design_capacity", 10, 2, False, lambda x: x // 100),
        BMSDp("cycles", 12, 2, False),
        BMSDp("balancer", 16, 4, False, swap32),
        BMSDp("problem_code", 20, 2, False),
        BMSDp("battery_level", 23, 1, False),
        BMSDp("chrg_mosfet", 24, 1, False, lambda x: bool(x & 0x1)),
        BMSDp("dischrg_mosfet", 24, 1, False, lambda x: bool(x & 0x2)),
        BMSDp("temp_sensors", 26, 1, False),  # count is not limited
    )  # general protocol v4

    accept_secret: bool = True

    def __init__(
        self,
        ble_device: BLEDevice,
        keep_alive: bool = True,
        secret: str = "",
        logger_name: str = "",
    ) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive, secret, logger_name)
        self._valid_reply: int = 0x00
        self._msg: bytes = b""

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            MatcherPattern(
                local_name=pattern,
                service_uuid=BMS.uuid_services()[0],
                connectable=True,
            )
            for pattern in (
                "DWF*",  # Daren BMS, Docan battery
                "JBD-*",
                "LSG-*",  # Lossigy battery
                "N-?????BL*",  # Nordström battery
                "SX1*",  # Supervolt v3
                "SX60*",  # Supervolt Ultra
                "SBL-*",  # SBL
                "OGR-*",  # OGRPHY
                "TZ-H*",  # CERRNSS battery
            )
        ] + [
            MatcherPattern(
                oui=oui, service_uuid=BMS.uuid_services()[0], connectable=True
            )
            for oui in (
                "10:A5:62",  # CHINS
                "A4:C1:37",
                "A4:C1:38",
                "A5:C2:37",
                "A5:C2:39",
                "A5:C2:3A",
                "AA:C2:37",
                "70:3E:97",
            )
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("ff00"),)

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "ff01"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "ff02"

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        await self._await_cmd_resp(0x05)
        length: Final[int] = self._msg[3]
        return {
            "hw_version": b2str(self._msg[4 : length + 4]),
        }

    def _notify_init_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new init data arrives)."""
        self._log.debug("RX BLE data: %s", data)

        if not data.startswith(BMS._HEAD_INIT):
            self._log.debug("incorrect SOF")
            return

        if len(data) < BMS._INIT_LEN or len(data) < BMS._INIT_LEN + data[3]:
            self._log.debug("incorrect frame length")
            return

        if not self._check_integrity(data, crc_sum, slice(2, -1), slice(-1, None)):
            return

        if data[2] != 0x15 or data[3] != 0x01:
            self._log.debug("unexpected response")
            return

        self._msg = bytes(data)
        self._msg_event.set()

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        if self._secret:
            await self._client.start_notify(BMS.uuid_rx(), self._notify_init_handler)
            data: Final[bytes] = self._secret.encode(encoding="ASCII")
            try:
                await self._await_msg(
                    BMS._HEAD_INIT
                    + b"\x15"
                    + len(self._secret).to_bytes(1)
                    + data
                    + ((0x15 + len(self._secret) + sum(data)) & 0xFF).to_bytes(1)
                )
            except TimeoutError:
                self._log.warning("Failed to initialize connection with secret")
                raise
            if self._msg[4] != 0x00:
                self._log.warning("incorrect secret")
                raise PermissionError("Incorrect secret.")

            await self._client.stop_notify(BMS.uuid_rx())

        await super()._init_connection(char_notify)

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        # check if answer is a heading of basic info (0x3) or cell block info (0x4)
        if (
            data.startswith(BMS._HEAD_RSP)
            and len(self._frame) > BMS._INFO_LEN
            and data[1] in (0x03, 0x04, 0x05)
            and data[2] == 0x00
            and len(self._frame) >= BMS._INFO_LEN + self._frame[3]
        ):
            self._frame.clear()

        self._frame.extend(data)
        self._log.debug(
            "RX BLE data (%s): %s", "start" if data == self._frame else "cnt.", data
        )

        # verify that data is long enough
        if (
            len(self._frame) < BMS._INFO_LEN
            or len(self._frame) < BMS._INFO_LEN + self._frame[3]
        ):
            return

        # check correct frame ending
        frame_end: Final[int] = BMS._INFO_LEN + self._frame[3] - 1
        if self._frame[frame_end] != BMS._TAIL:
            self._log.debug("incorrect frame end (length: %i).", len(self._frame))
            return

        if not self._check_integrity(
            self._frame,
            BMS._crc,
            slice(2, frame_end - 2),
            slice(frame_end - 2, frame_end),
        ):
            return

        if len(self._frame) != BMS._INFO_LEN + self._frame[3]:
            self._log.debug("wrong data length (%i): %s", len(self._frame), self._frame)

        if self._frame[1] != self._valid_reply:
            self._log.debug("unexpected response (type 0x%X)", self._frame[1])
            return

        self._msg = bytes(self._frame)
        self._msg_event.set()

    @staticmethod
    def _crc(frame: bytes | bytearray) -> int:
        """Calculate JBD frame CRC."""
        return 0x10000 - sum(frame)

    @staticmethod
    @lru_cache(maxsize=32)
    def _cmd(cmd: int, data: bytes = b"") -> bytes:
        """Assemble a JBD BMS command."""
        assert 0 <= cmd <= 0xFF
        assert len(data) <= 0xFF
        frame = bytes(BMS._HEAD_CMD + cmd.to_bytes(1) + len(data).to_bytes(1) + data)

        return frame + BMS._crc(frame[2:]).to_bytes(2, "big") + BMS._TAIL.to_bytes(1)

    async def _await_cmd_resp(self, cmd: int) -> None:
        msg: Final[bytes] = BMS._cmd(cmd)
        self._valid_reply = msg[2]
        await self._await_msg(msg)
        self._valid_reply = 0x00

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        data: BMSSample = {}
        await self._await_cmd_resp(0x03)
        data = BMS._decode_data(BMS._FIELDS, self._msg)
        data["temp_values"] = BMS._temp_values(
            self._msg,
            values=data.get("temp_sensors", 0),
            start=27,
            signed=False,
            offset=2731,
            divider=10,
        )

        await self._await_cmd_resp(0x04)
        data["cell_voltages"] = BMS._cell_voltages(
            self._msg, cells=self._msg[3] // 2, start=4, byteorder="big"
        )

        return data
