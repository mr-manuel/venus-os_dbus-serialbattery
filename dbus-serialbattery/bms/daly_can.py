# -*- coding: utf-8 -*-

# NOTES
# Added by https://github.com/SamuelBrucksch
# https://github.com/Louisvdw/dbus-serialbattery/pull/169
# Reworked by https://github.com/mr-manuel


from __future__ import absolute_import, division, print_function, unicode_literals
from battery import Battery, Cell
from utils import (
    BATTERY_CAPACITY,
    bytearray_to_string,
    INVERT_CURRENT_MEASUREMENT,
    logger,
    MAX_BATTERY_CHARGE_CURRENT,
    MAX_BATTERY_DISCHARGE_CURRENT,
    MIN_CELL_VOLTAGE,
)
from struct import unpack_from
from time import time
import sys


class Daly_Can(Battery):
    def __init__(self, port, baud, address):
        super(Daly_Can, self).__init__(port, baud, address)
        self.charger_connected = None
        self.load_connected = None
        self.cell_min_voltage = None
        self.cell_max_voltage = None
        self.cell_min_no = None
        self.cell_max_no = None
        self.poll_interval = 1000
        self.poll_step = 0
        self.type = self.BATTERYTYPE
        self.can_bus = None
        self.device_address = int.from_bytes(address, byteorder="big") if address is not None else 0
        self.error_active = False
        self.last_error_time = 0
        self.history.exclude_values_to_calculate = ["charge_cycles"]

    COMMAND_BASE = "COMMAND_BASE"
    COMMAND_SOC = "COMMAND_SOC"
    COMMAND_MINMAX_CELL_VOLTS = "COMMAND_MINMAX_CELL_VOLTS"
    COMMAND_MINMAX_TEMP = "COMMAND_MINMAX_TEMP"
    COMMAND_FET = "COMMAND_FET"
    COMMAND_STATUS = "COMMAND_STATUS"
    COMMAND_CELL_VOLTS = "COMMAND_CELL_VOLTS"
    COMMAND_TEMP = "COMMAND_TEMP"
    COMMAND_CELL_BALANCE = "COMMAND_CELL_BALANCE"
    COMMAND_ALARM = "COMMAND_ALARM"

    RESPONSE_BASE = "RESPONSE_BASE"
    RESPONSE_SOC = "RESPONSE_SOC"
    RESPONSE_MINMAX_CELL_VOLTS = "RESPONSE_MINMAX_CELL_VOLTS"
    RESPONSE_MINMAX_TEMP = "RESPONSE_MINMAX_TEMP"
    RESPONSE_FET = "RESPONSE_FET"
    RESPONSE_STATUS = "RESPONSE_STATUS"
    RESPONSE_CELL_VOLTS = "RESPONSE_CELL_VOLTS"
    RESPONSE_TEMP = "RESPONSE_TEMP"
    RESPONSE_CELL_BALANCE = "RESPONSE_CELL_BALANCE"
    RESPONSE_ALARM = "RESPONSE_ALARM"

    # command bytes [Priority=18][Command=94][BMS ID=01][Uplink ID=40]
    CAN_FRAMES = {
        COMMAND_BASE: [0x18940140],
        COMMAND_SOC: [0x18900140],
        COMMAND_MINMAX_CELL_VOLTS: [0x18910140],
        COMMAND_MINMAX_TEMP: [0x18920140],
        COMMAND_FET: [0x18930140],
        COMMAND_STATUS: [0x18940140],
        COMMAND_CELL_VOLTS: [0x18950140],
        COMMAND_TEMP: [0x18960140],
        COMMAND_CELL_BALANCE: [0x18970140],
        COMMAND_ALARM: [0x18980140],
        RESPONSE_BASE: [0x18944001],
        RESPONSE_SOC: [0x18904001],
        RESPONSE_MINMAX_CELL_VOLTS: [0x18914001],
        RESPONSE_MINMAX_TEMP: [0x18924001],
        RESPONSE_FET: [0x18934001],
        RESPONSE_STATUS: [0x18944001],
        RESPONSE_CELL_VOLTS: [0x18954001],
        RESPONSE_TEMP: [0x18964001],
        RESPONSE_CELL_BALANCE: [0x18974001],
        RESPONSE_ALARM: [0x18984001],
    }

    BATTERYTYPE = "Daly CAN"
    LENGTH_CHECK = 4
    LENGTH_POS = 3
    CURRENT_ZERO_CONSTANT = 30000
    TEMP_ZERO_CONSTANT = 40

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
        self.capacity = BATTERY_CAPACITY

        return True

    def refresh_data(self):
        # call all functions that will refresh the battery data.
        # This will be called for every iteration (1 second)
        # Return True if success, False for failure
        result = self.read_daly_can()
        # check if connection success
        if result is False:
            return False

        return True

    def read_daly_can(self):
        # reset errors after timeout
        if ((time() - self.last_error_time) > 120.0) and self.error_active is True:
            self.error_active = False
            # Do the errors need to be reset for Daly CAN?
            # self.reset_protection_bits()

        # check if all needed data is available
        data_check = 0

        # CONSTANTS
        crntMinValid = -(MAX_BATTERY_DISCHARGE_CURRENT * 2.1)
        crntMaxValid = MAX_BATTERY_CHARGE_CURRENT * 1.3

        for frame_id, data in self.can_message_cache_callback().items():
            normalized_arbitration_id = frame_id + self.device_address

            # Status data
            if normalized_arbitration_id in self.CAN_FRAMES[self.COMMAND_STATUS]:
                (
                    self.cell_count,
                    temperature_sensors,
                    self.charger_connected,
                    self.load_connected,
                    state,
                    self.history.charge_cycles,
                ) = unpack_from(">BB??BHX", data)

                if self.cell_count != 0:
                    # check if all needed data is available
                    data_check += 1

            # SOC data
            elif normalized_arbitration_id in self.CAN_FRAMES[self.COMMAND_SOC]:

                voltage, tmp, current, soc = unpack_from(">HHHH", data)
                current = (current - self.CURRENT_ZERO_CONSTANT) / -10 * INVERT_CURRENT_MEASUREMENT
                # logger.info("voltage: " + str(voltage) + ", current: " + str(current) + ", soc: " + str(soc))
                if crntMinValid < current < crntMaxValid:
                    self.voltage = voltage / 10
                    self.current = current
                    self.soc = soc / 10

                    # check if all needed data is available
                    data_check += 1

            # Cell voltage data
            elif normalized_arbitration_id in self.CAN_FRAMES[self.COMMAND_CELL_VOLTS]:
                if self.cell_count is not None:

                    frameCell = [0, 0, 0]
                    lowMin = MIN_CELL_VOLTAGE / 2
                    frame = 0
                    bufIdx = 0

                    if len(self.cells) != self.cell_count:
                        # init the numbers of cells
                        self.cells = []
                        for idx in range(self.cell_count):
                            self.cells.append(Cell(True))

                    while bufIdx < len(data):
                        frame, frameCell[0], frameCell[1], frameCell[2] = unpack_from(">BHHH", data, bufIdx)
                        for idx in range(3):
                            cellnum = ((frame - 1) * 3) + idx  # daly is 1 based, driver 0 based
                            if cellnum >= self.cell_count:
                                break
                            cellVoltage = frameCell[idx] / 1000
                            self.cells[cellnum].voltage = None if cellVoltage < lowMin else cellVoltage
                        bufIdx += 8

            # Cell voltage range data
            elif normalized_arbitration_id in self.CAN_FRAMES[self.COMMAND_MINMAX_CELL_VOLTS]:
                (
                    cell_max_voltage,
                    self.cell_max_no,
                    cell_min_voltage,
                    self.cell_min_no,
                ) = unpack_from(">hbhb", data)
                # Daly cells numbers are 1 based and not 0 based
                self.cell_min_no -= 1
                self.cell_max_no -= 1
                # Voltage is returned in mV
                self.cell_max_voltage = cell_max_voltage / 1000
                self.cell_min_voltage = cell_min_voltage / 1000

            # Temperature range data
            elif normalized_arbitration_id in self.CAN_FRAMES[self.COMMAND_MINMAX_TEMP]:

                max_temp, max_no, min_temp, min_no = unpack_from(">BBBB", data)

                # store temperatures in a dict to assign the temperature to the correct sensor
                temperatures = {min_no: (min_temp - self.TEMP_ZERO_CONSTANT), max_no: (max_temp - self.TEMP_ZERO_CONSTANT)}

                self.to_temperature(1, temperatures[0])
                self.to_temperature(2, temperatures[1])

            # FET data
            elif normalized_arbitration_id in self.CAN_FRAMES[self.COMMAND_FET]:
                (
                    status,
                    self.charge_fet,
                    self.discharge_fet,
                    self.history.charge_cycles,
                    capacity_remain,
                ) = unpack_from(">b??BL", data)
                self.capacity_remain = capacity_remain / 1000

            # Alarm data
            elif normalized_arbitration_id in self.CAN_FRAMES[self.COMMAND_ALARM]:
                (
                    al_volt,
                    al_temp,
                    al_crnt_soc,
                    al_diff,
                    al_mos,
                    al_misc1,
                    al_misc2,
                    al_fault,
                ) = unpack_from(">BBBBBBBB", data)

                if al_volt & 48:
                    # High voltage levels - Alarm
                    self.protection.high_voltage = 2
                elif al_volt & 15:
                    # High voltage Warning levels - Pre-alarm
                    self.protection.high_voltage = 1
                else:
                    self.protection.high_voltage = 0

                if al_volt & 128:
                    # Low voltage level - Alarm
                    self.protection.low_voltage = 2
                elif al_volt & 64:
                    # Low voltage Warning level - Pre-alarm
                    self.protection.low_voltage = 1
                else:
                    self.protection.low_voltage = 0

                if al_temp & 2:
                    # High charge temp - Alarm
                    self.protection.high_charge_temperature = 2
                elif al_temp & 1:
                    # High charge temp - Pre-alarm
                    self.protection.high_charge_temperature = 1
                else:
                    self.protection.high_charge_temperature = 0

                if al_temp & 8:
                    # Low charge temp - Alarm
                    self.protection.low_charge_temperature = 2
                elif al_temp & 4:
                    # Low charge temp - Pre-alarm
                    self.protection.low_charge_temperature = 1
                else:
                    self.protection.low_charge_temperature = 0

                if al_temp & 32:
                    # High discharge temp - Alarm
                    self.protection.high_temperature = 2
                elif al_temp & 16:
                    # High discharge temp - Pre-alarm
                    self.protection.high_temperature = 1
                else:
                    self.protection.high_temperature = 0

                if al_temp & 128:
                    # Low discharge temp - Alarm
                    self.protection.low_temperature = 2
                elif al_temp & 64:
                    # Low discharge temp - Pre-alarm
                    self.protection.low_temperature = 1
                else:
                    self.protection.low_temperature = 0

                # if al_crnt_soc & 2:
                #    # High charge current - Alarm
                #    self.protection.high_charge_current = 2
                # elif al_crnt_soc & 1:
                #    # High charge current - Pre-alarm
                #    self.protection.high_charge_current = 1
                # else:
                #    self.protection.high_charge_current = 0

                # if al_crnt_soc & 8:
                #    # High discharge current - Alarm
                #    self.protection.high_charge_current = 2
                # elif al_crnt_soc & 4:
                #    # High discharge current - Pre-alarm
                #    self.protection.high_charge_current = 1
                # else:
                #    self.protection.high_charge_current = 0

                if al_crnt_soc & 2 or al_crnt_soc & 8:
                    # High charge/discharge current - Alarm
                    self.protection.high_charge_current = 2
                elif al_crnt_soc & 1 or al_crnt_soc & 4:
                    # High charge/discharge current - Pre-alarm
                    self.protection.high_charge_current = 1
                else:
                    self.protection.high_charge_current = 0

                if al_crnt_soc & 128:
                    # Low SoC - Alarm
                    self.protection.low_soc = 2
                elif al_crnt_soc & 64:
                    # Low SoC Warning level - Pre-alarm
                    self.protection.low_soc = 1
                else:
                    self.protection.low_soc = 0

        self.hardware_version = "Daly CAN " + str(self.cell_count) + "S"

        # check if all needed data is available
        # sum of all data checks except for alarms
        logger.debug("Data check: %d" % (data_check))
        if data_check == 0:
            logger.error(">>> ERROR: No reply - returning")
            return False

        return True

        # TODO handle errors?
        """
        can_filters = [
            {"can_id": self.response_base, "can_mask": 0xFFFFFFF},
            {"can_id": self.response_soc, "can_mask": 0xFFFFFFF},
            {"can_id": self.response_minmax_cell_volts, "can_mask": 0xFFFFFFF},
            {"can_id": self.response_minmax_temp, "can_mask": 0xFFFFFFF},
            {"can_id": self.response_fet, "can_mask": 0xFFFFFFF},
            {"can_id": self.response_status, "can_mask": 0xFFFFFFF},
            {"can_id": self.response_cell_volts, "can_mask": 0xFFFFFFF},
            {"can_id": self.response_temp, "can_mask": 0xFFFFFFF},
            {"can_id": self.response_cell_balance, "can_mask": 0xFFFFFFF},
            {"can_id": self.response_alarm, "can_mask": 0xFFFFFFF},
        ]
        """
