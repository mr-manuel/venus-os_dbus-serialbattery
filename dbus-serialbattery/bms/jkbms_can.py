# -*- coding: utf-8 -*-

# NOTES
# Added by https://github.com/IrisCrimson
# Reworked by https://github.com/Hooorny and https://github.com/mr-manuel
# https://github.com/mr-manuel/venus-os_dbus-serialbattery/pull/108

# TODO
# - Implement controlling of BMS, see protocol documentation 7.1 (Ctrl_INFO)


from __future__ import absolute_import, division, print_function, unicode_literals
from battery import Battery, Cell
from utils import bytearray_to_string, logger
from struct import unpack_from
from typing import Union
from time import time
import sys


class Jkbms_Can(Battery):
    def __init__(self, port, baud, address):
        super(Jkbms_Can, self).__init__(port, baud, address)
        self.cell_count = 0
        self.type = self.BATTERYTYPE
        self.history.exclude_values_to_calculate = ["charge_cycles", "total_ah_drawn"]

        # If multiple BMS are used simultaneously, the device address can be set via the dip switches on the BMS
        # (default address is 0, all switches down) to change the CAN frame ID sent by the BMS
        self.device_address = int.from_bytes(address, byteorder="big") if address is not None else 0
        self.last_error_time = 0
        self.error_active = False
        self.protocol_version = None
        self.v1_max_cell_nr = None
        self.v1_min_cell_nr = None

    BATTERYTYPE = "JKBMS CAN"

    BATT_STAT = "BATT_STAT"
    CELL_VOLT = "CELL_VOLT"
    CELL_TEMP = "CELL_TEMP"
    ALM_INFO = "ALM_INFO"

    BATT_STAT_EXT = "BATT_STAT_EXT"
    ALL_TEMP = "ALL_TEMP"
    BMSERR_INFO = "BMSERR_INFO"
    BMS_INFO = "BMS_INFO"
    BMS_SWITCH_STATE = "BMS_SWITCH_STATE"
    CELL_VOLT_EXT1 = "CELL_VOLT_EXT1"
    CELL_VOLT_EXT2 = "CELL_VOLT_EXT2"
    CELL_VOLT_EXT3 = "CELL_VOLT_EXT3"
    CELL_VOLT_EXT4 = "CELL_VOLT_EXT4"
    CELL_VOLT_EXT5 = "CELL_VOLT_EXT5"
    CELL_VOLT_EXT6 = "CELL_VOLT_EXT6"
    BMS_CHG_INFO = "BMS_CHG_INFO"

    CAN_FRAMES = {
        BATT_STAT: [0x02F4],
        CELL_VOLT: [0x04F4],
        CELL_TEMP: [0x05F4],
        ALM_INFO: [0x07F4],
        BATT_STAT_EXT: [0x18F128F4],
        ALL_TEMP: [0x18F228F4],
        BMSERR_INFO: [0x18F328F4],
        BMS_INFO: [0x18F428F4],
        BMS_SWITCH_STATE: [0x18F528F4],
        CELL_VOLT_EXT1: [0x18E028F4],
        CELL_VOLT_EXT2: [0x18E128F4],
        CELL_VOLT_EXT3: [0x18E228F4],
        CELL_VOLT_EXT4: [0x18E328F4],
        CELL_VOLT_EXT5: [0x18E428F4],
        CELL_VOLT_EXT6: [0x18E528F4],
        BMS_CHG_INFO: [0x1806E5F4],
    }

    def connection_name(self) -> str:
        return f"CAN socketcan:{self.port}" + (f"__{self.device_address}" if self.device_address != 0 else "")

    def unique_identifier(self) -> str:
        """
        Used to identify a BMS when multiple BMS are connected
        Provide a unique identifier from the BMS to identify a BMS, if multiple same BMS are connected
        e.g. the serial number
        If there is no such value, please remove this function
        """
        return self.port + ("__" + bytearray_to_string(self.address).replace("\\", "0") if self.address is not None else "")

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

            # if there are no messages in the cache after sleeping, something is wrong
            if not self.can_message_cache_callback().items():
                logger.error("Error: found no messages on can bus, is it properly configured?")
                result = False

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

        return True

    def refresh_data(self):
        # call all functions that will refresh the battery data.
        # This will be called for every iteration (1 second)
        # Return True if success, False for failure
        result = self.read_jkbms_can()
        # check if connection success
        if result is False:
            return False

        return True

    def to_protection_bits(self, byte_data):
        tmp = bin(byte_data | 0xFF00000000)
        pos = len(tmp)
        logger.debug(tmp)
        self.protection.high_cell_voltage = 2 if int(tmp[pos - 2 : pos], 2) > 0 else 0
        self.protection.low_cell_voltage = 2 if int(tmp[pos - 4 : pos - 2], 2) > 0 else 0
        self.protection.high_voltage = 2 if int(tmp[pos - 6 : pos - 4], 4) > 0 else 0
        self.protection.low_voltage = 2 if int(tmp[pos - 8 : pos - 6], 2) > 0 else 0
        self.protection.cell_imbalance = 2 if int(tmp[pos - 10 : pos - 8], 2) > 0 else 0
        self.protection.high_discharge_current = 2 if int(tmp[pos - 12 : pos - 10], 2) > 0 else 0
        self.protection.high_charge_current = 2 if int(tmp[pos - 14 : pos - 12], 2) > 0 else 0

        # there is just a BMS and Battery temp alarm (not for charge and discharge)
        self.protection.high_charge_temp = 2 if int(tmp[pos - 16 : pos - 14], 2) > 0 else 0
        self.protection.high_temperature = 2 if int(tmp[pos - 16 : pos - 14], 2) > 0 else 0
        self.protection.low_charge_temp = 2 if int(tmp[pos - 18 : pos - 16], 2) > 0 else 0
        self.protection.low_temperature = 2 if int(tmp[pos - 18 : pos - 16], 2) > 0 else 0
        self.protection.high_charge_temp = 2 if int(tmp[pos - 20 : pos - 18], 2) > 0 else 0
        self.protection.high_temperature = 2 if int(tmp[pos - 20 : pos - 18], 2) > 0 else 0
        self.protection.low_soc = 2 if int(tmp[pos - 22 : pos - 20], 2) > 0 else 0
        self.protection.internal_failure = 2 if int(tmp[pos - 24 : pos - 22], 2) > 0 else 0
        self.protection.internal_failure = 2 if int(tmp[pos - 26 : pos - 24], 2) > 0 else 0
        self.protection.internal_failure = 2 if int(tmp[pos - 28 : pos - 26], 2) > 0 else 0
        self.protection.internal_failure = 2 if int(tmp[pos - 30 : pos - 28], 2) > 0 else 0

    def reset_protection_bits(self):
        self.protection.high_cell_voltage = 0
        self.protection.low_cell_voltage = 0
        self.protection.high_voltage = 0
        self.protection.low_voltage = 0
        self.protection.cell_imbalance = 0
        self.protection.high_discharge_current = 0
        self.protection.high_charge_current = 0

        # there is just a BMS and Battery temp alarm (not for charge and discharge)
        self.protection.high_charge_temp = 0
        self.protection.high_temperature = 0
        self.protection.low_charge_temp = 0
        self.protection.low_temperature = 0
        self.protection.high_charge_temp = 0
        self.protection.high_temperature = 0
        self.protection.low_soc = 0
        self.protection.internal_failure = 0
        self.protection.internal_failure = 0
        self.protection.internal_failure = 0
        self.protection.internal_failure = 0

    def update_cell_voltages(self, start_index, end_index, data):
        for i in range(start_index, end_index + 1):
            cell_voltage = unpack_from("<H", data[2 * (i - start_index) : 2 * (i - start_index) + 2])[0] / 1000
            if cell_voltage > 0:
                if len(self.cells) <= i:
                    self.cells.insert(i, Cell(False))
                    self.cell_count = len(self.cells)
                self.cells[i].voltage = cell_voltage

    def read_jkbms_can(self):
        # reset errors after timeout
        if ((time() - self.last_error_time) > 120.0) and self.error_active is True:
            self.error_active = False
            self.reset_protection_bits()

        # check if all needed data is available
        data_check = 0

        for frame_id, data in self.can_message_cache_callback().items():
            normalized_arbitration_id = frame_id + self.device_address

            # Frame is send every 20ms
            if normalized_arbitration_id in self.CAN_FRAMES[self.BATT_STAT]:
                voltage = unpack_from("<H", bytes([data[0], data[1]]))[0]
                self.voltage = voltage / 10

                current = unpack_from("<H", bytes([data[2], data[3]]))[0]
                self.current = (current / 10) - 400

                self.soc = unpack_from("<B", bytes([data[4]]))[0]

                # self.time_to_go = unpack_from("<H", bytes([data[6], data[7]]))[0] * 36

                # check if all needed data is available
                data_check += 1

            # Frame is send every 100ms
            elif normalized_arbitration_id in self.CAN_FRAMES[self.BATT_STAT_EXT]:
                self.capacity_remain = unpack_from("<H", bytes([data[0], data[1]]))[0] / 10
                self.capacity = unpack_from("<H", bytes([data[2], data[3]]))[0] / 10
                self.history.total_ah_drawn = unpack_from("<H", bytes([data[4], data[5]]))[0] / 10
                self.history.charge_cycles = unpack_from("<H", bytes([data[6], data[7]]))[0]

                # check if all needed data is available
                data_check += 2

            # Frame is send every 100ms
            elif normalized_arbitration_id in self.CAN_FRAMES[self.ALM_INFO]:
                alarms = unpack_from(
                    "<L",
                    bytes([data[0], data[1], data[2], data[3]]),
                )[0]
                print("alarms %d" % (alarms))
                self.last_error_time = time()
                self.error_active = True
                self.to_protection_bits(alarms)

                # check if all needed data is available
                data_check += 4

            # Frame is send every 100ms
            # elif normalized_arbitration_id in self.CAN_FRAMES[self.BMSERR_INFO]:
            #    pass

            # Frame is send every 100ms
            elif normalized_arbitration_id in self.CAN_FRAMES[self.CELL_VOLT]:
                v1_max_cell_volt = unpack_from("<H", bytes([data[0], data[1]]))[0] / 1000
                self.v1_max_cell_nr = unpack_from("<B", bytes([data[2]]))[0]

                v1_min_cell_volt = unpack_from("<H", bytes([data[3], data[4]]))[0] / 1000
                self.v1_min_cell_nr = unpack_from("<B", bytes([data[5]]))[0]

                # logger.info(f"Min cell: {self.min_cell_nr} {min_cell_volt} - Max cell: {self.max_cell_nr} {max_cell_volt}")

                # check if all needed data is available
                data_check += 8

            # Frame is send every 500ms
            elif normalized_arbitration_id in self.CAN_FRAMES[self.CELL_TEMP]:
                v1_max_temp = unpack_from("<B", bytes([data[0]]))[0] - 50
                v1_max_nr = unpack_from("<B", bytes([data[1]]))[0]
                v1_min_temp = unpack_from("<B", bytes([data[2]]))[0] - 50
                v1_min_nr = unpack_from("<B", bytes([data[3]]))[0]

                # store temperatures in a dict to assign the temperature to the correct sensor
                v1_temperatures = {v1_min_nr: v1_min_temp, v1_max_nr: v1_max_temp}

                # check if all needed data is available
                data_check += 16

            # Frame is send every 500ms
            elif normalized_arbitration_id in self.CAN_FRAMES[self.ALL_TEMP]:
                # temp_sensor_cnt = unpack_from("<B", bytes([data[0]]))[0]
                # temp1
                if data[1] != 0x00:
                    temp1 = unpack_from("<B", bytes([data[1]]))[0] - 50
                    self.to_temp(1, temp1)
                # temp2
                if data[2] != 0x00:
                    temp2 = unpack_from("<B", bytes([data[2]]))[0] - 50
                    self.to_temp(2, temp2)
                # temp3 equals mosfet temp
                if data[3] != 0x00:
                    temp_mosfet = unpack_from("<B", bytes([data[3]]))[0] - 50
                    self.to_temp(0, temp_mosfet)
                # temp4 (currently only JKBMS PB Model)
                if data[4] != 0x00:
                    temp4 = unpack_from("<B", bytes([data[4]]))[0] - 50
                    self.to_temp(3, temp4)
                # temp5 (currently only JKBMS PB Model)
                if data[5] != 0x00:
                    temp5 = unpack_from("<B", bytes([data[5]]))[0] - 50
                    self.to_temp(4, temp5)

                # check if all needed data is available
                data_check += 32

            # Frame is send every 500ms
            # elif normalized_arbitration_id in self.CAN_FRAMES[self.BMS_INFO]:
            #    pass

            # Frame is send every 500ms
            elif normalized_arbitration_id in self.CAN_FRAMES[self.BMS_SWITCH_STATE]:
                switch_state_bytes = unpack_from("<B", bytes([data[0]]))[0]
                # logger.info(switch_state_bytes)
                self.charge_fet = bool((switch_state_bytes >> 0) & 0x01)
                self.discharge_fet = bool((switch_state_bytes >> 1) & 0x01)
                # set balance status, if only a common balance status is available (bool)
                # not needed, if balance status is available for each cell
                self.balancing = bool((switch_state_bytes >> 2) & 0x01)
                if self.get_min_cell() is not None and self.get_max_cell() is not None and self.cell_count > 1:
                    for c in range(self.cell_count):
                        if self.balancing and (self.get_min_cell() == c or self.get_max_cell() == c):
                            self.cells[c].balance = True
                        else:
                            self.cells[c].balance = False

                # check if all needed data is available
                data_check += 64

            # Frame is send every 1000ms
            elif normalized_arbitration_id in self.CAN_FRAMES[self.CELL_VOLT_EXT1]:
                self.update_cell_voltages(0, 3, data)
                # check if all needed data is available
                # this is important to differentiate between the JKBMS CAN V1 and V2
                data_check += 128

            # Frame is send every 1000ms, if the BMS has more than 4 cells
            elif normalized_arbitration_id in self.CAN_FRAMES[self.CELL_VOLT_EXT2]:
                self.update_cell_voltages(4, 7, data)
            # Frame is send every 1000ms, if the BMS has more than 8 cells
            elif normalized_arbitration_id in self.CAN_FRAMES[self.CELL_VOLT_EXT3]:
                self.update_cell_voltages(8, 11, data)
            # Frame is send every 1000ms, if the BMS has more than 12 cells
            elif normalized_arbitration_id in self.CAN_FRAMES[self.CELL_VOLT_EXT4]:
                self.update_cell_voltages(12, 15, data)
            # Frame is send every 1000ms, if the BMS has more than 16 cells
            elif normalized_arbitration_id in self.CAN_FRAMES[self.CELL_VOLT_EXT5]:
                self.update_cell_voltages(16, 19, data)
            # Frame is send every 1000ms, if the BMS has more than 20 cells
            elif normalized_arbitration_id in self.CAN_FRAMES[self.CELL_VOLT_EXT6]:
                self.update_cell_voltages(20, 23, data)

        # fetch data from min/max values if protocol is JKBMS CAN V1 (extra frames missing)
        if data_check < 128:

            if self.cell_count == 0:
                self.cell_count = 2
                self.cells = [Cell(False) for _ in range(self.cell_count)]

            if self.cell_count == len(self.cells):
                self.cells[1].voltage = v1_max_cell_volt
                # self.cells[1].balance = True

                self.cells[0].voltage = v1_min_cell_volt
                # self.cells[0].balance = True

                self.to_temp(1, v1_temperatures[0] if v1_temperatures[0] <= 100 else 100)
                self.to_temp(2, v1_temperatures[1] if v1_temperatures[1] <= 100 else 100)

            self.protocol_version = 1
            self.type = "JKBMS CAN"

        else:
            self.protocol_version = 2
            self.type = "JKBMS CAN V2"

        if self.hardware_version is None:
            self.hardware_version = "JKBMS CAN" + (" V2" + str(self.cell_count) + "S" if self.protocol_version == 2 else "")

        # check if all needed data is available
        # sum of all data checks except for alarms
        logger.debug("Data check: %d" % (data_check))
        if data_check == 0:
            logger.error(">>> ERROR: No reply - returning")
            return False

        return True

    def get_min_cell_desc(self) -> Union[str, None]:
        """
        Get the description of the cell with the lowest voltage.

        :return: The description of the cell with the lowest voltage
        """
        if self.protocol_version == 1:
            return f"C{self.v1_min_cell_nr}" if self.v1_min_cell_nr is not None else ""

        cell_no = self.get_min_cell()
        return cell_no if cell_no is None else "C" + str(cell_no + 1)

    def get_max_cell_desc(self) -> Union[str, None]:
        """
        Get the description of the cell with the highest voltage.

        :return: The description of the cell with the highest voltage
        """
        if self.protocol_version == 1:
            return f"C{self.v1_max_cell_nr}" if self.v1_max_cell_nr is not None else ""

        cell_no = self.get_max_cell()
        return cell_no if cell_no is None else "C" + str(cell_no + 1)
