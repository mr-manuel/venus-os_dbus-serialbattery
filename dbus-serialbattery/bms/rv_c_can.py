# -*- coding: utf-8 -*-

# NOTES
# Added by https://github.com/IrisCrimson


from __future__ import absolute_import, division, print_function, unicode_literals
from battery import Battery, Cell
from utils import (
    is_bit_set,
    logger,
    ZERO_CHAR,
)
from struct import unpack_from
import can
import sys
import time

class RV_C_Can(Battery):
    def __init__(self, port, baud, address):
        super(RV_C_Can, self).__init__(port, baud, address)
        self.can_bus = False
        self.cell_count = 4
        self.poll_interval = 1500
        self.type = "RV-C"
        self.last_error_time = time.time()
        self.error_active = False

    def __del__(self):
        if self.can_bus:
            self.can_bus.shutdown()
            self.can_bus = False
            logger.debug("bus shutdown")

    BATTERYTYPE = "RV-C"
    CAN_BUS_TYPE = "socketcan"

    CURRENT_ZERO_CONSTANT = 400
    BATT_STAT = "BATT_STAT"
    BATT_STAT2 = "BATT_STAT2"

    MESSAGES_TO_READ = 100

    # B2A... Black is using 0x0XF4
    # B2A... Silver is using 0x0XF5
    # See https://github.com/Louisvdw/dbus-serialbattery/issues/950
    CAN_FRAMES = {
        BATT_STAT: [0x19FFFD8F],
        BATT_STAT2: [0x19FFFC8F],
    }

    def connection_name(self) -> str:
        return "CAN " + self.port

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
        self.cell_count = 4
        self.max_battery_charge_current = 100
        # self.max_battery_voltage =  14.6
        self.control_charge_current = 100
        self.control_discharge_current = 100
        self.control_allow_discharge = True
        self.control_allow_charge = True
        self.max_battery_discharge_current = 100
        #self.min_cell_voltage = 12.1
        #self.max_cell_voltage = 14.6
        self.capacity = 400
        self.charge_fet = 1
        self.discharge_fet = 1
        VolSOC_full = 100
        VolSOC_empty = 5
        # init the cell array add only missing Cell instances
        missing_instances = self.cell_count - len(self.cells)
        if missing_instances > 0:
            for c in range(missing_instances):
                self.cells.append(Cell(False))

        self.hardware_version = "RV-C CAN " + str(self.cell_count) + "S"
        return True

    def refresh_data(self):
        # call all functions that will refresh the battery data.
        # This will be called for every iteration (1 second)
        # Return True if success, False for failure
        return self.read_status_data()

    def read_status_data(self):
        status_data = self.read_serial_data_rv_c_CAN()
        # check if connection success
        if status_data is False:
            return False

        return True

    def to_fet_bits(self, byte_data):
        tmp = bin(byte_data)[2:].rjust(2, ZERO_CHAR)
        # self.charge_fet = is_bit_set(tmp[1])
        # self.discharge_fet = is_bit_set(tmp[0])


    def read_serial_data_rv_c_CAN(self):
        if self.can_bus is False:
            logger.debug("Can bus init")
            # intit the can interface
            try:
                self.can_bus = can.interface.Bus(bustype=self.CAN_BUS_TYPE, channel=self.port)
                logger.debug(f"bustype: {self.CAN_BUS_TYPE}, channel: {self.port}, bitrate: {self.baud_rate}")
            except can.CanError as e:
                logger.error(e)

            if self.can_bus is None:
                logger.error("Can bus init failed")
                return False

            logger.debug("Can bus init done")

        try:

            # reset errors after timeout
            if ((time.time() - self.last_error_time) > 120.0) and self.error_active is True:
                self.error_active = False
                self.reset_protection_bits()

            # read msgs until we get one we want
            messages_to_read = self.MESSAGES_TO_READ
            while messages_to_read > 0:
                msg = self.can_bus.recv(1)
                if msg is None:
                    logger.info("No CAN Message received")
                    return False

                if msg is not None:
                    # print("message received")
                    messages_to_read -= 1
                    # print(messages_to_read)
                    if msg.arbitration_id in self.CAN_FRAMES[self.BATT_STAT]:
                        voltage = unpack_from("<H", bytes([msg.data[2], msg.data[3]]))[0]
                        self.voltage = voltage / 20
                        self.cells[0].voltage  = (voltage / 20) / 4
                        self.cells[1].voltage  = (voltage / 20)	/ 4
                        self.cells[2].voltage  = (voltage / 20)	/ 4
                        self.cells[3].voltage  = (voltage / 20)	/ 4
                        current = unpack_from("<L", bytes([msg.data[4], msg.data[5],msg.data[6], msg.data[7] ]))[0]
                        self.current = (2000000000 - current) / 1000
                        # logger.debug("Current: %d" % (current))
                        # print(self.voltage)
                        # print(self.current)

                    elif msg.arbitration_id in self.CAN_FRAMES[self.BATT_STAT2]:
                        soc = unpack_from("<B", bytes([msg.data[4]]))[0]
                        self.soc = soc / 2
                        temperature_1 = unpack_from("<H", bytes([msg.data[2], msg.data[3]]))[0]
                        temp = (temperature_1 * .03125) - 273
                        self.to_temperature(1, temp)
                        # print(self.soc)
                        # print(self.time_to_go)


            return True

        except Exception:
            (
                exception_type,
                exception_object,
                exception_traceback,
            ) = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
            return False