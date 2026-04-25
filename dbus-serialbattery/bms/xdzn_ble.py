"""
XDZN / WattCycle BLE BMS driver for dbus-serialbattery.

Supports XDZN_001 and WT-prefixed devices (e.g. WattCycle 314Ah LiFePO4).
Protocol reverse-engineered by @qume (https://github.com/qume/wattcycle_ble).

BLE GATT:
  Service  0xFFF0
  Write    0xFFF2  (commands)
  Notify   0xFFF1  (responses)
  Auth     0xFFFA  (write "HiLink" to authenticate)

Tested hardware:
  - WattCycle Mini Smart BMS 314Ah LiFePO4 (4S)

battery_mode field in Warning Info (DP 141):
  0x00 = standby
  0x01 = charging   (charge FET on)
  0x02 = discharging (discharge FET on)
  0x03 = both FETs on

Author: generated for venus-os dbus-serialbattery integration
"""

from __future__ import annotations

import asyncio
import struct
from typing import Optional

from battery import Battery, Cell
from utils import logger

# ── BLE UUIDs ──────────────────────────────────────────────────────────────
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
AUTH_UUID = "0000fffa-0000-1000-8000-00805f9b34fb"

# ── Protocol constants ──────────────────────────────────────────────────────
FRAME_HEAD = 0x7E
FRAME_HEAD_ALT = 0x1E
FRAME_TAIL = 0x0D
FUNC_READ = 0x03
DEVICE_ADDR = 0x01
MIN_FRAME_SIZE = 11
AUTH_KEY = b"HiLink"

# Data-point addresses
DP_ANALOG = 140  # 0x8C  main battery data
DP_WARNING = 141  # 0x8D  protection / warning flags
DP_PRODUCT = 146  # 0x92  firmware / serial

# ── Modbus CRC16 lookup tables ──────────────────────────────────────────────
_CRC_HI = bytes(
    [
        0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
        0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
        0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
        0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
        0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
        0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
        0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
        0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
        0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
        0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
        0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
        0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
        0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
        0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
        0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
        0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
    ]
)
_CRC_LO = bytes(
    [
        0x00, 0xC0, 0xC1, 0x01, 0xC3, 0x03, 0x02, 0xC2, 0xC6, 0x06, 0x07, 0xC7, 0x05, 0xC5, 0xC4, 0x04,
        0xCC, 0x0C, 0x0D, 0xCD, 0x0F, 0xCF, 0xCE, 0x0E, 0x0A, 0xCA, 0xCB, 0x0B, 0xC9, 0x09, 0x08, 0xC8,
        0xD8, 0x18, 0x19, 0xD9, 0x1B, 0xDB, 0xDA, 0x1A, 0x1E, 0xDE, 0xDF, 0x1F, 0xDD, 0x1D, 0x1C, 0xDC,
        0x14, 0xD4, 0xD5, 0x15, 0xD7, 0x17, 0x16, 0xD6, 0xD2, 0x12, 0x13, 0xD3, 0x11, 0xD1, 0xD0, 0x10,
        0xF0, 0x30, 0x31, 0xF1, 0x33, 0xF3, 0xF2, 0x32, 0x36, 0xF6, 0xF7, 0x37, 0xF5, 0x35, 0x34, 0xF4,
        0x3C, 0xFC, 0xFD, 0x3D, 0xFF, 0x3F, 0x3E, 0xFE, 0xFA, 0x3A, 0x3B, 0xFB, 0x39, 0xF9, 0xF8, 0x38,
        0x28, 0xE8, 0xE9, 0x29, 0xEB, 0x2B, 0x2A, 0xEA, 0xEE, 0x2E, 0x2F, 0xEF, 0x2D, 0xED, 0xEC, 0x2C,
        0xE4, 0x24, 0x25, 0xE5, 0x27, 0xE7, 0xE6, 0x26, 0x22, 0xE2, 0xE3, 0x23, 0xE1, 0x21, 0x20, 0xE0,
        0xA0, 0x60, 0x61, 0xA1, 0x63, 0xA3, 0xA2, 0x62, 0x66, 0xA6, 0xA7, 0x67, 0xA5, 0x65, 0x64, 0xA4,
        0x6C, 0xAC, 0xAD, 0x6D, 0xAF, 0x6F, 0x6E, 0xAE, 0xAA, 0x6A, 0x6B, 0xAB, 0x69, 0xA9, 0xA8, 0x68,
        0x78, 0xB8, 0xB9, 0x79, 0xBB, 0x7B, 0x7A, 0xBA, 0xBE, 0x7E, 0x7F, 0xBF, 0x7D, 0xBD, 0xBC, 0x7C,
        0xB4, 0x74, 0x75, 0xB5, 0x77, 0xB7, 0xB6, 0x76, 0x72, 0xB2, 0xB3, 0x73, 0xB1, 0x71, 0x70, 0xB0,
        0x50, 0x90, 0x91, 0x51, 0x93, 0x53, 0x52, 0x92, 0x96, 0x56, 0x57, 0x97, 0x55, 0x95, 0x94, 0x54,
        0x9C, 0x5C, 0x5D, 0x9D, 0x5F, 0x9F, 0x9E, 0x5E, 0x5A, 0x9A, 0x9B, 0x5B, 0x99, 0x59, 0x58, 0x98,
        0x88, 0x48, 0x49, 0x89, 0x4B, 0x8B, 0x8A, 0x4A, 0x4E, 0x8E, 0x8F, 0x4F, 0x8D, 0x4D, 0x4C, 0x8C,
        0x44, 0x84, 0x85, 0x45, 0x87, 0x47, 0x46, 0x86, 0x82, 0x42, 0x43, 0x83, 0x41, 0x81, 0x80, 0x40,
    ]
)


