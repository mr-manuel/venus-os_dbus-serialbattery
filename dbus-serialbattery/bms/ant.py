# -*- coding: utf-8 -*-

# ANT BMS is disabled by default as it causes issues with other devices
# can be enabled by specifying it in the BMS_TYPE setting in the "config.ini"
# https://github.com/Louisvdw/dbus-serialbattery/issues/479

from battery import Battery
from utils import read_serial_data, logger, MIN_CELL_VOLTAGE
from struct import unpack_from
import sys


class ANT(Battery):
    def __init__(self, port, baud, address):
        super(ANT, self).__init__(port, baud, address)
        self.type = self.BATTERYTYPE
        self.history.exclude_values_to_calculate = ["charge_cycles", "total_ah_drawn"]

    command_general = b"\xDB\xDB\x00\x00\x00\x00"
    # command_capacity_low = b"\x5A\x5A\x1F\x00\x00\x1F"
    # command_capacity_high = b"\x5A\x5A\x20\x00\x00\x20"
    balancing = 0
    BATTERYTYPE = "ANT"
    LENGTH_CHECK = -1
    LENGTH_POS = 139
    LENGTH_FIXED = 140

    def test_connection(self):
        """
        call a function that will connect to the battery, send a command and retrieve the result.
        The result or call should be unique to this BMS. Battery name or version, etc.
        Return True if success, False for failure
        """
        result = False
        try:
            # get settings to check if the data is valid and the connection is working
            result = self.get_settings()
            # get the rest of the data to be sure, that all data is valid and the correct battery type is recognized
            # only read next data if the first one was successful, this saves time when checking multiple battery types
            result = result and self.refresh_data()
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

    def get_settings(self):
        # After successful connection get_settings() will be called to set up the battery
        # Set the current limits, populate cell count, etc
        # Return True if success, False for failure
        self.version = "ANT BMS V2.0"
        logger.info(self.hardware_version)
        return True

    def refresh_data(self):
        # call all functions that will refresh the battery data.
        # This will be called for every iteration (1 second)
        # Return True if success, False for failure
        result = self.read_status_data()
        return result

    def read_status_data(self):
        status_data = self.read_serial_data_ant(self.command_general)
        # check if connection success
        if status_data is False:
            return False

        voltage = unpack_from(">H", status_data, 4)
        self.voltage = voltage[0] * 0.1

        current, self.soc = unpack_from(">lB", status_data, 70)
        self.current = 0.0 if current == 0 else current / -10

        self.cell_count = unpack_from(">b", status_data, 123)[0]

        cell_max_no, cell_max_voltage, cell_min_no, cell_min_voltage = unpack_from(">bhbh", status_data, 115)
        self.cell_max_no = cell_max_no - 1
        self.cell_min_no = cell_min_no - 1
        self.cell_max_voltage = cell_max_voltage / 1000
        self.cell_min_voltage = cell_min_voltage / 1000

        capacity = unpack_from(">L", status_data, 75)
        self.capacity = capacity[0] / 1000000

        capacity_remain = unpack_from(">L", status_data, 79)
        self.capacity_remain = capacity_remain[0] / 1000000

        total_ah_drawn = unpack_from(">L", status_data, 83)
        self.history.total_ah_drawn = total_ah_drawn[0] / 1000
        self.history.charge_cycles = self.history.total_ah_drawn / self.capacity

        self.charge_fet, self.discharge_fet, self.balancing = unpack_from(">bbb", status_data, 103)

        self.temp1, self.temp2 = unpack_from(">bxb", status_data, 96)

        self.hardware_version = "ANT BMS " + str(self.cell_count) + "S"

        # Alarms
        self.protection.high_voltage = 2 if self.charge_fet == 2 else 0
        self.protection.low_voltage = 2 if self.discharge_fet == 2 or self.discharge_fet == 5 else 0
        self.protection.low_cell_voltage = 2 if self.cell_min_voltage < MIN_CELL_VOLTAGE - 0.1 else 1 if self.cell_min_voltage < MIN_CELL_VOLTAGE else 0
        self.protection.high_charge_temp = 1 if self.charge_fet == 3 or self.charge_fet == 6 else 0
        self.protection.high_temperature = 1 if self.discharge_fet == 7 or self.discharge_fet == 6 else 0
        self.protection.high_charge_current = 2 if self.charge_fet == 3 else 0
        self.protection.high_discharge_current = 2 if self.discharge_fet == 3 else 0

        return True

    def get_balancing(self):
        return 1 if self.balancing or self.balancing == 2 else 0

    def read_serial_data_ant(self, command):
        # use the read_serial_data() function to read the data and then do BMS spesific checks (crc, start bytes, etc)
        data = read_serial_data(
            command,
            self.port,
            self.baud_rate,
            self.LENGTH_POS,
            self.LENGTH_CHECK,
            self.LENGTH_FIXED,
        )
        if data is False:
            logger.error(">>> ERROR: Incorrect Data")
            return False

        if len(data) == self.LENGTH_FIXED:
            return data
        else:
            logger.error(">>> ERROR: Incorrect Reply")
            return False
