# -*- coding: utf-8 -*-

# NOTES
# Added by https://github.com/IrisCrimson


from __future__ import absolute_import, division, print_function, unicode_literals
from battery import Battery, Cell
from utils import (
    is_bit_set,
    logger,
    JKBMS_CAN_CELL_COUNT,
    ZERO_CHAR,
)
from struct import unpack_from
import can
import sys
import time


class Jkbms_Can(Battery):
    def __init__(self, port, baud, address):
        super(Jkbms_Can, self).__init__(port, baud, address)
        self.can_bus = False
        self.cell_count = 1
        self.poll_interval = 1500
        self.type = self.BATTERYTYPE
        self.last_error_time = time.time()
        self.error_active = False

    def __del__(self):
        if self.can_bus:
            self.can_bus.shutdown()
            self.can_bus = False
            logger.debug("bus shutdown")

    BATTERYTYPE = "JKBMS CAN"
    CAN_BUS_TYPE = "socketcan"

    CURRENT_ZERO_CONSTANT = 400
    BATT_STAT = "BATT_STAT"
    CELL_VOLT = "CELL_VOLT"
    CELL_TEMP = "CELL_TEMP"
    ALM_INFO = "ALM_INFO"

    MESSAGES_TO_READ = 100

    # B2A... Black is using 0x0XF4
    # B2A... Silver is using 0x0XF5
    # See https://github.com/Louisvdw/dbus-serialbattery/issues/950
    CAN_FRAMES = {
        BATT_STAT: [0x02F4, 0x02F5, 0x02F9],
        CELL_VOLT: [0x04F4, 0x04F5, 0x04F9],
        CELL_TEMP: [0x05F4, 0x05F5, 0x05F9],
        ALM_INFO: [0x07F4, 0x07F5, 0x07F9],
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
        self.cell_count = JKBMS_CAN_CELL_COUNT

        # init the cell array add only missing Cell instances
        missing_instances = self.cell_count - len(self.cells)
        if missing_instances > 0:
            for c in range(missing_instances):
                self.cells.append(Cell(False))

        self.hardware_version = "JKBMS CAN " + str(self.cell_count) + "S"
        return True

    def refresh_data(self):
        # call all functions that will refresh the battery data.
        # This will be called for every iteration (1 second)
        # Return True if success, False for failure
        return self.read_status_data()

    def read_status_data(self):
        status_data = self.read_serial_data_jkbms_CAN()
        # check if connection success
        if status_data is False:
            return False

        return True

    def to_fet_bits(self, byte_data):
        tmp = bin(byte_data)[2:].rjust(2, ZERO_CHAR)
        self.charge_fet = is_bit_set(tmp[1])
        self.discharge_fet = is_bit_set(tmp[0])

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

        # there is just a BMS and Battery temp alarm (not for charg and discharge)
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

        # there is just a BMS and Battery temp alarm (not for charg and discharge)
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

    def read_serial_data_jkbms_CAN(self):
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
                        voltage = unpack_from("<H", bytes([msg.data[0], msg.data[1]]))[0]
                        self.voltage = voltage / 10

                        current = unpack_from("<H", bytes([msg.data[2], msg.data[3]]))[0]
                        self.current = (current / 10) - 400

                        self.soc = unpack_from("<B", bytes([msg.data[4]]))[0]

                        self.time_to_go = unpack_from("<H", bytes([msg.data[6], msg.data[7]]))[0] * 36

                        # print(self.voltage)
                        # print(self.current)
                        # print(self.soc)
                        # print(self.time_to_go)

                    elif msg.arbitration_id in self.CAN_FRAMES[self.CELL_VOLT]:
                        max_cell_volt = unpack_from("<H", bytes([msg.data[0], msg.data[1]]))[0] / 1000
                        max_cell_nr = unpack_from("<B", bytes([msg.data[2]]))[0]
                        max_cell_cnt = max(max_cell_nr, self.cell_count)

                        min_cell_volt = unpack_from("<H", bytes([msg.data[3], msg.data[4]]))[0] / 1000
                        min_cell_nr = unpack_from("<B", bytes([msg.data[5]]))[0]
                        max_cell_cnt = max(min_cell_nr, max_cell_cnt)

                        if max_cell_cnt > self.cell_count:
                            self.cell_count = max_cell_cnt
                            self.get_settings()

                        for c_nr in range(len(self.cells)):
                            self.cells[c_nr].balance = False

                        if self.cell_count == len(self.cells):
                            self.cells[max_cell_nr - 1].voltage = max_cell_volt
                            self.cells[max_cell_nr - 1].balance = True

                            self.cells[min_cell_nr - 1].voltage = min_cell_volt
                            self.cells[min_cell_nr - 1].balance = True

                    elif msg.arbitration_id in self.CAN_FRAMES[self.CELL_TEMP]:
                        max_temp = unpack_from("<B", bytes([msg.data[0]]))[0] - 50
                        # max_nr = unpack_from("<B", bytes([msg.data[1]]))[0]
                        min_temp = unpack_from("<B", bytes([msg.data[2]]))[0] - 50
                        # min_nr = unpack_from("<B", bytes([msg.data[3]]))[0]
                        self.to_temp(1, max_temp if max_temp <= 100 else 100)
                        self.to_temp(2, min_temp if min_temp <= 100 else 100)
                        # print(max_temp)
                        # print(min_temp)
                    elif msg.arbitration_id in self.CAN_FRAMES[self.ALM_INFO]:
                        alarms = unpack_from(
                            "<L",
                            bytes([msg.data[0], msg.data[1], msg.data[2], msg.data[3]]),
                        )[0]
                        print("alarms %d" % (alarms))
                        self.last_error_time = time.time()
                        self.error_active = True
                        self.to_protection_bits(alarms)
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
