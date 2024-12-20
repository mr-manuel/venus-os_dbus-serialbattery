# -*- coding: utf-8 -*-

# NOTES
# Added by https://github.com/versager
# https://github.com/mr-manuel/venus-os_dbus-serialbattery/pull/116

from battery import Battery, Cell, Protection
from utils import read_serial_data, unpack_from, logger
import utils
from struct import unpack
import struct
import sys


class Felicity(Battery):
    def __init__(self, port, baud, address):
        super(Felicity, self).__init__(port, baud, address)
        self.type = self.BATTERYTYPE

        # should be 0x01
        self.command_address = address

    BATTERYTYPE = "Felicity"
    LENGTH_CHECK = 4
    LENGTH_POS = 2

    # command bytes [Address field][Function code (03 = Read register)]
    #                   [Register Address (2 bytes)][Data Length (2 bytes)][CRC (2 bytes little endian)]

    command_read = b"\x03"
    command_cell_voltages = b"\x13\x2a\x00\x10"  # Registers 4906
    command_bms_temperature_1_3 = b"\x13\x39\x00\x05"  # Register  4929-4931 (tempsensor1-3)

    command_dvcc = b"\x13\x1C\x00\x04"  # Registers  4892(charger and discharger informations)
    command_status = b"\x13\x02\x00\x03"  # Registers 4866(battery status and fault informations)

    command_total_voltage_current = b"\x13\x06\x00\x02"  # Register 4870-4871
    command_bms_temperature_1 = b"\x13\x0A\x00\x01"  # Register  4874 (bms_temp)
    command_soc = b"\x13\x0B\x00\x01"  # Registers 4875(soc)
    command_firmware_version = b"\xF8\x0B\x00\x01"  # Registers 63499 (1 byte string)
    command_serialnumber = b"\xF8\x04\x00\x05"  # Registers 63492 (1 byte string)

    # BMS warning and protection config

    def unique_identifier(self) -> str:
        return self.serial_number

    def test_connection(self):
        # call a function that will connect to the battery, send a command and retrieve the result.
        # The result or call should be unique to this BMS. Battery name or version, etc.
        # Return True if success, False for failure
        result = False
        try:
            result = self.read_gen_data()
            result = result and self.get_settings()
            # get first data to show in startup log
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
        # After successful  connection get_settings will be call to set up the battery.
        # Set the current limits, populate cell count, etc
        # Return True if success, False for failure

        self.capacity = utils.BATTERY_CAPACITY if not None else 0.0

        return True

    def refresh_data(self):
        # call all functions that will refresh the battery data.
        # This will be called for every iteration (1 second)
        # Return True if success, False for failure
        result = self.read_soc_data()
        result = result and self.read_cell_data()
        result = result and self.read_temperature_data()

        return result

    def read_gen_data(self):

        firmware = self.read_serial_data_felicity(self.command_firmware_version)

        if firmware is False:
            return False

        self.version = str(unpack(">h", firmware)[0])
        logger.debug(">>> INFO: Battery Firmware: %s", self.version)

        serialnumber = self.read_serial_data_felicity(self.command_serialnumber)

        if serialnumber is False:
            return False

        if len(serialnumber) != 10:
            logger.error(">>> INFO: serialnumber Data size are wrong: %s", len(serialnumber))
            return False

        s1 = str(unpack_from(">H", serialnumber, 0 * 2)[0])
        s2 = str(unpack_from(">H", serialnumber, 1 * 2)[0])
        s3 = str(unpack_from(">H", serialnumber, 2 * 2)[0])
        s4 = str(unpack_from(">H", serialnumber, 3 * 2)[0])
        s5 = str(unpack_from(">H", serialnumber, 4 * 2)[0])
        self.serial_number = s1 + s2 + s3 + s4 + s5
        logger.debug(">>> INFO: Battery Serialnumber: %s", self.serial_number)

        self.cell_count = 16
        for c in range(self.cell_count):
            self.cells.append(Cell(False))

        # temperature_sensors = 4

        return True

    def read_soc_data(self):

        soc_data = self.read_serial_data_felicity(self.command_soc)
        if soc_data is False:
            return False

        if len(soc_data) != 2:
            logger.error(">>> INFO: soc Data size are wrong: %s", len(soc_data))
        else:
            self.soc = unpack_from(">H", soc_data)[0]
            logger.debug(">>> INFO: Battery SoC: %s", self.soc)

        voltage_current_data = self.read_serial_data_felicity(self.command_total_voltage_current)
        if voltage_current_data is False:
            return False

        if len(voltage_current_data) != 4:
            logger.error(">>> INFO: voltage_current Data size are wrong: %s", len(voltage_current_data))
        else:
            self.voltage = unpack_from(">H", voltage_current_data)[0] / 100
            logger.debug(">>> INFO: Battery voltage: %f V", self.voltage)

            self.current = unpack_from(">h", voltage_current_data, 2)[0] / 10 * -1
            logger.debug(">>> INFO: Battery current: %f A", self.current)

        if utils.USE_BMS_DVCC_VALUES is True:
            dvcc_data = self.read_serial_data_felicity(self.command_dvcc)
            if dvcc_data is False:
                return False

            if len(dvcc_data) != 8:
                logger.error(">>> INFO: dvcc Data size are wrong: %s", len(dvcc_data))
            else:
                self.max_battery_voltage = unpack_from(">H", dvcc_data, 0 * 2)[0] / 100
                self.min_battery_voltage = unpack_from(">H", dvcc_data, 1 * 2)[0] / 100
                self.max_battery_charge_current = unpack_from(">H", dvcc_data, 2 * 2)[0] / 10
                self.max_battery_discharge_current = unpack_from(">H", dvcc_data, 3 * 2)[0] / 10

                logger.debug(">>> INFO: Max Battery voltage: %f V", self.max_battery_voltage)
                logger.debug(">>> INFO: Min Battery voltage: %f V", self.min_battery_voltage)
                logger.debug(">>> INFO: Max Battery charge current: %f A", self.max_battery_charge_current)
                logger.debug(">>> INFO: Max Battery discharge current: %f A", self.max_battery_discharge_current)

        status_data = self.read_serial_data_felicity(self.command_status)
        if status_data is False:
            return False

        if len(status_data) != 6:
            logger.error(">>> INFO: Status Data size are wrong: %s", len(status_data))
        else:
            status_int = unpack_from(">H", status_data)[0]

            # Charge enable
            self.charge_fet = True if (status_int & 0b0000000000000001) > 0 else False
            # Discharge enable
            self.discharge_fet = True if (status_int & 0b0000000000000100) > 0 else False

            logger.debug(">>> INFO: Battery Status: %s", bin(status_int))

            fault_int = unpack_from(">H", status_data, 2 * 2)[0]

            logger.debug(">>> INFO: Battery Fault: %s", bin(fault_int))

            self.protection = Protection()
            #   ALARM = 2 , WARNING = 1 , OK = 0

            # Cell voltage high status
            self.protection.high_cell_voltage = 2 if (fault_int & 0b0000000000000100) > 0 else 0
            # Cell voltage low status
            self.protection.low_cell_voltage = 2 if (fault_int & 0b0000000000001000) > 0 else 0
            # Charge current high status
            self.protection.high_charge_current = 2 if (fault_int & 0b0000000000010000) > 0 else 0
            # Discharge current high status
            self.protection.high_discharge_current = 2 if (fault_int & 0b0000000000100000) > 0 else 0
            # BMS Temperature high status
            self.protection.high_internal_temperature = 2 if (fault_int & 0b0000000001000000) > 0 else 0
            # Cell Temperature high status
            self.protection.high_charge_temperature = 2 if (fault_int & 0b0000000100000000) > 0 else 0
            # Cell Temperature low status
            self.protection.low_charge_temperature = 2 if (fault_int & 0b0000001000000000) > 0 else 0

        return True

    def read_cell_data(self):
        cell_volt_data = self.read_serial_data_felicity(self.command_cell_voltages)
        if len(cell_volt_data) != 32:
            logger.error(">>> INFO: Cell Data size are wrong: %s", len(cell_volt_data))
        else:
            for c in range(self.cell_count):
                try:
                    cell_volts = unpack_from(">H", cell_volt_data, c * 2)
                    if len(cell_volts) != 0:
                        self.cells[c].voltage = cell_volts[0] / 1000
                except struct.error:
                    self.cells[c].voltage = 0
        return True

    def read_temperature_data(self):
        tempBms_data = self.read_serial_data_felicity(self.command_bms_temperature_1)

        if tempBms_data is False:
            return False

        if len(tempBms_data) != 2:
            logger.error(">>> INFO: BMS Temp Data size are wrong: %s", len(tempBms_data))
        else:
            self.temperature_mos = unpack(">h", tempBms_data)[0]

        temperature_1_3_data = self.read_serial_data_felicity(self.command_bms_temperature_1_3)

        if temperature_1_3_data is False:
            return False

        if len(temperature_1_3_data) != 10:
            logger.error(">>> INFO: Temp Data size are wrong: %s", len(temperature_1_3_data))
        else:
            self.temperature_1 = unpack_from(">h", temperature_1_3_data, 1 * 2)[0]
            self.temperature_2 = unpack_from(">h", temperature_1_3_data, 2 * 2)[0]
            self.temperature_3 = unpack_from(">h", temperature_1_3_data, 3 * 2)[0]

            logger.debug(">>> INFO: Battery TempMos: %f C", self.temperature_mos)
            logger.debug(">>> INFO: Battery Temperature_1: %f C", self.temperature_1)
            logger.debug(">>> INFO: Battery Temperature_2: %f C", self.temperature_2)
            logger.debug(">>> INFO: Battery Temperature_3: %f C", self.temperature_3)

        return True

    def read_bms_config(self):
        return True

    def calc_crc(self, data):
        crc = 0xFFFF
        for pos in data:
            crc ^= pos
            for i in range(8):
                if (crc & 1) != 0:
                    crc >>= 1
                    crc ^= 0xA001
                else:
                    crc >>= 1
        return struct.pack("<H", crc)

    def generate_command(self, command):
        buffer = bytearray(self.command_address)
        buffer += self.command_read
        buffer += command
        buffer += self.calc_crc(buffer)

        return buffer

    def read_serial_data_felicity(self, command):
        # use the read_serial_data() function to read the data and then do BMS spesific checks (crc, start bytes, etc)
        data = read_serial_data(self.generate_command(command), self.port, self.baud_rate, self.LENGTH_POS, self.LENGTH_CHECK)
        # logger.debug(">>> INFO: Query: %s",self.generate_command(command))
        # logger.debug(">>> INFO: Result All: %s", data)
        if data is False:
            return False

        start, flag, length = unpack_from("BBB", data)
        crc_calced = self.calc_crc(data[0 : length + 3])
        crc_transfered = data[length + 3 : length + 5]

        # logger.debug(">>> INFO: Result Data: %s", data[3 : length + 3])
        # logger.debug(">>> INFO: Result CRC: %s %s", crc_transfered, crc_calced)

        if crc_transfered != crc_calced:
            logger.error(">>> ERROR: Felicity Incorrect Checksum")
            return False

        if flag == 3:
            return data[3 : length + 3]
        else:
            logger.error(">>> ERROR: Felicity Incorrect Reply")
            return False
