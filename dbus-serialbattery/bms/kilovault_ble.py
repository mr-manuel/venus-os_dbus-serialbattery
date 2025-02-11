from battery import Battery, Cell
import struct
import binascii
import atexit
import threading
import sys
import asyncio
from bleak import BleakClient
from time import time
from utils import logger
from typing import Optional


class Kilovault_Ble(Battery):

    MODEL_NBR_UUID = "2A24"
    KILOVAULT_BMS_SERVICE_UUID = "FFE0"
    KILOVAULT_BMS_NOTIFY_CHARACTERISTIC_UUID = "FFE4"
    KILOVAULT_BMS_NAME_CHARACTERISTIC_UUID = "FFE6"
    KILOVAULT_START_END_BYTE = 0xB0

    def __init__(self, port, baud, address):
        super(Kilovault_Ble, self).__init__(port, baud, address)
        self.type = self.BATTERYTYPE
        self.history.exclude_values_to_calculate = []

        logger.info(f"Kilovault_Ble: port={port} baud={baud} address={address}")

        # we create a new background thread for processing commands on the BLE connection
        self.main_thread = threading.current_thread()
        self.bt_thread = threading.Thread(name="Kilovault_Ble_Loop", target=self.background_loop, daemon=True)
        self.client: Optional[BleakClient] = None
        self.run = True

        # This is the BLE address for the battery
        self.address = address
        self._device_name = None

        # we get many notifications for one status update, this accumulates them
        self.status_buffer = bytearray()
        # signalled when we've received status
        self.valid_data_event = threading.Event()
        # this is our BLE client object
        self.client = None
        self.notifyService = None

        # last notification update time
        self.lastUpdateTime = time()

        self._charge_cycles = 0
        self._temperature = None
        self._status = 0
        self.cell_count = 0
        # This BMS supports a maximum of 16 cells.  The number populated is in cell_count
        self._cellvoltage = [0] * 16

    BATTERYTYPE = "Kilovault HLX+ BLE"

    # BMS specific, could be removed, if not needed
    LENGTH_CHECK = 4

    # BMS specific, could be removed, if not needed
    LENGTH_POS = 3

    # Start getting notifications from the BMS.  These arrive roughly once per second.
    # This function completes after the first notification has returned.
    async def connection_thread(self):
        logger.info(f"Starting connection to {self.address}")
        try:

            async with BleakClient(self.address) as client:
                self.client = client
                # register a callback to stop notifications
                atexit.register(self.stop_notifications_and_disconnect)
                # find the BMS service out of the list of services
                bmsService = self.client.services.get_service(self.KILOVAULT_BMS_SERVICE_UUID)
                # get the device name
                deviceName = await self.client.read_gatt_char(self.KILOVAULT_BMS_NAME_CHARACTERISTIC_UUID)
                self._device_name = deviceName.decode("utf-8").rstrip()
                # find the notification service that hangs off of the BMS
                self.notifyService = bmsService.get_characteristic(self.KILOVAULT_BMS_NOTIFY_CHARACTERISTIC_UUID)
                # turn on notifications.  Data is sent to notifyCallback
                await self.client.start_notify(self.notifyService, self.notifyCallback)
                logger.info(f"Connected to {self.address}")
                while self.run and self.main_thread.is_alive() and time() - self.lastUpdateTime < 10:
                    await asyncio.sleep(0.1)
            logger.info(f"Disconnected from {self.address}")
            logger.info(f"self.run: {self.run}")
            return True
        except Exception:
            (
                exception_type,
                exception_object,
                exception_traceback,
            ) = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error(f"Connection failure occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
            return False

    def stop_notifications_and_disconnect(self):
        logger.info("Stopping notifications and disconnecting")
        self.run = False
        self.bt_thread.join()

    # this is the body of the worker thread loop.  It just tries to stay connected to the battery
    def background_loop(self):
        while self.run and self.main_thread.is_alive():
            asyncio.run(self.connection_thread())

    # this is called for each frame from the BMS.  We assemble
    # the frames until we get a full status block.  Status
    # starts and ends with 0xB0
    def notifyCallback(self, sender, data):
        self.lastUpdateTime = time()
        # logger.debug(f"Received notification from {sender}: {data}")
        if data[0] == self.KILOVAULT_START_END_BYTE:
            if len(self.status_buffer) > 0 and self.status_buffer[0] == self.KILOVAULT_START_END_BYTE:
                decode_buffer = self.status_buffer[1:]
                self.status_buffer = data
                # logger.info(f"Decoding KV BLE status buffer: {decode_buffer}")
                self.decode_status_buffer(decode_buffer)
            else:
                self.status_buffer = data
        else:
            self.status_buffer.extend(data)

    # This function decodes status
    #
    # This is gross.  The buffer contains a hex string, except for the first
    # byte which is b0.  We have to manually process that back to useful
    # numbers and that is what this function does.
    #
    # offsets in here are nibbles (4 bits)
    def decode_status_buffer(self, data):
        x = data.find(bytearray("RR", "ascii"))
        # convert the hex string back into binary
        try:
            bindata = binascii.unhexlify(data[0:x])
        except Exception as e:
            logger.warning(f"Ignoring invalid buffer: {repr(e)}")
            return False

        logger.debug(f"Decoding KV BLE status buffer: {data}")

        # unpack the binary data
        if len(bindata) < 56:
            logger.warning(f"Incomplete buffer length: {len(bindata)}")
            return False
        unpacked_data = struct.unpack("<hhiIhhhIhhhhhhhhhhhhhhhhh", bindata[0:56])

        # process into output values
        i = (x for x in range(len(unpacked_data)))
        self.voltage = float(unpacked_data[next(i)]) * 0.001
        unpacked_data[next(i)]  # unknown value at unpacked_data[1]
        self.current = float(unpacked_data[next(i)]) * 0.001
        self.capacity = float(unpacked_data[next(i)]) * 0.001
        self._charge_cycles = unpacked_data[next(i)]
        self.soc = unpacked_data[next(i)]
        self._temperature = float(unpacked_data[next(i)] * 0.1) - 273.15
        self._status = unpacked_data[next(i)]

        # decode the cell voltages.  The encoded data supports up to 16 cells, but sets non-existant
        # cells to 0.
        for cell in range(16):
            self._cellvoltage[cell] = float(unpacked_data[next(i)]) * 0.001

        # This only is executed on the first pass
        if self.cell_count == 0:
            for cell in range(16):
                if self._cellvoltage[cell] > 0:
                    self.cells.append(Cell(False))
                else:  # voltage is 0
                    self.cell_count = cell
                    break

            if self.cell_count == 0:
                self.cell_count = 16

        # This can only be run once we've figured out cell_count
        for b in range(self.cell_count):
            self.cells[b].voltage = self._cellvoltage[b]

        # checksum = unpacked_data[next(i)]

        logger.debug("decode complete")

        self.valid_data_event.set()
        return True

    async def async_test_connection(self):
        if not self.bt_thread.is_alive():
            self.bt_thread.start()

    # This creates the initial connection to the BMS
    def test_connection(self):
        result = False
        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(self.async_test_connection())
            # wait for the first notification to be complete
            self.valid_data_event.wait()
            result = True
        except Exception:
            (
                exception_type,
                exception_object,
                exception_traceback,
            ) = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
            result = False

        return result

    def connection_name(self) -> str:
        return "BLE " + self.address

    def custom_name(self) -> str:
        if self._device_name is not None:
            return self._device_name
        else:
            return "SerialBattery(" + self.type + ") " + self.address[-5:]

    def unique_identifier(self) -> str:
        """
        Serial number reported by the battery is bogus, so we just use the battery name
        """
        return self.custom_name()

    def get_settings(self):
        return True

    def refresh_data(self):
        # most values are set in decode_status_buffer

        # temperature sensor 1 in °C (float)
        if self._temperature is not None:
            self.to_temperature(1, self._temperature)

        # any of these errors will shutdown the BMS
        if (self._status & 0xFF) > 0:
            self.charge_fet = False
            self.discharge_fet = False
            self.balance_fet = False
        else:
            self.charge_fet = True
            self.discharge_fet = True
            self.balance_fet = True

        # PROTECTION values
        # 2 = alarm, 1 = warningm 0 = ok
        # high battery voltage alarm (int)
        self.protection.high_voltage = 2 if (self._status & 0x80) > 0 else 0

        # low battery voltage alarm (int)
        self.protection.low_voltage = 2 if (self._status & 0x40) > 0 else 0

        # high charge current alarm (int)
        self.protection.high_charge_current = 2 if (self._status & 0x20) > 0 else 0

        # high discharge current alarm (int)
        self.protection.high_discharge_current = 2 if (self._status & 0x10) > 0 else 0

        # high charge temperature alarm (int)
        self.protection.high_charge_temperature = 2 if (self._status & 0x1 > 0) else 0

        # low charge temperature alarm (int)
        self.protection.low_charge_temperature = 2 if (self._status & 0x4 > 0) else 0

        # high temperature alarm (int)
        self.protection.high_temperature = 2 if (self._status & 0x2 > 0) else 0

        # low temperature alarm (int)
        self.protection.low_temperature = 2 if (self._status & 0x8 > 0) else 0

        return True
