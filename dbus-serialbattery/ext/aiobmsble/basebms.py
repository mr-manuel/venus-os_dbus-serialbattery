"""Base class definition for battery management systems (BMS).

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from abc import ABC, abstractmethod
import asyncio
from collections.abc import Callable, MutableMapping
from itertools import takewhile
import logging
from statistics import fmean
from types import TracebackType
from typing import Any, Final, Literal, Self, final

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import (
    BleakCharacteristicNotFoundError,
    BleakDeviceNotFoundError,
    BleakError,
)
from bleak_retry_connector import BLEAK_TIMEOUT, establish_connection

from aiobmsble import BMSDp, BMSInfo, BMSSample, BMSValue, MatcherPattern


class BaseBMS(ABC):
    """Abstract base class for battery management system."""

    INFO: BMSInfo  # static BMS info, set "default_" keys in subclass
    MAX_RETRY: Final[int] = 3  # max number of retries for data requests
    TIMEOUT: Final[float] = BLEAK_TIMEOUT / 4  # default timeout for BMS operations
    # calculate time between retries to complete all retries (2 modes) in TIMEOUT seconds
    _RETRY_TIMEOUT: Final[float] = TIMEOUT / (2**MAX_RETRY - 1)
    _MAX_TIMEOUT_FACTOR: Final[int] = 8  # limit timeout increase to 8x
    _MAX_CELL_VOLT: Final[float] = 5.906  # max cell potential
    _HRS_TO_SECS: Final[int] = 60 * 60  # seconds in an hour

    type InfoCharType = Literal[
        "model",
        "serial_number",
        "fw_version",
        "sw_version",
        "hw_version",
        "manufacturer",
    ]

    class PrefixAdapter(logging.LoggerAdapter[logging.Logger]):
        """Logging adapter to add instance ID to each log message."""

        def process(
            self, msg: str, kwargs: MutableMapping[str, Any]
        ) -> tuple[str, MutableMapping[str, Any]]:
            """Process the logging message."""
            prefix: str = str(self.extra.get("prefix") if self.extra else "")
            return (f"{prefix} {msg}", kwargs)

    def __init__(
        self,
        ble_device: BLEDevice,
        keep_alive: bool = True,
        logger_name: str = "",
    ) -> None:
        """Initialize the BMS.

        `_notification_handler`: the callback function used for notifications from `uuid_rx()`
            characteristic. Not defined as abstract in this base class, as it can be both,
            a normal or async function

        Args:
            ble_device (BLEDevice): the Bleak device to connect to
            bms_info (dict[Literal["manufacturer", "model"], str]): default BMS identification
            keep_alive (bool): if true, the connection will be kept active after each update.
                Make sure to call `disconnect()` when done using the BMS class or better use
                `async with` context manager (requires `keep_alive=True`).
            logger_name (str): name of the logger for the BMS instance, default: module name

        """
        assert getattr(self, "_notification_handler", None) is not None, (
            "BMS class must define `_notification_handler` method"
        )
        assert {"default_manufacturer", "default_model"}.issubset(self.INFO), (
            "BMS class must define `INFO`"
        )
        self._ble_device: Final[BLEDevice] = ble_device
        self._keep_alive: Final[bool] = keep_alive
        self.name: Final[str] = self._ble_device.name or "undefined"
        self._inv_wr_mode: bool | None = None  # invert write mode (WNR <-> W)
        logger_name = logger_name or self.__class__.__module__
        self._log: Final[BaseBMS.PrefixAdapter] = BaseBMS.PrefixAdapter(
            logging.getLogger(f"{logger_name}"),
            {
                "prefix": f"{self.name}|{self._ble_device.address[-5:].replace(':', '')}:"
            },
        )

        self._log.debug(
            "initializing %s, BT address: %s", self.bms_id(), ble_device.address
        )
        self._client: BleakClient = BleakClient(
            self._ble_device,
            disconnected_callback=self._on_disconnect,
            services=[*self.uuid_services(), "180a"],
        )
        self._frame: bytearray = bytearray()
        self._msg_event: Final[asyncio.Event] = asyncio.Event()
        self._connect_lock: Final[asyncio.Lock] = asyncio.Lock()

    @final
    async def __aenter__(self) -> Self:
        """Asynchronous context manager to implement `async with` functionality."""
        if not self._keep_alive:
            raise ValueError("usage of context manager requires `keep_alive=True`.")
        await self._connect()
        return self

    @final
    async def __aexit__(
        self,
        typ: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Asynchronous context manager exit functionality."""
        await self.disconnect()

    @final
    @property
    def is_connected(self) -> bool:
        """Return True if BMS is connected."""
        return self._client.is_connected

    @final
    @classmethod
    def get_bms_module(cls) -> str:
        """Return BMS module name, e.g. aiobmsble.bms.dummy_bms."""
        return cls.__module__

    @staticmethod
    @abstractmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Return a list of Bluetooth advertisement matchers."""

    @final
    @classmethod
    def bms_id(cls) -> str:
        """Return static BMS information as string."""
        return f"{cls.INFO.get('default_manufacturer', "unknown")} {cls.INFO.get('default_model', "unknown")}"

    @staticmethod
    @abstractmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""

    @staticmethod
    @abstractmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""

    @staticmethod
    @abstractmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""

    @final
    async def device_info(self) -> BMSInfo:
        """Return a dictionary of device information.

        keys: manufacturer, model, model_id, name, serial_number, sw_version, hw_version
        """

        disconnect: Final[bool] = not self._client.is_connected
        await self._connect()
        dev_info: Final[BMSInfo] = await self._fetch_device_info()
        if disconnect:
            await self.disconnect()

        self._log.debug("BMS info %s", dev_info)
        return dev_info

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        info: BMSInfo = BMSInfo()

        if not self._client.services.get_service("180a"):
            self._log.debug("No BT device information available.")
            return info

        characteristics: Final[tuple[tuple[str, BaseBMS.InfoCharType], ...]] = (
            ("2a24", "model"),
            ("2a25", "serial_number"),
            ("2a26", "fw_version"),
            ("2a27", "hw_version"),
            ("2a28", "sw_version"),
            ("2a29", "manufacturer"),
        )

        for char, key in characteristics:
            try:
                if value := bytes(await self._client.read_gatt_char(char)):
                    info[key] = b2str(value)
                    self._log.debug("BT device %s: '%s'", key, info.get(key))
            except BleakCharacteristicNotFoundError:
                pass

        return info

    @staticmethod
    def _raw_values() -> frozenset[BMSValue]:
        """Return values that shall not be calculated even if the BMS cannot provide them.

        Default is `None`, i.e. calculate all possible missing values.
        See _add_missing_values() function for the required input to actually do so.

        Returns:
            frozenset[BMSValue]: set of BMS values that shall not be calculated

        """
        return frozenset()

    @final
    @staticmethod
    def _add_missing_values(
        data: BMSSample, raw_values: frozenset[BMSValue] = frozenset()
    ) -> None:
        """Calculate missing BMS values from existing ones.

        Args:
            data: data dictionary with values received from BMS
            raw_values: list of values that shall not be added to the dictionary

        Returns:
            None

        """
        if not data:
            return

        def can_calc(value: BMSValue, using: frozenset[BMSValue]) -> bool:
            """Check value to add is not excluded, does not exist, and needed data is available."""
            return (
                (value not in raw_values)
                and (value not in data)
                and using.issubset(data)
            )

        cell_voltages: Final[list[float]] = data.get("cell_voltages", [])
        battery_level: Final[int | float] = data.get("battery_level", 0)
        current: Final[float] = data.get("current", 0)

        calculations: dict[BMSValue, tuple[set[BMSValue], Callable[[], Any]]] = {
            "voltage": ({"cell_voltages"}, lambda: round(sum(cell_voltages), 3)),
            "delta_voltage": (
                {"cell_voltages"},
                lambda: (
                    round(max(cell_voltages) - min(cell_voltages), 3)
                    if len(cell_voltages)
                    else None
                ),
            ),
            "cycle_charge": (
                {"design_capacity", "battery_level"},
                lambda: (data.get("design_capacity", 0) * battery_level) / 100,
            ),
            "battery_level": (
                {"design_capacity", "cycle_charge"},
                lambda: round(
                    data.get("cycle_charge", 0) / data.get("design_capacity", 0) * 100,
                    1,
                ),
            ),
            "cell_count": ({"cell_voltages"}, lambda: len(cell_voltages)),
            "cycle_capacity": (
                {"voltage", "cycle_charge"},
                lambda: round(data.get("voltage", 0) * data.get("cycle_charge", 0), 3),
            ),
            "cycles": (
                {"design_capacity", "total_charge"},
                lambda: data.get("total_charge", 0) // data.get("design_capacity", 0),
            ),
            "power": (
                {"voltage", "current"},
                lambda: round(data.get("voltage", 0) * current, 3),
            ),
            "battery_charging": ({"current"}, lambda: current > 0),
            "runtime": (
                {"current", "cycle_charge"},
                lambda: (
                    int(
                        data.get("cycle_charge", 0)
                        / abs(current)
                        * BaseBMS._HRS_TO_SECS
                    )
                    if current < 0
                    else None
                ),
            ),
            "temperature": (
                {"temp_values"},
                lambda: (
                    round(fmean(data.get("temp_values", [])), 3)
                    if data.get("temp_values")
                    else None
                ),
            ),
        }

        for attr, (required, calc_func) in calculations.items():
            if (
                can_calc(attr, frozenset(required))
                and (value := calc_func()) is not None
            ):
                data[attr] = value

        # do sanity check on values to set problem state
        data["problem"] = any(
            [
                data.get("problem", False),
                data.get("problem_code", False),
                data.get("voltage") is not None and data.get("voltage", 0) <= 0,
                any(v <= 0 or v > BaseBMS._MAX_CELL_VOLT for v in cell_voltages),
                data.get("delta_voltage", 0) > BaseBMS._MAX_CELL_VOLT,
                data.get("cycle_charge") is not None
                and data.get("cycle_charge", 0.0) <= 0.0,
                battery_level > 100,
            ]
        )

    @final
    def _on_disconnect(self, _client: BleakClient) -> None:
        """Disconnect callback function."""

        self._log.debug("disconnected from BMS")

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        # reset any stale data from BMS
        self._frame.clear()
        self._msg_event.clear()

        self._log.debug(
            "start notify on RX characteristic %s", str(char_notify or self.uuid_rx())
        )
        await self._client.start_notify(
            char_notify or self.uuid_rx(), getattr(self, "_notification_handler")
        )

    @final
    async def _connect(self) -> None:
        """Connect to the BMS and setup notification if not connected."""

        async with self._connect_lock:
            if self._client.is_connected:
                self._log.debug("BMS already connected")
                return

            try:
                await self._client.disconnect()  # ensure no stale connection exists
            except (BleakError, TimeoutError, EOFError) as exc:
                self._log.debug(
                    "failed to disconnect stale connection (%s)", type(exc).__name__
                )

            self._log.debug("connecting BMS")
            self._client = await establish_connection(
                client_class=BleakClient,
                device=self._ble_device,
                name=self._ble_device.address,
                disconnected_callback=self._on_disconnect,
                services=[*self.uuid_services(), "180a"],
            )

            try:
                await self._init_connection()
            except Exception as exc:
                self._log.info(
                    "failed to initialize BMS connection (%s)", type(exc).__name__
                )
                await self.disconnect()
                raise

    def _wr_response(self, char: int | str) -> bool:
        char_tx: Final[BleakGATTCharacteristic | None] = (
            self._client.services.get_characteristic(char)
        )
        return bool(char_tx and "write" in getattr(char_tx, "properties", []))

    @final
    async def _send_msg(
        self,
        data: bytes,
        max_size: int,
        char: int | str,
        attempt: int,
        inv_wr_mode: bool = False,
    ) -> None:
        """Send message to the bms in chunks if needed."""
        chunk_size: Final[int] = max_size or len(data)

        for i in range(0, len(data), chunk_size):
            chunk: bytes = data[i : i + chunk_size]
            self._log.debug(
                "TX BLE req #%i (%s%s%s): %s",
                attempt + 1,
                "!" if inv_wr_mode else "",
                "W" if self._wr_response(char) else "WNR",
                "." if self._inv_wr_mode is not None else "",
                chunk.hex(" "),
            )
            await self._client.write_gatt_char(
                char,
                chunk,
                response=(self._wr_response(char) != inv_wr_mode),
            )

    async def _await_msg(
        self,
        data: bytes,
        char: int | str | None = None,
        wait_for_notify: bool = True,
        max_size: int = 0,
    ) -> None:
        """Send data to the BMS and wait for valid reply notification."""

        for inv_wr_mode in (
            [False, True] if self._inv_wr_mode is None else [self._inv_wr_mode]
        ):
            try:
                self._msg_event.clear()  # clear event before requesting new data
                for attempt in range(BaseBMS.MAX_RETRY):
                    await self._send_msg(
                        data, max_size, char or self.uuid_tx(), attempt, inv_wr_mode
                    )
                    if not wait_for_notify:
                        return  # write without wait for response selected
                    try:
                        await asyncio.wait_for(
                            self._wait_event(),
                            BaseBMS._RETRY_TIMEOUT
                            * min(2**attempt, BaseBMS._MAX_TIMEOUT_FACTOR),
                        )
                    except TimeoutError:
                        self._log.debug("TX BLE request timed out.")
                        continue  # retry sending data

                    self._inv_wr_mode = inv_wr_mode
                    return  # leave loop if no exception
            except (BleakCharacteristicNotFoundError, BleakDeviceNotFoundError):
                raise  # do not retry on these exceptions
            except BleakError as exc:
                self._log.error("TX BLE request error (%s)", type(exc).__name__)
                # try next write mode, without reconnecting, as recursion might occur
        raise TimeoutError

    @final
    async def disconnect(self, reset: bool = False) -> None:
        """Disconnect the BMS, includes stopping notifications."""

        self._log.debug("disconnecting BMS (%s)", str(self._client.is_connected))
        try:
            self._msg_event.clear()
            if reset:
                self._inv_wr_mode = None  # reset write mode
            await self._client.disconnect()
        except (BleakError, TimeoutError, EOFError) as exc:
            self._log.warning("disconnect failed! (%s)", type(exc).__name__)

    @final
    async def _wait_event(self) -> None:
        """Wait for data event and clear it."""
        await self._msg_event.wait()
        self._msg_event.clear()

    @abstractmethod
    async def _async_update(self) -> BMSSample:
        """Return a dictionary of BMS values (keys need to come from the SENSOR_TYPES list)."""

    @final
    async def async_update(self, raw: bool = False) -> BMSSample:
        """Retrieve updated values from the BMS using method of the subclass.

        Args:
            raw (bool): if true, the raw data from the BMS is returned without
                any calculations or missing values added

        Returns:
            BMSSample: dictionary with BMS values

        """
        await self._connect()

        data: BMSSample = await self._async_update()
        if not raw:
            self._add_missing_values(data, self._raw_values())

        if not self._keep_alive:
            # disconnect after data update to force reconnect next time (slow!)
            await self.disconnect()

        return data

    @staticmethod
    def _decode_data(
        fields: tuple[BMSDp, ...],
        data: bytes | dict[int, bytes],
        *,
        byteorder: Literal["little", "big"] = "big",
        start: int = 0,
    ) -> BMSSample:
        result: BMSSample = {}
        for field in fields:
            if isinstance(data, dict) and field.idx not in data:
                continue
            msg: bytes = data[field.idx] if isinstance(data, dict) else data
            result[field.key] = field.fct(
                int.from_bytes(
                    msg[start + field.pos : start + field.pos + field.size],
                    byteorder=byteorder,
                    signed=field.signed,
                )
            )
        return result

    @staticmethod
    def _cell_voltages(
        data: bytes,
        *,
        cells: int,
        start: int,
        size: int = 2,
        gap: int = 0,
        byteorder: Literal["little", "big"] = "big",
        divider: int = 1000,
    ) -> list[float]:
        """Return cell voltages from BMS message.

        Args:
            data: Raw data from BMS
            cells: Number of cells to read
            start: Start position in data array
            size: Number of bytes per cell value (default: 2)
            gap: Number of bytes to skip after each cell value (default: 0)
            byteorder: Byte order ("big"/"little" endian)
            divider: Value to divide raw value by, defaults to 1000 (mv to V)

        Returns:
            list[float]: List of cell voltages in volts

        """
        return [
            value / divider
            for idx in range(cells)
            if (len(data) >= start + idx * (size + gap) + size)
            and (
                value := int.from_bytes(
                    data[
                        start + idx * (size + gap) : start + idx * (size + gap) + size
                    ],
                    byteorder=byteorder,
                    signed=False,
                )
            )
        ]

    @staticmethod
    def _temp_values(
        data: bytes,
        *,
        values: int,
        start: int,
        size: int = 2,
        gap: int = 0,
        byteorder: Literal["little", "big"] = "big",
        signed: bool = True,
        offset: float = 0,
        divider: int = 1,
    ) -> list[int | float]:
        """Return temperature values from BMS message.

        Args:
            data: Raw data from BMS
            values: Number of values to read
            start: Start position in data array
            size: Number of bytes per temperature value (defaults 2)
            gap: Number of bytes to skip after each temperature value (default: 2)
            byteorder: Byte order ("big"/"little" endian)
            signed: Indicates whether two's complement is used to represent the integer.
            offset: The offset read values are shifted by (for Kelvin use 273.15)
            divider: Value to divide raw value by, defaults to 1000 (mv to V)

        Returns:
            list[int | float]: List of temperature values

        """
        return [
            (value - offset) / divider
            for idx in range(values)
            if (len(data) >= start + idx * (size + gap) + size)
            and (
                (
                    value := int.from_bytes(
                        data[
                            start + idx * (size + gap) : start
                            + idx * (size + gap)
                            + size
                        ],
                        byteorder=byteorder,
                        signed=signed,
                    )
                )
                or (offset == 0)
            )
        ]


def b2str(b: bytes) -> str:
    """Decode a bytearray to string, stopping at the first non-printable character."""
    s: Final[str] = b.decode("utf-8", errors="ignore")
    for i, c in enumerate(s):
        if not c.isprintable():
            return s[:i].strip()
    return s.strip()


def lstr2int(string: str) -> int:
    """Convert the beginning of a string to an integer, till first non-digit is found."""
    return int("".join(takewhile(str.isdigit, string)))


def swap32(value: int, signed: bool = False) -> int:
    """Swap high and low 16bit in 32bit integer."""
    value = ((value >> 16) & 0xFFFF) | (value & 0xFFFF) << 16
    if signed and value & 0x80000000:
        value -= 0x100000000
    return value


def crc_modbus(data: bytes | bytearray) -> int:
    """Calculate CRC-16-CCITT MODBUS."""
    crc: int = 0xFFFF
    for i in data:
        crc ^= i & 0xFF
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc % 2 else (crc >> 1)
    return crc & 0xFFFF


def lrc_modbus(data: bytes | bytearray) -> int:
    """Calculate MODBUS LRC."""
    return ((sum(data) ^ 0xFFFF) + 1) & 0xFFFF


def crc_xmodem(data: bytes | bytearray) -> int:
    """Calculate CRC-16-CCITT XMODEM."""
    crc: int = 0x0000
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = (crc << 1) ^ 0x1021 if (crc & 0x8000) else (crc << 1)
    return crc & 0xFFFF


def crc8(data: bytes | bytearray) -> int:
    """Calculate CRC-8/MAXIM-DOW."""
    crc: int = 0x00  # Initialwert für CRC

    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8C if crc & 0x1 else crc >> 1

    return crc & 0xFF


def crc_sum(frame: bytes | bytearray, size: int = 1) -> int:
    """Calculate the checksum of a frame using a specified size.

    size : int, optional
        The size of the checksum in bytes (default is 1).
    """
    return sum(frame) & ((1 << (8 * size)) - 1)
