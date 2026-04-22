# -*- coding: utf-8 -*-

# RoyPow BMS BLE driver for dbus-serialbattery
# Supports: Epoch, RoyPow, PowerUrus batteries (4S/8S/16S LiFePO4)
#
# Protocol (commands 0x02-0x04) reverse-engineered by @patman15:
#   https://github.com/patman15/aiobmsble
#   https://github.com/patman15/BMS_BLE-HA
#
# Additional commands (0x01 device info, 0x07 config/protection registers)
# discovered during this driver's development.
#
# Driver by @CyB0rgg — https://kiroshi.group
#
# Architecture: BLE polling runs in a dedicated background thread with its own
# asyncio event loop. Parsed data is cached in a thread-safe dict. The main
# dbus thread reads from the cache in refresh_data() — never blocks on BLE.

import asyncio
import atexit
import os
import sys
import re
import threading
from time import sleep, time
from typing import Optional
from utils import logger, BLUETOOTH_FORCE_RESET_BLE_STACK
from utils_ble import restart_ble_hardware_and_bluez_driver
from bleak import BleakClient, BleakScanner
from battery import Battery, Cell, Protection

BLE_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
BLE_CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"

# RoyPow protocol
HEADER = bytes([0xEA, 0xD1, 0x01])
TAIL = 0xF5
CMD_DEVICE_INFO = 0x01
CMD_CELLS = 0x02
CMD_STATUS = 0x03
CMD_SOC = 0x04
CMD_CONFIG = 0x07  # Protection/config registers — structure not fully decoded

# BLE timing
BLE_POLL_INTERVAL = 10  # seconds between full poll cycles
BLE_CMD_TIMEOUT = 3  # seconds to wait for a single BLE response
BLE_CONNECT_TIMEOUT = 10

# Known models where actual capacity differs from the name encoding
# Format: model_prefix -> actual_capacity_ah
KNOWN_CAPACITY_OVERRIDES = {
    "B12100": 105,  # Epoch B12100A/B marketed as 100 but rated 105Ah
    "12105": 105,  # Epoch Essential 12105ES/12105A-H
}

# Voltage-to-cell-count mapping
VOLTAGE_TO_CELLS = {
    12: 4,
    24: 8,
    36: 12,
    48: 16,
    51: 16,  # RoyPow uses 51 for 48V/16S
    72: 24,
}


def _parse_device_name(name: str) -> dict:
    """Parse battery specs from BLE advertisement name.
    Examples: 'B12100B 220700577', 'S12200A', 'C24230A 123456789'
    Returns: {voltage, cell_count, capacity, variant, serial, model}
    """
    result = {"voltage": None, "cell_count": None, "capacity": None, "variant": "", "serial": "", "model": ""}
    if not name:
        return result

    parts = name.strip().split()
    model = parts[0]
    result["model"] = model
    result["serial"] = parts[1] if len(parts) > 1 else ""

    # Pattern: [B|C|S][voltage_digits][capacity_digits][optional_variant_letter]
    m = re.match(r"[BCS]?(\d{2})(\d+)([A-Z\-]*)", model)
    if not m:
        return result

    voltage_code = int(m.group(1))
    capacity_from_name = int(m.group(2))
    result["variant"] = m.group(3)
    result["voltage"] = voltage_code
    result["cell_count"] = VOLTAGE_TO_CELLS.get(voltage_code)

    # Check known capacity overrides (marketing name != actual capacity)
    model_prefix = re.match(r"([A-Z]?\d+)", model)
    if model_prefix:
        prefix = model_prefix.group(1)
        for known_prefix, actual_ah in KNOWN_CAPACITY_OVERRIDES.items():
            if prefix.startswith(known_prefix) or known_prefix in prefix:
                result["capacity"] = actual_ah
                break

    if result["capacity"] is None:
        result["capacity"] = capacity_from_name

    return result


def _build_command(cmd: int) -> bytes:
    """Build a RoyPow protocol command with XOR checksum."""
    data = bytes([0x04, 0xFF, cmd])
    crc = 0
    for b in data:
        crc ^= b
    return HEADER + data + bytes([crc, TAIL])


def _validate_response(data: bytearray) -> bool:
    """Validate RoyPow response framing."""
    if not data or len(data) < 8:
        return False
    if data[0] != 0xEA or data[1] != 0xD1 or data[2] != 0x01:
        return False
    if data[-1] != TAIL:
        return False
    return True


