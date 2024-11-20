# -*- coding: utf-8 -*-

# NOTES
# copied some lines from jkbms_can.py
# extended for JK Inverter BMS CAN from https://github.com/Hooorny/venus-os_dbus-serialbattery


from __future__ import absolute_import, division, print_function, unicode_literals
from battery import Battery, Cell
from utils import (
    logger,
    JKBMS_CAN_CELL_COUNT,
)
from struct import unpack_from
import can
import sys
import time


class Jkbms_Pb_Can(Battery):
    def __init__(self, port, baud, address):
        super(Jkbms_Pb_Can, self).__init__(port, baud, address)
        self.can_bus = False
        self.cell_count = 1
        self.poll_interval = 1500
        self.type = self.BATTERYTYPE

        # If multiple BMS are used simultaneously, the device address can be set via the Jikong BMS APP
        # (default address is 0) to change the CAN frame ID sent by the BMS
        # currently pinned to 0 and allow 1 BMS with default address
        self.device_address = int.from_bytes(address, byteorder="big") if address is not None else 0
        self.last_error_time = time.time()
        self.error_active = False

    def __del__(self):
        if self.can_bus:
            self.can_bus.shutdown()
            self.can_bus = False
            logger.debug("bus shutdown")

    BATTERYTYPE = "JKBMS PB CAN"
    CAN_BUS_TYPE = "socketcan"

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

    MESSAGES_TO_READ = 100

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
        return "CAN " + self.port + " Device ID " + str(self.device_id)

    def unique_identifier(self) -> str:
        """
        Used to identify a BMS when multiple BMS are connected
        Provide a unique identifier from the BMS to identify a BMS, if multiple same BMS are connected
        e.g. the serial number
        If there is no such value, please remove this function
        """
        return "JK Inverter BMS " + self.port + " addr " + str(self.device_id)

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

        self.hardware_version = "JKBMS PB CAN " + str(self.cell_count) + "S"
        return True

    def refresh_data(self):
        # call all functions that will refresh the battery data.
        # This will be called for every iteration (1 second)
        # Return True if success, False for failure
        return self.read_status_data()

    def read_status_data(self):
        status_data = self.read_jkbms_can()
        # check if connection success
        if status_data is False:
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

    def read_jkbms_can(self):
        if self.can_bus is False:
            logger.debug("Can bus init")
            # init the can interface
            try:
                self.can_bus = can.interface.Bus(bustype=self.CAN_BUS_TYPE, channel=self.port, bitrate=self.baud_rate)
            except can.CanError as e:
                logger.error(e)

            if self.can_bus is None:
                return False

            logger.debug("Can bus init done")

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
                normalized_arbitration_id = msg.arbitration_id - self.device_address
                if normalized_arbitration_id in self.CAN_FRAMES[self.BATT_STAT]:
                    voltage = unpack_from("<H", bytes([msg.data[0], msg.data[1]]))[0]
                    self.voltage = voltage / 10

                    current = unpack_from("<H", bytes([msg.data[2], msg.data[3]]))[0]
                    self.current = (current / 10) - 400

                    self.soc = unpack_from("<B", bytes([msg.data[4]]))[0]

                elif normalized_arbitration_id in self.CAN_FRAMES[self.ALM_INFO]:
                    alarms = unpack_from(
                        "<L",
                        bytes([msg.data[0], msg.data[1], msg.data[2], msg.data[3]]),
                    )[0]
                    print("alarms %d" % (alarms))
                    self.last_error_time = time.time()
                    self.error_active = True
                    self.to_protection_bits(alarms)

                elif normalized_arbitration_id in self.CAN_FRAMES[self.BATT_STAT_EXT]:
                    self.capacity_remain = unpack_from("<H", bytes([msg.data[0], msg.data[1]]))[0] / 10
                    self.capacity = unpack_from("<H", bytes([msg.data[2], msg.data[3]]))[0] / 10
                    self.history.total_ah_drawn = unpack_from("<H", bytes([msg.data[4], msg.data[5]]))[0] / 10
                    self.history.charge_cycles = unpack_from("<H", bytes([msg.data[6], msg.data[7]]))[0]

                elif normalized_arbitration_id in self.CAN_FRAMES[self.ALL_TEMP]:
                    # temp_sensor_cnt = unpack_from("<B", bytes([msg.data[0]]))[0]
                    temp1 = unpack_from("<B", bytes([msg.data[1]]))[0] - 50
                    temp2 = unpack_from("<B", bytes([msg.data[2]]))[0] - 50
                    temp_mosfet = unpack_from("<B", bytes([msg.data[3]]))[0] - 50
                    temp4 = unpack_from("<B", bytes([msg.data[4]]))[0] - 50
                    temp5 = unpack_from("<B", bytes([msg.data[5]]))[0] - 50
                    # temp3 equals mosfet temp
                    self.to_temp(0, temp_mosfet)
                    self.to_temp(1, temp1)
                    self.to_temp(2, temp2)
                    self.to_temp(3, temp4)
                    self.to_temp(4, temp5)

                # elif normalized_arbitration_id in self.CAN_FRAMES[self.BMSERR_INFO]:

                # elif normalized_arbitration_id in self.CAN_FRAMES[self.BMS_INFO]:

                elif normalized_arbitration_id in self.CAN_FRAMES[self.BMS_SWITCH_STATE]:
                    switch_state_bytes = unpack_from("<B", bytes([msg.data[0]]))[0]
                    # logger.info(switch_state_bytes)
                    self.charge_fet = bool((switch_state_bytes >> 0) & 0x01)
                    self.discharge_fet = bool((switch_state_bytes >> 1) & 0x01)
                    # set balance status, if only a common balance status is available (bool)
                    # not needed, if balance status is available for each cell
                    self.balancing = bool((switch_state_bytes >> 2) & 0x01)
                    if self.get_min_cell() is not None and self.get_max_cell() is not None:
                        for c in range(self.cell_count):
                            if self.balancing and (self.get_min_cell() == c or self.get_max_cell() == c):
                                self.cells[c].balance = True
                            else:
                                self.cells[c].balance = False

                elif normalized_arbitration_id in self.CAN_FRAMES[self.CELL_VOLT_EXT1]:
                    self.cells[0].voltage = unpack_from("<H", bytes([msg.data[0], msg.data[1]]))[0] / 1000
                    self.cells[1].voltage = unpack_from("<H", bytes([msg.data[2], msg.data[3]]))[0] / 1000
                    self.cells[2].voltage = unpack_from("<H", bytes([msg.data[4], msg.data[5]]))[0] / 1000
                    self.cells[3].voltage = unpack_from("<H", bytes([msg.data[6], msg.data[7]]))[0] / 1000

                elif normalized_arbitration_id in self.CAN_FRAMES[self.CELL_VOLT_EXT2]:
                    self.cells[4].voltage = unpack_from("<H", bytes([msg.data[0], msg.data[1]]))[0] / 1000
                    self.cells[5].voltage = unpack_from("<H", bytes([msg.data[2], msg.data[3]]))[0] / 1000
                    self.cells[6].voltage = unpack_from("<H", bytes([msg.data[4], msg.data[5]]))[0] / 1000
                    self.cells[7].voltage = unpack_from("<H", bytes([msg.data[6], msg.data[7]]))[0] / 1000

                elif normalized_arbitration_id in self.CAN_FRAMES[self.CELL_VOLT_EXT3]:
                    self.cells[8].voltage = unpack_from("<H", bytes([msg.data[0], msg.data[1]]))[0] / 1000
                    self.cells[9].voltage = unpack_from("<H", bytes([msg.data[2], msg.data[3]]))[0] / 1000
                    self.cells[10].voltage = unpack_from("<H", bytes([msg.data[4], msg.data[5]]))[0] / 1000
                    self.cells[11].voltage = unpack_from("<H", bytes([msg.data[6], msg.data[7]]))[0] / 1000

                elif normalized_arbitration_id in self.CAN_FRAMES[self.CELL_VOLT_EXT4]:
                    self.cells[12].voltage = unpack_from("<H", bytes([msg.data[0], msg.data[1]]))[0] / 1000
                    self.cells[13].voltage = unpack_from("<H", bytes([msg.data[2], msg.data[3]]))[0] / 1000
                    self.cells[14].voltage = unpack_from("<H", bytes([msg.data[4], msg.data[5]]))[0] / 1000
                    self.cells[15].voltage = unpack_from("<H", bytes([msg.data[6], msg.data[7]]))[0] / 1000

                elif normalized_arbitration_id in self.CAN_FRAMES[self.CELL_VOLT_EXT5]:
                    self.cells[16].voltage = unpack_from("<H", bytes([msg.data[0], msg.data[1]]))[0] / 1000
                    self.cells[17].voltage = unpack_from("<H", bytes([msg.data[2], msg.data[3]]))[0] / 1000
                    self.cells[18].voltage = unpack_from("<H", bytes([msg.data[4], msg.data[5]]))[0] / 1000
                    self.cells[19].voltage = unpack_from("<H", bytes([msg.data[6], msg.data[7]]))[0] / 1000

                elif normalized_arbitration_id in self.CAN_FRAMES[self.CELL_VOLT_EXT6]:
                    self.cells[20].voltage = unpack_from("<H", bytes([msg.data[0], msg.data[1]]))[0] / 1000
                    self.cells[21].voltage = unpack_from("<H", bytes([msg.data[2], msg.data[3]]))[0] / 1000
                    self.cells[22].voltage = unpack_from("<H", bytes([msg.data[4], msg.data[5]]))[0] / 1000
                    self.cells[23].voltage = unpack_from("<H", bytes([msg.data[6], msg.data[7]]))[0] / 1000

                # elif normalized_arbitration_id in self.CAN_FRAMES[self.BMS_CHG_INFO]:

        return True