def _crc16(data: bytes) -> int:
    hi, lo = 0xFF, 0xFF
    for b in data:
        idx = hi ^ b
        hi = lo ^ _CRC_HI[idx]
        lo = _CRC_LO[idx]
    return ((lo << 8) | hi) & 0xFFFF


def _build_frame(dp: int, head: int = FRAME_HEAD) -> bytes:
    buf = bytearray([head, 0x00, DEVICE_ADDR, FUNC_READ])
    buf += struct.pack(">H", dp)
    buf += struct.pack(">H", 0)
    crc = _crc16(bytes(buf))
    buf += struct.pack(">H", crc)
    buf.append(FRAME_TAIL)
    return bytes(buf)


def _expected_len(first_packet: bytes) -> Optional[int]:
    if len(first_packet) < 8:
        return None
    data_len = struct.unpack(">H", first_packet[6:8])[0]
    return data_len + 11


def _parse_current(data: bytes, off: int):
    """Parse 2-byte signed current with decimal flag. Returns (amps, new_offset)."""
    b0, b1 = data[off], data[off + 1]
    negative = bool(b0 & 0x80)
    has_decimal = bool(b0 & 0x40)
    raw = b1 | ((b0 & 0x3F) << 8)
    amps = (raw / 10.0) if has_decimal else float(raw)
    if negative:
        amps = -amps
    return amps, off + 2


# ── Main driver class ───────────────────────────────────────────────────────