class RoyPow_Ble(Battery):
    BATTERYTYPE = "RoyPow BLE"

    def __init__(self, port: Optional[str], baud: Optional[int], address: str):
        super().__init__(port, -1, address)

        self.address = address
        self.protection = Protection()
        self.type = self.BATTERYTYPE
        self.poll_interval = 5000  # dbus poll interval (ms) — data comes from cache

        # BLE thread state
        self.main_thread = threading.current_thread()
        self.ble_thread: Optional[threading.Thread] = None
        self.ble_connected = threading.Event()
        self.ble_run = True
        self.device = None  # BLEDevice instance, set after scan

        # Thread-safe data cache — written by BLE thread, read by dbus thread
        self._cache_lock = threading.Lock()
        self._cache = {
            "voltage": None,
            "current": None,
            "soc": None,
            "cells": [],
            "temperatures": [],
            "charge_fet": None,
            "discharge_fet": None,
            "protection_code": 0,
            "cycles": None,
            "device_info": None,
            "last_update": 0,
        }
        self._device_info_fetched = False
        self._poll_count = 0
        self._last_config_hex = None
        self._ambient_temp_service = None  # Separate dbus service for ambient temp

        # HCI UART recovery
        self._init_hci_uart_state()

        logger.info("Init of RoyPow_Ble at " + address)

    def _init_hci_uart_state(self):
        """Save HCI UART attach command for recovery."""
        try:
            if not os.path.isfile("/tmp/dbus-blebattery-hciattach"):
                execpath = os.popen("ps -ww | grep hciattach | grep -v grep").read()
                match = re.search(r"/usr/bin/hciattach.+", execpath)
                if match:
                    with open("/tmp/dbus-blebattery-hciattach", "w") as f:
                        f.write(match.group())
            else:
                execpath = os.popen("ps -ww | grep hciattach | grep -v grep").read()
                if not execpath:
                    with open("/tmp/dbus-blebattery-hciattach", "r") as f:
                        os.system(f.readline())
        except Exception:
            pass

    # ── BLE Background Thread ──────────────────────────────────────

    def _ble_thread_main(self):
        """Background thread: runs its own asyncio loop for BLE communication."""
        while self.ble_run and self.main_thread.is_alive():
            try:
                asyncio.run(self._ble_session())
            except Exception:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                logger.error(f"BLE session error: {repr(exc_obj)} " f"in {exc_tb.tb_frame.f_code.co_filename} line #{exc_tb.tb_lineno}")
            if self.ble_run:
                sleep(5)  # wait before reconnecting

    async def _ble_session(self):
        """Single BLE connection session: connect, poll in loop, handle disconnect."""
        logger.info(f"|- Scanning for RoyPow BMS at {self.address}")
        try:
            self.device = await BleakScanner.find_device_by_address(self.address, cb=dict(use_bdaddr=True), timeout=BLE_CONNECT_TIMEOUT)
        except Exception as e:
            if "Bluetooth adapters" in repr(e):
                self._reset_hci_uart()
                return
            logger.error(f"BLE scan error: {repr(e)}")
            self.device = None
            return

        if not self.device:
            logger.error(f"BMS not found at {self.address}")
            return

        try:
            async with BleakClient(self.device) as client:
                logger.info(f"|- Connected to {self.device.name}")
                self.ble_connected.set()

                while self.ble_run and client.is_connected and self.main_thread.is_alive():
                    await self._poll_cycle(client)
                    await asyncio.sleep(BLE_POLL_INTERVAL)

        except Exception:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            logger.error(f"BLE connection error: {repr(exc_obj)} " f"in {exc_tb.tb_frame.f_code.co_filename} line #{exc_tb.tb_lineno}")
        finally:
            self.ble_connected.clear()
            logger.info("BLE client disconnected")

    async def _send_ble_command(self, client: BleakClient, cmd: int) -> bytearray:
        """Send a single RoyPow command and collect the response."""
        command = _build_command(cmd)
        response = bytearray()
        event = asyncio.Event()

        def on_notify(sender, data):
            # Filter out AT+STAT responses from BLE module
            if data.startswith(b"AT+"):
                return
            response.extend(data)
            # Check for complete frame
            if len(response) >= 4:
                expected_len = response[3] + 5
                if len(response) >= expected_len:
                    event.set()

        await client.start_notify(BLE_CHAR_UUID, on_notify)
        await client.write_gatt_char(BLE_CHAR_UUID, command, response=False)

        try:
            await asyncio.wait_for(event.wait(), timeout=BLE_CMD_TIMEOUT)
        except asyncio.TimeoutError:
            pass
        finally:
            try:
                await client.stop_notify(BLE_CHAR_UUID)
            except Exception:
                pass

        return response

    async def _poll_cycle(self, client: BleakClient):
        """Execute one full poll cycle: read all 3 commands and update cache."""
        # Fetch device info once on first successful poll
        if not self._device_info_fetched:
            info_data = await self._send_ble_command(client, CMD_DEVICE_INFO)
            if _validate_response(info_data):
                try:
                    device_info = info_data[7:-2].decode("ascii", errors="replace")
                    with self._cache_lock:
                        self._cache["device_info"] = device_info.strip()
                    self._device_info_fetched = True
                    logger.info(f"RoyPow HW: {device_info.strip()}")
                except Exception:
                    pass

        cells_data = await self._send_ble_command(client, CMD_CELLS)
        status_data = await self._send_ble_command(client, CMD_STATUS)
        soc_data = await self._send_ble_command(client, CMD_SOC)

        # Periodically read CMD 0x07 (config/protection registers) and log
        # changes. Structure not fully decoded — logging raw hex for future
        # analysis (e.g. heater activation in cold weather, protection events).
        self._poll_count += 1
        if self._poll_count % 10 == 0:
            config_data = await self._send_ble_command(client, CMD_CONFIG)
            if config_data:
                # Filter out AT+STAT prefix if present
                hex_str = config_data.hex()
                if "ead101" in hex_str:
                    hex_str = hex_str[hex_str.index("ead101") :]
                if hex_str != self._last_config_hex:
                    logger.info(f"CMD 0x07 config registers: {hex_str}")
                    self._last_config_hex = hex_str

        # Parse and update cache atomically
        with self._cache_lock:
            # Cells
            if _validate_response(cells_data):
                n_cells = cells_data[6]
                cell_voltages = []
                for i in range(n_cells):
                    v = int.from_bytes(cells_data[9 + i * 2 : 9 + i * 2 + 2], "big")
                    cell_voltages.append(v / 1000.0)
                self._cache["cells"] = cell_voltages

            # Status: current, temps, MOSFETs, protection
            if _validate_response(status_data):
                curr_raw = int.from_bytes(status_data[6:9], "big")
                sign = -1 if (curr_raw & 0x010000) else 1
                magnitude = curr_raw & 0xFFFF
                self._cache["current"] = sign * magnitude / 100.0

                n_temps = status_data[13] if len(status_data) > 13 else 0
                temps = []
                for i in range(min(n_temps, 4)):
                    if len(status_data) > 14 + i:
                        temps.append(status_data[14 + i] - 40)
                self._cache["temperatures"] = temps

                if len(status_data) > 24:
                    mosfet = status_data[24]
                    self._cache["charge_fet"] = bool(mosfet & 0x04)
                    self._cache["discharge_fet"] = bool(mosfet & 0x02)

                if len(status_data) > 12:
                    self._cache["protection_code"] = int.from_bytes(status_data[9:12], "big")

            # SOC, voltage, cycles
            if _validate_response(soc_data):
                self._cache["soc"] = soc_data[7]

                if len(soc_data) > 48:
                    self._cache["voltage"] = int.from_bytes(soc_data[47:49], "big") / 100.0

                if len(soc_data) > 10:
                    cycles = int.from_bytes(soc_data[9:11], "big")
                    if cycles < 65535:
                        self._cache["cycles"] = cycles

            self._cache["last_update"] = time()

    # ── Battery Interface (called from main dbus thread) ───────────

    def connection_name(self) -> str:
        return "BLE " + self.address

    def custom_name(self) -> str:
        if self.device and self.device.name:
            return self.device.name
        return "RoyPow BLE"

    def product_name(self) -> str:
        return "SerialBattery(" + self.type + ")"

    def unique_identifier(self) -> str:
        return self.address.replace(":", "").lower()

    def test_connection(self) -> bool:
        """Start BLE thread and wait for first connection."""
        try:
            if not self.address:
                return False

            # Start BLE background thread
            self.ble_thread = threading.Thread(
                name="RoyPow_BLE_" + self.address[-5:],
                target=self._ble_thread_main,
                daemon=True,
            )
            self.ble_thread.start()

            def shutdown_ble_atexit():
                self.ble_run = False
                if self.ble_thread.is_alive():
                    self.ble_thread.join(timeout=5)

            atexit.register(shutdown_ble_atexit)

            # Wait for first BLE connection
            if not self.ble_connected.wait(timeout=BLE_CONNECT_TIMEOUT + 5):
                logger.error(">>> Unable to connect to RoyPow BMS")
                return False

            # Wait for first data to arrive in cache
            for _ in range(30):
                with self._cache_lock:
                    if self._cache["last_update"] > 0:
                        break
                sleep(0.5)
            else:
                logger.error(">>> Connected but no data received")
                return False

            # Set up battery identity from device name and cached data
            dev_name = self.device.name if self.device else ""
            parsed = _parse_device_name(dev_name)

            # Cell count: prefer actual BLE data, fall back to name parsing
            with self._cache_lock:
                cells_from_data = len(self._cache["cells"])
            if cells_from_data > 0:
                self.cell_count = cells_from_data
            elif parsed["cell_count"]:
                self.cell_count = parsed["cell_count"]
            else:
                self.cell_count = 4  # safe default for 12V

            self.cells = [Cell(True) for _ in range(self.cell_count)]

            # Capacity: from name parsing (with known overrides), user can
            # override via BATTERY_CAPACITY in config.ini
            self.capacity = parsed["capacity"] if parsed["capacity"] else 100

            # Hardware version: will be updated from CMD 0x01 in get_settings
            self.hardware_version = dev_name.strip() if dev_name else "RoyPow BMS"

            logger.info(
                f"RoyPow BMS found! {self.hardware_version}, "
                f"{self.cell_count}S {self.capacity}Ah, "
                f"serial: {parsed['serial']}, "
                f"BLE polling every {BLE_POLL_INTERVAL}s"
            )
            return True

        except Exception:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            logger.error(f"test_connection error: {repr(exc_obj)} " f"in {exc_tb.tb_frame.f_code.co_filename} line #{exc_tb.tb_lineno}")
            return False

    def get_settings(self) -> bool:
        """Read battery settings from cache (called once after connection)."""
        with self._cache_lock:
            if self._cache["cycles"] is not None:
                self.history.charge_cycles = self._cache["cycles"]
            # Update hardware version from CMD 0x01 if available
            if self._cache["device_info"]:
                self.hardware_version = self.hardware_version + " (" + self._cache["device_info"] + ")"

        self.has_settings = True
        logger.info(f"RoyPow settings: {self.cell_count}S, " f"{self.capacity}Ah, HW: {self.hardware_version}")
        return True

    def _setup_ambient_temp_service(self):
        """Create a separate com.victronenergy.temperature service for ambient temp.
        This shows as an independent sensor in Venus GUI, not mixed with cell temps.
        """
        try:
            import dbus
            from vedbus import VeDbusService

            svc_name = "com.victronenergy.temperature.roypow_ambient"
            self._ambient_temp_service = VeDbusService(svc_name, dbus.SystemBus())
            self._ambient_temp_service.add_path("/Mgmt/ProcessName", __file__)
            self._ambient_temp_service.add_path("/Mgmt/ProcessVersion", "1.0")
            self._ambient_temp_service.add_path("/Mgmt/Connection", "BLE " + self.address)
            self._ambient_temp_service.add_path("/DeviceInstance", 200)
            self._ambient_temp_service.add_path("/ProductId", 0)
            self._ambient_temp_service.add_path("/ProductName", "RoyPow Ambient")
            self._ambient_temp_service.add_path("/FirmwareVersion", "1.0")
            self._ambient_temp_service.add_path("/HardwareVersion", "")
            self._ambient_temp_service.add_path("/Connected", 1)
            self._ambient_temp_service.add_path("/Temperature", None)
            self._ambient_temp_service.add_path("/TemperatureType", 2)  # 2 = Generic
            parsed = _parse_device_name(self.device.name if self.device else "")
            serial_suffix = parsed["serial"][-3:] if parsed["serial"] else "BMS"
            self._ambient_temp_service.add_path("/CustomName", f"Epoch {serial_suffix} Ambient")
            self._ambient_temp_service.add_path("/Status", 0)
            logger.info("Ambient temperature service created: " + svc_name)
        except Exception as e:
            import traceback

            traceback.print_exc()
            logger.error(f"Failed to create ambient temp service: {e}")

    def refresh_data(self) -> bool:
        """Copy latest data from BLE cache to battery properties.
        This is called from the main dbus thread every poll_interval.
        It NEVER blocks on BLE — just reads the cache.
        """
        with self._cache_lock:
            # Check data freshness — if BLE hasn't updated in 60s, report offline
            age = time() - self._cache["last_update"]
            if age > 60:
                logger.warning(f"BLE data is {age:.0f}s stale")
                return False

            # Voltage and current
            if self._cache["voltage"] is not None:
                self.voltage = self._cache["voltage"]
            if self._cache["current"] is not None:
                self.current = self._cache["current"]

            # SOC
            if self._cache["soc"] is not None:
                self.soc = self._cache["soc"]

            # Cell voltages
            for i, v in enumerate(self._cache["cells"]):
                if i < len(self.cells):
                    self.cells[i].voltage = v

            # Temperatures — mapping confirmed from Epoch app:
            # [0] = Cell T1, [1] = Cell T2, [2] = MOSFET, [3] = Ambient
            # Ambient is published to a separate dbus temperature service
            # to avoid contaminating cell temperature calculations
            temps = self._cache["temperatures"]
            if len(temps) >= 1:
                self.temperature_1 = temps[0]
            if len(temps) >= 2:
                self.temperature_2 = temps[1]
            if len(temps) >= 3:
                self.temperature_mos = temps[2]
            if len(temps) >= 4:
                if self._ambient_temp_service is None:
                    self._setup_ambient_temp_service()
                if self._ambient_temp_service:
                    self._ambient_temp_service["/Temperature"] = temps[3]

            # FETs
            self.charge_fet = self._cache["charge_fet"]
            self.discharge_fet = self._cache["discharge_fet"]

            # Protection
            self._parse_protection(self._cache["protection_code"])

            # Cycles and SoH
            if self._cache["cycles"] is not None:
                self.history.charge_cycles = self._cache["cycles"]
                # Epoch spec: >3500 cycles to 70% EOL (30% degradation over 3500 cycles)
                self.soh = max(0, min(100, 100 - (self._cache["cycles"] * 30 / 3500)))

            # Remaining capacity
            if self.soc is not None and self.capacity is not None:
                self.capacity_remain = self.capacity * self.soc / 100.0

        return True

    def _parse_protection(self, code: int):
        """Parse RoyPow protection status bits."""
        self.protection.high_voltage = 2 if (code & 0x01) else 0
        self.protection.low_voltage = 2 if (code & 0x02) else 0
        self.protection.high_charge_current = 2 if (code & 0x04) else 0
        self.protection.high_discharge_current = 2 if (code & 0x08) else 0
        self.protection.high_charge_temp = 2 if (code & 0x10) else 0
        self.protection.low_charge_temp = 2 if (code & 0x20) else 0
        self.protection.high_temperature = 2 if (code & 0x40) else 0
        self.protection.low_temperature = 2 if (code & 0x80) else 0

    def _reset_hci_uart(self):
        """Reset HCI UART stack on critical Bluetooth failure."""
        logger.error("Reset of hci_uart stack... Reconnecting to: " + self.address)
        self.ble_run = False
        os.system("pkill -f 'hciattach'")
        sleep(0.5)
        os.system("rmmod hci_uart")
        os.system("rmmod btbcm")
        os.system("modprobe hci_uart")
        os.system("modprobe btbcm")
        sys.exit(1)

    def reset_bluetooth(self):
        """Reset BLE stack if configured."""
        if BLUETOOTH_FORCE_RESET_BLE_STACK:
            restart_ble_hardware_and_bluez_driver()


if __name__ == "__main__":
    bat = RoyPow_Ble("Foo", -1, sys.argv[1])
    if not bat.test_connection():
        logger.error(">>> ERROR: Unable to connect")
    else:
        bat.get_settings()
        bat.refresh_data()
        logger.info(f"SOC: {bat.soc}%, V: {bat.voltage}V, I: {bat.current}A")
        for i, c in enumerate(bat.cells):
            logger.info(f"  Cell {i+1}: {c.voltage}V")
