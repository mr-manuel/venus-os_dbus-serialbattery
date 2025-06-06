# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals
from battery import Protection, Battery, Cell
from utils import (
    get_connection_error_message,
    logger,
    GREENMETER_ADDRESS,
    LIPRO_CELL_COUNT,
    LIPRO_END_ADDRESS,
    LIPRO_START_ADDRESS,
)
import ext.minimalmodbus as minimalmodbus
import sys


class Ecs(Battery):
    def __init__(self, port, baud, address):
        super(Ecs, self).__init__(port, baud, address)
        self.type = self.BATTERYTYPE

    BATTERYTYPE = "ECS LiPro"
    GREENMETER_ID_500A = 500
    GREENMETER_ID_250A = 501
    GREENMETER_ID_125A = 502
    METER_SIZE = ""
    # LiPro 100, 101 is untested but should work if they have updated firmware
    # that match the registers of the newer models
    LIPRO1X_ID_V1 = 100
    LIPRO1X_ID_ACTIVE = 101
    # ---
    LIPRO1X_ID_V2 = 102
    LIPRO1X_ID_ACTIVE_V2 = 103
    LIPRO1X_ID_V3 = 104
    LiProCells = []

    def test_connection(self):
        """
        call a function that will connect to the battery, send a command and retrieve the result.
        The result or call should be unique to this BMS. Battery name or version, etc.
        Return True if success, False for failure
        """
        # Trying to find Green Meter ID
        result = False
        try:
            mbdev = minimalmodbus.Instrument(self.port, GREENMETER_ADDRESS)
            mbdev.serial.parity = minimalmodbus.serial.PARITY_EVEN
            tmpId = mbdev.read_register(0, 0)
            if tmpId in range(self.GREENMETER_ID_500A, self.GREENMETER_ID_125A + 1):
                if tmpId == self.GREENMETER_ID_500A:
                    self.METER_SIZE = "500A"
                if tmpId == self.GREENMETER_ID_250A:
                    self.METER_SIZE = "250A"
                if tmpId == self.GREENMETER_ID_125A:
                    self.METER_SIZE = "125A"

                # TODO
                # has this to be true?
                # if yes then self.get_settings() should only be called, if this is true
                self.find_LiPro_cells()

                result = self.get_settings()

                # get first data to show in startup log, only if result is true
                result = result and self.refresh_data()

        except IOError:
            result = False
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

        # give the user a feedback that no BMS was found
        if not result:
            get_connection_error_message(self.online)

        return result

    def find_LiPro_cells(self):
        # test for LiPro cell devices
        for cell_address in range(LIPRO_START_ADDRESS, LIPRO_END_ADDRESS + 1):
            try:
                mbdev = minimalmodbus.Instrument(self.port, cell_address)
                mbdev.serial.parity = minimalmodbus.serial.PARITY_EVEN

                tmpId = mbdev.read_register(0, 0)
                if tmpId in range(self.LIPRO1X_ID_V1, self.LIPRO1X_ID_V3 + 1):
                    self.LiProCells.append(cell_address)
                    logger.info("Found LiPro at " + str(cell_address))
                    self.cells.append(Cell(False))

            except IOError:
                pass

        return True if len(self.LiProCells) > 0 else False

    def get_settings(self):
        # After successful connection get_settings() will be called to set up the battery
        # Set the current limits, populate cell count, etc
        # Return True if success, False for failure

        # Uncomment if BMS does not supply capacity
        self.cell_count = LIPRO_CELL_COUNT
        # temperature_sensors = 2

        return self.read_status_data()

    def refresh_data(self):
        # call all functions that will refresh the battery data.
        # This will be called for every iteration (1 second)
        # Return True if success, False for failure
        result = self.read_soc_data()
        result = result and self.read_cell_data()

        return result

    def read_status_data(self):
        try:
            mbdev = minimalmodbus.Instrument(self.port, GREENMETER_ADDRESS)
            mbdev.serial.parity = minimalmodbus.serial.PARITY_EVEN

            self.max_battery_discharge_current = abs(mbdev.read_register(30, 0, 3, True))
            self.max_battery_charge_current = mbdev.read_register(31, 0, 3, True)
            self.capacity = mbdev.read_long(46, 3, False, minimalmodbus.BYTEORDER_LITTLE_SWAP) / 1000
            self.production = mbdev.read_long(2, 3, False, minimalmodbus.BYTEORDER_LITTLE_SWAP)

            self.hardware_version = "Greenmeter-" + self.METER_SIZE + " " + str(self.cell_count) + "S"
            logger.info(self.hardware_version)

            return True
        except IOError:
            return False

    def read_soc_data(self):
        try:
            mbdev = minimalmodbus.Instrument(self.port, GREENMETER_ADDRESS)
            mbdev.serial.parity = minimalmodbus.serial.PARITY_EVEN

            self.voltage = mbdev.read_long(108, 3, True, minimalmodbus.BYTEORDER_LITTLE_SWAP) / 1000
            self.current = mbdev.read_long(114, 3, True, minimalmodbus.BYTEORDER_LITTLE_SWAP) / 1000
            # if (mbdev.read_register(129, 0, 3, False) != 65535):
            temp_soc = mbdev.read_long(128, 3, True, minimalmodbus.BYTEORDER_LITTLE_SWAP)
            # Fix for Greenmeter that seems to not correctly define/set the high bytes
            # if the SOC value is less than 65535 (65.535%). So 50% comes through as #C350 FFFF instead of #C350 0000
            self.soc = (temp_soc if temp_soc < 4294901760 else temp_soc - 4294901760) / 1000

            self.protection = Protection()

            over_voltage = mbdev.read_register(130, 0, 3, True)
            under_voltage = mbdev.read_register(131, 0, 3, True)
            self.charge_fet = True if over_voltage == 0 else False
            self.discharge_fet = True if under_voltage == 0 else False
            self.protection.high_voltage = 2 if over_voltage == 1 else 0
            self.protection.low_voltage = 2 if under_voltage == 1 else 0
            self.protection.high_charge_temperature = 1 if over_voltage in range(3, 5) else 0
            self.protection.low_charge_temperature = 1 if over_voltage in range(5, 7) else 0
            self.protection.high_temperature = 1 if under_voltage in range(3, 5) else 0
            self.protection.low_temperature = 1 if under_voltage in range(5, 7) else 0
            self.protection.high_charge_current = 1 if over_voltage == 2 else 0
            self.protection.high_discharge_current = 1 if under_voltage == 2 else 0

            self.temperature_1 = mbdev.read_register(102, 0, 3, True) / 100
            self.temperature_2 = mbdev.read_register(103, 0, 3, True) / 100

            return True
        except IOError:
            return False

    def read_cell_data(self):
        for cell in range(len(self.LiProCells)):
            try:
                mbdev = minimalmodbus.Instrument(self.port, self.LiProCells[cell])
                mbdev.serial.parity = minimalmodbus.serial.PARITY_EVEN

                self.cells[cell].voltage = mbdev.read_register(100, 0, 3, False) / 1000
                self.cells[cell].balance = True if mbdev.read_register(102, 0, 3, False) > 50 else False
                self.cells[cell].temperature = mbdev.read_register(101, 0, 3, True) / 100

                return True
            except IOError:
                pass