class Xdzn_Ble(Battery):
    """
    dbus-serialbattery driver for XDZN / WattCycle BLE batteries.

    Configure in config.ini:
        BLUETOOTH_BMS = Xdzn_Ble AA:BB:CC:DD:EE:FF
    """

    poll_interval = 10000  # 10 s — BLE is slower than serial

    def __init__(self, port: str, baud: int, address: str = None):
        super().__init__(port, baud, address)
        self.type = "XDZN_BLE"
        self.address = address
        self.cell_count = 0
        self.capacity = 314.0
        self.max_battery_voltage = 0
        self.max_battery_charge_current = 150.0
        self.max_battery_discharge_current = 200.0
        self.charge_fet = True
        self.discharge_fet = True
        self.min_battery_voltage = 0
        self.cells = []
        self.temperature_mos = 0.0
        self.temperature_1 = 0.0
        self.temperature_2 = 0.0
        self.frame_head = FRAME_HEAD
        self._client = None
        self._buf = bytearray()
        self._event = asyncio.Event()
        self._expected = None
        self._loop = None
        self._unique_id = ""

    # ── dbus-serialbattery interface ────────────────────────────────────────

    def unique_identifier(self) -> str:
        return self._unique_id

    def connection_name(self) -> str:
        return "BLE " + (self.port if self.port else "")

    def test_connection(self) -> bool:
        """Try to connect and read product info. Returns True on success."""
        try:
            return self._run(self._async_test_connection())
        except Exception as e:
            logger.error("XDZN_BLE: test_connection failed: %s", e)
            return False

    def get_settings(self) -> bool:
        """Read static battery settings (capacity, cell count etc.)."""
        try:
            return self._run(self._async_get_settings())
        except Exception as e:
            logger.error("XDZN_BLE: get_settings failed: %s", e)
            return False

    def refresh_data(self) -> bool:
        """Read live battery data and populate Battery fields."""
        try:
            return self._run(self._async_refresh_data())
        except Exception as e:
            logger.error("XDZN_BLE: refresh_data failed: %s", e)
            return False

    # ── Async implementation ────────────────────────────────────────────────

    def _run(self, coro):
        """Run a coroutine synchronously using a dedicated event loop."""
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(coro)

    async def _connect(self) -> bool:
        """Establish BLE connection and authenticate."""
        from bleak import BleakClient

        try:
            if self._client and self._client.is_connected:
                return True

            self._client = BleakClient(self.address, timeout=15.0)
            await self._client.connect()

            self._buf.clear()
            self._event.clear()
            self._expected = None
            await self._client.start_notify(NOTIFY_UUID, self._on_notify)

            await self._client.write_gatt_char(AUTH_UUID, AUTH_KEY, response=False)
            await asyncio.sleep(0.5)

            return True

        except Exception as e:
            logger.error("XDZN_BLE: connect failed: %s", e)
            self._client = None
            return False

    async def _disconnect(self):
        if self._client:
            try:
                if self._client.is_connected:
                    await self._client.stop_notify(NOTIFY_UUID)
                    await self._client.disconnect()
            except Exception:
                pass
            self._client = None

    def _on_notify(self, _sender, data: bytearray):
        self._buf.extend(data)
        if self._expected is None and len(self._buf) >= 8:
            self._expected = _expected_len(bytes(self._buf))
        if self._expected and len(self._buf) >= self._expected:
            self._event.set()

    async def _send(self, dp: int, timeout: float = 6.0) -> Optional[bytes]:
        """Send a read command and return the complete response frame."""
        self._buf.clear()
        self._event.clear()
        self._expected = None

        cmd = _build_frame(dp, self.frame_head)
        await self._client.write_gatt_char(WRITE_UUID, cmd, response=False)

        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("XDZN_BLE: timeout reading DP %d", dp)
            return None

        return bytes(self._buf)

    async def _detect_frame_head(self) -> bool:
        """Try 0x7E then 0x1E to find the working frame header."""
        for head in [FRAME_HEAD, FRAME_HEAD_ALT]:
            self._buf.clear()
            self._event.clear()
            self._expected = None
            cmd = _build_frame(DP_PRODUCT, head)
            await self._client.write_gatt_char(WRITE_UUID, cmd, response=False)
            try:
                await asyncio.wait_for(self._event.wait(), timeout=3.0)
                resp = bytes(self._buf)
                if len(resp) >= MIN_FRAME_SIZE and resp[-1] == FRAME_TAIL:
                    self.frame_head = head
                    return True
            except asyncio.TimeoutError:
                pass
        logger.error("XDZN_BLE: could not detect frame head")
        return False

    def _parse_frame_data(self, raw: bytes) -> Optional[bytes]:
        """Validate and return the DATA portion of a response frame."""
        if not raw or len(raw) < MIN_FRAME_SIZE:
            return None
        if raw[0] not in (FRAME_HEAD, FRAME_HEAD_ALT):
            return None
        if raw[-1] != FRAME_TAIL:
            return None
        if raw[3] == 0x86:
            logger.warning("XDZN_BLE: device returned error code")
            return None
        data_len = struct.unpack(">H", raw[6:8])[0]
        return raw[8 : 8 + data_len]

    # ── Async connection test ───────────────────────────────────────────────

