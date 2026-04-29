# -*- coding: utf-8 -*-

# Notes
# Updated by https://github.com/idstein

import asyncio
import atexit
import os
import threading
import sys
import re
from asyncio import CancelledError
from time import sleep
from typing import Union, Optional
from utils import get_connection_error_message, logger, BLUETOOTH_FORCE_RESET_BLE_STACK
from utils_ble import restart_ble_hardware_and_bluez_driver
from bleak import BleakClient, BleakScanner, BLEDevice
from bleak.exc import BleakDBusError
from bms.lltjbd import LltJbdProtection, LltJbd

BLE_SERVICE_UUID = "0000ff00-0000-1000-8000-00805f9b34fb"

# Default JBD BLE UUIDs (most common)
BLE_CHARACTERISTICS_TX_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"
BLE_CHARACTERISTICS_RX_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"

# Alternative UUIDs for DH04 and similar BMS variants
BLE_CHARACTERISTICS_TX_UUID_ALT = "0000fff2-0000-1000-8000-00805f9b34fb"
BLE_CHARACTERISTICS_RX_UUID_ALT = "0000fff1-0000-1000-8000-00805f9b34fb"

MIN_RESPONSE_SIZE = 6
MAX_RESPONSE_SIZE = 256


class LltJbd_Ble(LltJbd):
    BATTERYTYPE = "LLT/JBD BLE"

    def __init__(self, port: Optional[str], baud: Optional[int], address: str):
        super(LltJbd_Ble, self).__init__(port, -1, address)

        self.address = address
        self.protection = LltJbdProtection()
        self.type = self.BATTERYTYPE
        self.main_thread = threading.current_thread()
        self.data: bytearray = bytearray()
        self.run = True
        # Persistent BLE notification state
        self.notify_active = False
        self.response_buffer = bytearray()
        self.response_future = None
        # UUID auto-detection: None = not detected yet, True = use alt UUIDs, False = use default
        self._use_alt_uuids: Optional[bool] = None
        self.bt_thread = threading.Thread(name="LltJbd_Ble_Loop", target=self.background_loop, daemon=True)
        self.bt_loop: Optional[asyncio.AbstractEventLoop] = None
        self.bt_client: Optional[BleakClient] = None
        self.device: Optional[BLEDevice] = None
        self.response_queue: Optional[asyncio.Queue] = None
        self.ready_event: Optional[asyncio.Event] = None

        self.hci_uart_ok = True
        if not os.path.isfile("/tmp/dbus-blebattery-hciattach"):
            execfile = open("/tmp/dbus-blebattery-hciattach", "w")
            execpath = os.popen("ps -ww | grep hciattach | grep -v grep").read()
            execpath = re.search("/usr/bin/hciattach.+", execpath)
            execfile.write(execpath.group())
            execfile.close()
        else:
            execpath = os.popen("ps -ww | grep hciattach | grep -v grep").read()
            if not execpath:
                execfile = open("/tmp/dbus-blebattery-hciattach", "r")
                os.system(execfile.readline())
                execfile.close()

        logger.info("Init of LltJbd_Ble at " + address)

    def connection_name(self) -> str:
        return "BLE " + self.address

    def custom_name(self) -> str:
        return getattr(self.device, "name", "Unknown LLT/JBD BMS")

    def on_disconnect(self, client):
        logger.info("BLE client disconnected")

    async def bt_main_loop(self):
        logger.info("|- Try to connect to LltJbd_Ble at " + self.address)
        try:
            self.device = await BleakScanner.find_device_by_address(self.address, cb=dict(use_bdaddr=True))

        except Exception:
            exception_type, exception_object, exception_traceback = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            if "Bluetooth adapters" in repr(exception_object):
                self.reset_hci_uart()
            else:
                logger.error(f"BleakScanner(): Exception occurred: {repr(exception_object)} of type {exception_type} " f"in {file} line #{line}")

            self.device = None
            await asyncio.sleep(0.5)
            # allow the bluetooth connection to recover
            sleep(5)

        if not self.device:
            self.run = False
            return

        try:
            async with BleakClient(self.device, disconnected_callback=self.on_disconnect) as client:
                self.bt_client = client
                logger.info("|- Device connected, check if it's really a LLT/JBD BMS")
                self.bt_loop = asyncio.get_event_loop()
                self.response_queue = asyncio.Queue()
                self.notify_active = False
                self.response_buffer = bytearray()
                self.response_future = None
                self.ready_event.set()
                while self.run and client.is_connected and self.main_thread.is_alive():
                    await asyncio.sleep(0.1)
            self.bt_loop = None

        # Exception occurred: TimeoutError() of type <class 'asyncio.exceptions.TimeoutError'>
        except asyncio.exceptions.TimeoutError:
            exception_type, exception_object, exception_traceback = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error(f"BleakClient(): asyncio.exceptions.TimeoutError: {repr(exception_object)} of type {exception_type} " f"in {file} line #{line}")
            # needed?
            self.run = False
            return

        except TimeoutError:
            exception_type, exception_object, exception_traceback = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error(f"BleakClient(): TimeoutError: {repr(exception_object)} of type {exception_type} " f"in {file} line #{line}")
            # needed?
            self.run = False
            return

        except Exception:
            exception_type, exception_object, exception_traceback = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error(f"BleakClient(): Exception occurred: {repr(exception_object)} of type {exception_type} " f"in {file} line #{line}")
            # needed?
            self.run = False
            return

    def background_loop(self):
        while self.run and self.main_thread.is_alive():
            asyncio.run(self.bt_main_loop())

    async def async_test_connection(self):
        if self.hci_uart_ok:
            self.ready_event = asyncio.Event()
            if not self.bt_thread.is_alive():
                self.bt_thread.start()

                def shutdown_ble_atexit(thread):
                    self.run = False
                    thread.join()

                atexit.register(shutdown_ble_atexit, self.bt_thread)
            try:
                return await asyncio.wait_for(self.ready_event.wait(), timeout=5)
            except asyncio.TimeoutError:
                logger.error(">>> ERROR: Unable to connect with BLE device")
                return False
        else:
            return False

    async def _detect_uuids(self) -> bool:
        """
        Auto-detect which BLE UUIDs the BMS uses by checking available characteristics.
        Returns True if detection succeeded.
        """
        logger.info("Auto-detecting BLE UUIDs...")

        if not self.bt_client:
            logger.error(">>> ERROR: No BLE client for UUID detection")
            return False

        # Get all characteristics from the device (Bleak 3.x API)
        try:
            services = self.bt_client.services
            char_uuids = [str(char.uuid) for service in services for char in service.characteristics]

            # Check for alternative (DH04) UUIDs first since they're more specific
            if BLE_CHARACTERISTICS_RX_UUID_ALT in char_uuids and BLE_CHARACTERISTICS_TX_UUID_ALT in char_uuids:
                self._use_alt_uuids = True
                logger.info("Using alternative UUIDs for DH04 variant (fff1/fff2)")
                return True

            # Check for default JBD UUIDs
            if BLE_CHARACTERISTICS_RX_UUID in char_uuids and BLE_CHARACTERISTICS_TX_UUID in char_uuids:
                self._use_alt_uuids = False
                logger.info("Using default JBD UUIDs (ff01/ff02)")
                return True

            logger.error(f">>> ERROR: No known BLE UUIDs found. Available: {char_uuids}")
            return False

        except Exception as e:
            logger.error(f">>> ERROR: Failed to detect UUIDs: {e}")
            return False

    def test_connection(self):
        # call a function that will connect to the battery, send a command and retrieve the result.
        # The result or call should be unique to this BMS. Battery name or version, etc.
        # Return True if success, False for failure
        result = False
        try:
            if self.address:
                result = True
            if result and asyncio.run(self.async_test_connection()):
                result = True
            if result:
                # Auto-detect which UUIDs the BMS uses
                if self.bt_loop:
                    detection_task = asyncio.run_coroutine_threadsafe(self._detect_uuids(), self.bt_loop)
                    if not detection_task.result(timeout=10):
                        logger.error(">>> ERROR: Could not detect BLE UUIDs")
                        return False
                else:
                    logger.error(">>> ERROR: No BLE event loop")
                    return False
                result = super().test_connection()
        except Exception:
            exception_type, exception_object, exception_traceback = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
            result = False

        return result

    def unique_identifier(self) -> str:
        """
        Used to identify a BMS when multiple BMS are connected
        If not provided by the BMS/driver then the hardware version and capacity is used,
        since it can be changed by small amounts to make a battery unique.
        On +/- 5 Ah you can identify 11 batteries
        """
        return self.address.replace(":", "").lower()

    def _rx_callback(self, sender, rx: bytearray):
        """Persistent BLE notification callback"""
        self.response_buffer.extend(rx)
        if len(self.response_buffer) >= 4:
            length = self.response_buffer[self.LENGTH_POS]
            expected_len = length + 7
            if len(self.response_buffer) >= expected_len:
                if self.response_future and not self.response_future.done():
                    self.response_future.set_result(bytes(self.response_buffer[:expected_len]))
                # Clear processed data
                self.response_buffer = self.response_buffer[expected_len:]

    async def send_command(self, command) -> Union[bytearray, bool]:
        if not self.bt_client:
            logger.error(">>> ERROR: No BLE client connection - returning")
            return False

        # Select UUIDs based on detection result
        tx_uuid = BLE_CHARACTERISTICS_TX_UUID_ALT if self._use_alt_uuids else BLE_CHARACTERISTICS_TX_UUID
        rx_uuid = BLE_CHARACTERISTICS_RX_UUID_ALT if self._use_alt_uuids else BLE_CHARACTERISTICS_RX_UUID

        # Start notification if not already active
        if not self.notify_active:
            await self.bt_client.start_notify(rx_uuid, self._rx_callback)
            self.notify_active = True
            await asyncio.sleep(0.2)  # Wait for notification to be ready

        # Prepare for response
        self.response_buffer = bytearray()
        self.response_future = self.bt_loop.create_future()

        # Send command
        await self.bt_client.write_gatt_char(tx_uuid, command, False)

        try:
            result = await asyncio.wait_for(self.response_future, timeout=5.0)
            return bytearray(result)
        except asyncio.TimeoutError:
            logger.error(">>> ERROR: BLE response timeout")
            return False

    async def async_read_serial_data_llt(self, command):
        if self.hci_uart_ok:
            try:
                bt_task = asyncio.run_coroutine_threadsafe(self.send_command(command), self.bt_loop)
                result = await asyncio.wait_for(asyncio.wrap_future(bt_task), 20)
                return result
            except asyncio.TimeoutError:
                get_connection_error_message(self.online)
                return False
            except BleakDBusError:
                exception_type, exception_object, exception_traceback = sys.exc_info()
                file = exception_traceback.tb_frame.f_code.co_filename
                line = exception_traceback.tb_lineno
                logger.error(f"BleakDBusError: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
                self.reset_bluetooth()
                return False
            except Exception:
                exception_type, exception_object, exception_traceback = sys.exc_info()
                file = exception_traceback.tb_frame.f_code.co_filename
                line = exception_traceback.tb_lineno
                logger.error(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
                self.reset_bluetooth()
                return False
        else:
            return False

    def read_serial_data_llt(self, command):
        if not self.bt_loop:
            return False
        try:
            data = asyncio.run(self.async_read_serial_data_llt(command))
            return self.validate_packet(data)
        except CancelledError as e:
            logger.error(">>> ERROR: No reply - canceled - returning")
            logger.error(e)
            return False
        # except Exception as e:
        #     get_connection_error_message(self.online)
        #     logger.error(e)
        #     return False
        except Exception:
            exception_type, exception_object, exception_traceback = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
            return False

    def reset_bluetooth(self):
        if not BLUETOOTH_FORCE_RESET_BLE_STACK:
            return

        self.bt_loop = False

        restart_ble_hardware_and_bluez_driver()

    def reset_hci_uart(self):
        logger.error("Reset of hci_uart stack... Reconnecting to: " + self.address)
        self.run = False
        os.system("pkill -f 'hciattach'")
        sleep(0.5)
        os.system("rmmod hci_uart")
        os.system("rmmod btbcm")
        os.system("modprobe hci_uart")
        os.system("modprobe btbcm")
        sys.exit(1)
        # execfile = open("/tmp/dbus-blebattery-hciattach", "r")
        # sleep(5)
        # os.system(execfile.readline())
        # os.system(execfile.readline())
        # execfile.close()
        # sleep(0.5)


if __name__ == "__main__":
    bat = LltJbd_Ble("Foo", -1, sys.argv[1])
    if not bat.test_connection():
        logger.error(">>> ERROR: Unable to connect")
    else:
        # Allow to change charge / discharge FET
        bat.charge_fet = True
        bat.discharge_fet = True

        bat.trigger_disable_balancer = True
        bat.trigger_force_disable_charge = True
        bat.trigger_force_disable_discharge = True
        bat.refresh_data()
        bat.trigger_disable_balancer = False
        bat.trigger_force_disable_charge = False
        bat.trigger_force_disable_discharge = False
        bat.refresh_data()
        bat.get_settings()
