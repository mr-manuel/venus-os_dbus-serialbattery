# -*- coding: utf-8 -*-

# NOTES
# Added by https://github.com/gimx based on https://github.com/gimx/dbus_ubms

# TODO, also upstream
# - sum in cell voltage display is wrong (adding not only a string up)
#   and worse ignoring the correctly calculated one and setting CVL wrongly
# - cell balancing status
# - CAN masking for used ids only
# - VMU keep alive cyclic message on successful connect, otherwise the BMS disconnects battery


from __future__ import absolute_import, division, print_function, unicode_literals
from battery import Battery, Cell
from utils import bytearray_to_string, logger
from utils import (
    MAX_BATTERY_CHARGE_CURRENT,
    MAX_BATTERY_DISCHARGE_CURRENT,
    MAX_CELL_VOLTAGE,
    MIN_CELL_VOLTAGE,
    UBMS_CAN_MODULE_SERIES,
    UBMS_CAN_MODULE_PARALLEL,
)
from time import time
import sys
import can
import struct
import itertools


class Ubms_Can(Battery):
    def __init__(self, port, baud, address):
        super(Ubms_Can, self).__init__(port, baud, address)
        self.type = self.BATTERYTYPE
        # self.history.exclude_values_to_calculate = ["charge_cycles", "total_ah_drawn"]

        # If multiple BMS are used simultaneously, the device address can be set via the dip switches on the BMS
        # (default address is 0, all switches down) to change the CAN frame ID sent by the BMS
        self.device_address = int.from_bytes(address, byteorder="big") if address is not None else 0
        self.error_active = False
        self.protocol_version = None
        self.poll_interval = 100
        self.last_error_time = time()
        self.error_active = False

        self.numberOfModules = UBMS_CAN_MODULE_SERIES * UBMS_CAN_MODULE_PARALLEL
        self.numberOfStrings = UBMS_CAN_MODULE_PARALLEL
        self.modulesInSeries = int(self.numberOfModules / self.numberOfStrings)
        self.cellsPerModule = 4
        self.maxChargeVoltage = MAX_CELL_VOLTAGE * self.cellsPerModule * UBMS_CAN_MODULE_SERIES
        self.max_battery_voltage = self.maxChargeVoltage
        self.min_battery_voltage = MIN_CELL_VOLTAGE * self.cellsPerModule * UBMS_CAN_MODULE_SERIES

        self.cell_count = self.numberOfModules * self.cellsPerModule

        self.cells = [Cell(False) for _ in range(self.cell_count)]

        self.chargeComplete = 0
        self.soc = 0
        self.mode = 0
        self.state = ""
        self.voltage = 0
        self.current = 0
        self.temperature = 0
        self.balanced = True
        self.voltageAndCellTAlarms = 0
        self.internalErrors = 0
        self.currentAndPcbTAlarms = 0
        self.maxPcbTemperature = 0
        self.maxCellTemperature = 0
        self.minCellTemperature = 0

        self.cellVoltages = [(0, 0, 0, 0) for i in range(self.numberOfModules)]
        self.moduleVoltage = [0 for i in range(self.numberOfModules)]
        self.moduleCurrent = [0 for i in range(self.numberOfModules)]
        self.moduleSoc = [0 for i in range(self.numberOfModules)]
        self.maxCellVoltage = 3.2
        self.minCellVoltage = 3.2
        self.maxChargeCurrent = MAX_BATTERY_CHARGE_CURRENT
        self.maxDischargeCurrent = MAX_BATTERY_DISCHARGE_CURRENT
        self.partnr = 0
        self.firmwareVersion = "unknown"
        self.numberOfModulesBalancing = 0
        self.numberOfModulesCommunicating = 0
        self.cyclicModeTask = None

    BATTERYTYPE = "UBMS CAN"

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

        found = 0

        for frame_id, data in self.can_transport_interface.can_message_cache_callback().items():
            msg = can.Message(arbitration_id=frame_id, data=data, is_extended_id=True)

            if msg.arbitration_id == 0x180:
                self.firmwareVersion = msg.data[0]
                # self.bms_type = msg.data[3]
                logger.info("Found Valence U-BMS type %i with FW v%i.", msg.data[3], msg.data[0])
                if self.hardware_version is None:
                    self.hardware_version = str(msg.data[4])

                found = found | 1

            elif msg.arbitration_id == 0xC0:
                # status message received
                logger.info("U-BMS is in mode %x with %i modules communicating.", msg.data[1], msg.data[5])
                if msg.data[2] & 1 != 0:
                    logger.info("The number of modules communicating is less than configured.")
                if msg.data[3] & 2 != 0:
                    logger.info("The number of modules communicating is higher than configured.")

                found = found | 2

            elif msg.arbitration_id == 0xC1:
                # check pack voltage
                if abs(2 * msg.data[0] - self.maxChargeVoltage) > 0.15 * self.maxChargeVoltage:
                    logger.error("U-BMS pack voltage of %dV differs significantly from configured max charge voltage %dV.", msg.data[0], self.maxChargeVoltage)
                found = found | 4

        if found >= 3:
            return True
        else:
            return False

    def refresh_data(self):
        # call all functions that will refresh the battery data.
        # This will be called for every iteration (1 second)
        # Return True if success, False for failure
        result = False

        # decode all queued CAN messages
        result = self.decode_can()

        if result is True:
            # convert to alarms to protection bits
            self.to_protection_bits()

            self.update_cell_voltages()

        return result

    def to_protection_bits(self):
        self.protection.low_cell_voltage = (self.voltageAndCellTAlarms & 0x10) >> 3
        self.protection.high_cell_voltage = (self.voltageAndCellTAlarms & 0x20) >> 4
        self.protection.low_soc = (self.voltageAndCellTAlarms & 0x08) >> 3
        self.protection.high_discharge_current = self.currentAndPcbTAlarms & 0x3

        # flag high cell temperature alarm and high pcb temperature alarm
        self.protection.high_temperature = (self.voltageAndCellTAlarms & 0x6) >> 1 | (self.currentAndPcbTAlarms & 0x18) >> 3
        self.protection.low_temperature = (self.mode & 0x60) >> 5

        # FIXME check if any alarms came up

    # logger.debug("alarms %d" % (alarms))
    # self.last_error_time = time()
    # self.error_active = True

    def reset_protection_bits(self):
        self.protection.high_cell_voltage = 0
        self.protection.low_cell_voltage = 0
        self.protection.high_voltage = 0
        self.protection.low_voltage = 0
        self.protection.cell_imbalance = 0
        self.protection.high_discharge_current = 0
        self.protection.high_charge_current = 0

        # there is just a BMS and Battery temperature_ alarm (not for charge and discharge)
        self.protection.high_charge_temperature = 0
        self.protection.high_temperature = 0
        self.protection.low_charge_temperature = 0
        self.protection.low_temperature = 0
        self.protection.high_charge_temperature = 0
        self.protection.high_temperature = 0
        self.protection.low_soc = 0
        self.protection.internal_failure = 0

    def update_cell_voltages(self):
        chain = itertools.chain(*self.cellVoltages)
        flatVList = list(chain)
        for i in range(self.cell_count):
            self.cells[i].voltage = flatVList[i] / 1000.0

    def decode_can(self):

        for frame_id, data in self.can_transport_interface.can_message_cache_callback().items():
            msg = can.Message(arbitration_id=frame_id, data=data, is_extended_id=True)

            if msg.arbitration_id == 0xC0:
                self.soc = msg.data[0]
                self.mode = msg.data[1]
                self.balancing = True if (self.mode & 0x10) != 0 else False
                self.voltageAndCellTAlarms = msg.data[2]
                self.internalErrors = msg.data[3]
                self.currentAndPcbTAlarms = msg.data[4]

                self.numberOfModulesCommunicating = msg.data[5]

                # if no module flagged missing and not too many on the bus, then this is the number the U-BMS was configured for
                if (msg.data[2] & 1 == 0) and (msg.data[3] & 2 == 0):
                    self.numberOfModules = self.numberOfModulesCommunicating

                self.numberOfModulesBalancing = msg.data[6]

            elif msg.arbitration_id == 0xC1:
                # self.voltage = msg.data[0] * 1 # voltage scale factor depends on BMS configuration, so unusable
                self.current = struct.unpack("Bb", msg.data[0:2])[1]

                if (self.mode & 0x2) != 0:  # provided in drive mode only
                    self.maxDischargeCurrent = int((struct.unpack("<h", msg.data[3:5])[0]) / 10)
                    self.maxChargeCurrent = int((struct.unpack("<h", bytearray([msg.data[5], msg.data[7]]))[0]) / 5)

            elif msg.arbitration_id == 0xC2:
                # data valid in charge mode only
                if (self.mode & 0x1) != 0:
                    self.chargeComplete = (msg.data[3] & 0x4) >> 2
                    self.maxChargeVoltage2 = struct.unpack("<h", msg.data[1:3])[0]

                    # only apply lower charge current when equalizing
                    if (self.mode & 0x18) == 0x18:
                        self.maxChargeCurrent = msg.data[0]
                    else:
                        # allow charge with 0.1C
                        self.maxChargeCurrent = self.capacity * 0.1

            elif msg.arbitration_id == 0xC4:
                self.maxCellTemperature = msg.data[0] - 40
                self.minCellTemperature = msg.data[1] - 40
                self.maxPcbTemperature = msg.data[3] - 40
                self.maxCellVoltage = struct.unpack("<h", msg.data[4:6])[0] * 0.001
                self.minCellVoltage = struct.unpack("<h", msg.data[6:8])[0] * 0.001
                self.cell_max_voltage = self.maxCellVoltage
                self.cell_min_voltage = self.minCellVoltage

            # FIXME Intra-module balance flags, 1 bit per cell, 1 byte per module
            # elif msg.arbitration_id in [0x26A, 0x26B]:
            #     for m in range [(msg.arbitration_id-0x2A) * 8, ((msg.arbitration_id-0x2A + 1) * 8) -1]:
            #         self.cells[m * self.cellsPerModule + 0].balance = True if ((msg.data[m]>>c) & 1) != 0 else False
            #         self.cells[m * self.cellsPerModule + 1].balance = True if ((msg.data[m]>>1) & 1) != 0 else False
            #         self.cells[m * self.cellsPerModule + 2].balance = True if ((msg.data[m]>>2) & 1) != 0 else False
            #         self.cells[m * self.cellsPerModule + 3].balance = True if ((msg.data[m]>>3) & 1) != 0 else False

            elif msg.arbitration_id in [0x350, 0x352, 0x354, 0x356, 0x358, 0x35A, 0x35C, 0x35E, 0x360, 0x362, 0x364]:
                module = (msg.arbitration_id - 0x350) >> 1
                self.cellVoltages[module] = struct.unpack(">hhh", msg.data[2 : msg.dlc])

            elif msg.arbitration_id in [0x351, 0x353, 0x355, 0x357, 0x359, 0x35B, 0x35D, 0x35F, 0x361, 0x363, 0x365]:
                module = (msg.arbitration_id - 0x351) >> 1
                self.cellVoltages[module] = self.cellVoltages[module] + tuple(struct.unpack(">h", msg.data[2 : msg.dlc]))
                self.moduleVoltage[module] = sum(self.cellVoltages[module])

                # update pack voltage at each arrival of the first strings last modules cell voltages
                if module == self.numberOfModules - 1:
                    self.voltage = sum(self.moduleVoltage[0 : self.modulesInSeries]) / 1000.0

        return True