async def _async_test_connection(self) -> bool:
    if not await self._connect():
        return False
    try:
        if not await self._detect_frame_head():
            await self._disconnect()
            return False

        # Read product info (serial / firmware)
        raw = await self._send(DP_PRODUCT)
        data = self._parse_frame_data(raw)
        if data and len(data) == 60:
            fw = data[0:20].decode("ascii", errors="replace").rstrip("\x00").strip()
            sn = data[40:60].decode("ascii", errors="replace").rstrip("\x00").strip()
            self._unique_id = sn
            self.hardware_version = fw

        # Read analog data to get real cell count before setup_vedbus runs
        raw_a = await self._send(DP_ANALOG)
        analog = self._parse_analog(self._parse_frame_data(raw_a))
        if analog:
            self.cell_count = analog.get("cell_count", 4)
            self.max_battery_voltage = self.cell_count * 3.65
            self.min_battery_voltage = self.cell_count * 2.80
            self.cells = [Cell(False) for _ in range(self.cell_count)]
            logger.info(
                "XDZN_BLE: test_connection found %d cells, "
                "Vmax=%.2f Vmin=%.2f",
                self.cell_count,
                self.max_battery_voltage,
                self.min_battery_voltage,
            )
        else:
            logger.warning(
                "XDZN_BLE: could not read analog data in test_connection, "
                "using default %d cells",
                self.cell_count,
            )

        return True

    except Exception as e:
        logger.error("XDZN_BLE: _async_test_connection error: %s", e)
        await self._disconnect()
        return False

    # ── Async settings read ─────────────────────────────────────────────────

    async def _async_get_settings(self) -> bool:
        if not await self._connect():
            return False
        try:
            raw = await self._send(DP_ANALOG)
            data = self._parse_frame_data(raw)
            if not data:
                logger.error("XDZN_BLE: no data for DP_ANALOG in get_settings")
                return False

            result = self._parse_analog(data)
            if result:
                self.cell_count = result.get("cell_count", 8)
                self.capacity = result.get("design_capacity", 314.0)
                self.max_battery_voltage = self.cell_count * 3.65
                self.min_battery_voltage = self.cell_count * 2.80

            self.cells = [Cell(False) for _ in range(self.cell_count)]
            return True
        except Exception as e:
            logger.error("XDZN_BLE: get_settings error: %s", e)
            return False

    # ── Async data refresh ──────────────────────────────────────────────────

    async def _async_refresh_data(self) -> bool:
        if not await self._connect():
            return False
        try:
            raw_a = await self._send(DP_ANALOG)
            analog = self._parse_analog(self._parse_frame_data(raw_a))
            if not analog:
                logger.warning("XDZN_BLE: failed to parse analog data")
                return False

            self.voltage = analog["module_voltage"]
            self.current = analog["current"]
            self.soc = analog["soc"]
            self.capacity = analog["total_capacity"]
            self.remaining_capacity = analog["remaining_capacity"]

            for i, v in enumerate(analog["cell_voltages"]):
                if i < len(self.cells):
                    self.cells[i].voltage = v

            self.temperature_mos = analog["mos_temp"]
            self.temperature_1 = analog["mos_temp"]
            self.temperature_2 = analog["pcb_temp"]

            raw_w = await self._send(DP_WARNING)
            warning = self._parse_warning(self._parse_frame_data(raw_w))
            if warning:
                r1 = warning["status1"]
                r2 = warning["status2"]
                mode = warning["battery_mode"]

                self.protection.voltage_high = 2 if (r1 & 0x04) else 0
                self.protection.voltage_low = 2 if (r1 & 0x08) else 0
                self.protection.current_over = 2 if (r1 & 0x10) else 0
                self.protection.current_under = 2 if (r1 & 0x20) else 0
                self.protection.temp_high_charge = 2 if (r2 & 0x01) else 0
                self.protection.temp_high_discharge = 2 if (r2 & 0x02) else 0
                self.protection.temp_low_charge = 2 if (r2 & 0x04) else 0

                # battery_mode: 0x01=charging, 0x02=discharging, 0x03=both, 0x00=standby
                self.charge_fet = bool(mode & 0x01) or mode == 0x00
                self.discharge_fet = bool(mode & 0x02) or mode == 0x00

            return True

        except Exception as e:
            logger.error("XDZN_BLE: refresh_data error: %s", e)
            await self._disconnect()
            return False

    # ── Protocol parsers ────────────────────────────────────────────────────

    def _parse_analog(self, data: Optional[bytes]) -> Optional[dict]:
        """Parse Analog Quantity payload (DP 140)."""
        if not data:
            return None
        try:
            off = 0
            cell_count = data[off]
            off += 1
            cell_voltages = []
            for _ in range(cell_count):
                v = struct.unpack(">H", data[off : off + 2])[0]
                cell_voltages.append(v / 1000.0)
                off += 2

            temp_count = data[off]
            off += 1
            mos_temp = (struct.unpack(">H", data[off : off + 2])[0] - 2730) / 10.0
            off += 2
            pcb_temp = (struct.unpack(">H", data[off : off + 2])[0] - 2730) / 10.0
            off += 2
            for _ in range(temp_count - 2):
                off += 2

            current, off = _parse_current(data, off)

            module_voltage = struct.unpack(">H", data[off : off + 2])[0] / 100.0
            off += 2
            remaining_capacity = struct.unpack(">H", data[off : off + 2])[0] / 10.0
            off += 2
            total_capacity = struct.unpack(">H", data[off : off + 2])[0] / 10.0
            off += 2
            cycle_number = struct.unpack(">H", data[off : off + 2])[0]
            off += 2
            design_capacity = struct.unpack(">H", data[off : off + 2])[0] / 10.0
            off += 2
            soc = struct.unpack(">H", data[off : off + 2])[0]
            off += 2

            return {
                "cell_count": cell_count,
                "cell_voltages": cell_voltages,
                "mos_temp": mos_temp,
                "pcb_temp": pcb_temp,
                "current": current,
                "module_voltage": module_voltage,
                "remaining_capacity": remaining_capacity,
                "total_capacity": total_capacity,
                "cycle_number": cycle_number,
                "design_capacity": design_capacity,
                "soc": soc,
            }
        except Exception as e:
            logger.error("XDZN_BLE: _parse_analog error: %s", e)
            return None

    def _parse_warning(self, data: Optional[bytes]) -> Optional[dict]:
        """Parse Warning Info payload (DP 141)."""
        if not data:
            return None
        try:
            off = 0
            cell_count = data[off]
            off += 1
            off += cell_count

            temp_count = data[off]
            off += 1
            off += temp_count

            off += 3  # charge_current_state, voltage_state, discharge_current_state
            battery_mode = data[off]
            off += 1
            status1 = data[off]
            off += 1
            status2 = data[off]
            off += 1

            return {
                "battery_mode": battery_mode,
                "status1": status1,
                "status2": status2,
            }
        except Exception as e:
            logger.error("XDZN_BLE: _parse_warning error: %s", e)
            return None
