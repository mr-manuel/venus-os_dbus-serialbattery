# -*- coding: utf-8 -*-

# Notes
# Updated by https://github.com/mr-manuel

from battery import Battery, Cell
from utils import bytearray_to_string, is_bit_set, read_serial_data, logger, ZERO_CHAR
from struct import unpack_from
from re import sub
import sys


class Jkbms(Battery):
    def __init__(self, port, baud, address):
        super(Jkbms, self).__init__(port, baud, address)
        self.type = self.BATTERYTYPE
        self.unique_identifier_tmp = ""
        self.history.exclude_values_to_calculate = ["charge_cycles"]

    BATTERYTYPE = "JKBMS"
    LENGTH_CHECK = 1
    LENGTH_POS = 2
    LENGTH_SIZE = "H"
    CURRENT_ZERO_CONSTANT = 32768
    # byte 5 to 8 is the BMS terminal number
    # byte 5 is default 0x00
    # byte 6 to 8 is the dimension or ID number
    # to test with a RS485 adapter where the address can be set
    command_status = b"\x4E\x57\x00\x13\x00\x00\x00\x00\x06\x03\x00\x00\x00\x00\x00\x00\x68\x00\x00\x01\x29"

    def test_connection(self):
        """
        call a function that will connect to the battery, send a command and retrieve the result.
        The result or call should be unique to this BMS. Battery name or version, etc.
        Return True if success, False for failure
        """
        result = False
        try:
            # get settings to check if the data is valid and the connection is working
            result = self.refresh_data()
            # get the rest of the data to be sure, that all data is valid and the correct battery type is recognized
            # only read next data if the first one was successful, this saves time when checking multiple battery types
            result = result and self.get_settings()
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

        # init the cell array once
        # if len(self.cells) == 0:
        for _ in range(self.cell_count):
            self.cells.append(Cell(False))

        self.hardware_version = (
            "JKBMS "
            + (sub(r"\s+", " ", self.version) + " " if self.version != "" else "")
            + str(self.cell_count)
            + "S"
            + (" (" + self.production + ")" if self.production else "")
        )
        return True

    def refresh_data(self):
        # call all functions that will refresh the battery data.
        # This will be called for every iteration (1 second)
        # Return True if success, False for failure
        return self.read_status_data()

    def get_data(self, bytes, idcode, start, length):
        # logger.debug("start "+str(start) + " length " + str(length))
        # logger.debug(binascii.hexlify(bytearray(bytes[start:start + 1 + length])).decode('ascii'))
        start = bytes.find(idcode, start, start + 1 + length)
        if start < 0:
            return False
        return bytes[start + 1 : start + length + 1]

    def read_status_data(self):
        status_data = self.read_serial_data_jkbms(self.command_status)
        # check if connection success
        if status_data is False:
            return False

        # cell voltages
        offset = 1
        cellbyte_count = unpack_from(">B", self.get_data(status_data, b"\x79", offset, 1))[0]

        offset = cellbyte_count + 30
        cell_count = unpack_from(">H", self.get_data(status_data, b"\x8A", offset, 2))[0]
        # check if the cell count is valid
        if cell_count > 0:
            self.cell_count = cell_count

        if cellbyte_count == 3 * self.cell_count and self.cell_count == len(self.cells):
            offset = 1
            celldata = self.get_data(status_data, b"\x79", offset, 1 + cellbyte_count)

            for c in range(self.cell_count):
                cell_voltage = unpack_from(">xH", celldata, c * 3 + 1)[0] / 1000

                # check if the cell voltage is valid
                if cell_voltage > 0:
                    self.cells[c].voltage = cell_voltage

        # MOSFET temperature
        offset = cellbyte_count + 3
        temperature_mos = unpack_from(">H", self.get_data(status_data, b"\x80", offset, 2))[0]
        # check if the mosfet temperature is valid
        if temperature_mos >= 0:
            self.to_temperature(0, temperature_mos if temperature_mos < 99 else (100 - temperature_mos))

        # Temperature sensors
        offset = cellbyte_count + 6
        temperature_1 = unpack_from(">H", self.get_data(status_data, b"\x81", offset, 2))[0]
        # check if the temperature is valid
        if temperature_1 >= 0:
            self.to_temperature(1, temperature_1 if temperature_1 < 99 else (100 - temperature_1))

        offset = cellbyte_count + 9
        temperature_2 = unpack_from(">H", self.get_data(status_data, b"\x82", offset, 2))[0]
        # check if the temperature is valid
        if temperature_2 >= 0:
            self.to_temperature(2, temperature_2 if temperature_2 < 99 else (100 - temperature_2))

        offset = cellbyte_count + 12
        voltage = unpack_from(">H", self.get_data(status_data, b"\x83", offset, 2))[0]
        self.voltage = voltage / 100

        offset = cellbyte_count + 15
        current = unpack_from(">H", self.get_data(status_data, b"\x84", offset, 2))[0]
        self.current = current / -100 if current < self.CURRENT_ZERO_CONSTANT else (current - self.CURRENT_ZERO_CONSTANT) / 100

        # Continued discharge current
        offset = cellbyte_count + 66
        max_battery_discharge_current = float(unpack_from(">H", self.get_data(status_data, b"\x97", offset, 2))[0])
        # check if the max discharge current is valid
        if max_battery_discharge_current >= 0:
            self.max_battery_discharge_current = max_battery_discharge_current

        # Continued charge current
        offset = cellbyte_count + 72
        max_battery_charge_current = float(unpack_from(">H", self.get_data(status_data, b"\x99", offset, 2))[0])
        # check if the max charge current is valid
        if max_battery_charge_current >= 0:
            self.max_battery_charge_current = max_battery_charge_current

        # the JKBMS resets to
        # 95% SoC, if all cell voltages are above or equal to OVPR (Over Voltage Protection Recovery)
        # 100% Soc, if all cell voltages are above or equal to OVP (Over Voltage Protection)
        offset = cellbyte_count + 18
        soc = unpack_from(">B", self.get_data(status_data, b"\x85", offset, 1))[0]
        # check if the soc is valid
        if soc >= 0 and soc <= 100:
            self.soc = soc

        offset = cellbyte_count + 22
        charge_cycles = unpack_from(">H", self.get_data(status_data, b"\x87", offset, 2))[0]
        # check if the charge cycles are valid
        if charge_cycles >= 0:
            self.history.charge_cycles = charge_cycles

        # offset = cellbyte_count + 25
        # self.capacity_remain = unpack_from('>L', self.get_data(status_data, b'\x89', offset, 4))[0]
        offset = cellbyte_count + 121
        capacity = unpack_from(">L", self.get_data(status_data, b"\xAA", offset, 4))[0]
        # check if the capacity is valid
        if capacity >= 0:
            self.capacity = capacity

        offset = cellbyte_count + 33
        self.to_protection_bits(unpack_from(">H", self.get_data(status_data, b"\x8B", offset, 2))[0])

        offset = cellbyte_count + 36
        self.to_fet_bits(unpack_from(">H", self.get_data(status_data, b"\x8C", offset, 2))[0])

        offset = cellbyte_count + 84
        self.to_balance_bits(unpack_from(">B", self.get_data(status_data, b"\x9D", offset, 1))[0])

        # "User Private Data" field in APP
        offset = cellbyte_count + 155
        tmp = sub(
            " +",
            " ",
            (unpack_from(">8s", self.get_data(status_data, b"\xB4", offset, 8))[0].decode().replace("\x00", " ").strip()),
        )
        self.custom_field = tmp if tmp != "Input Us" else None

        # production date
        try:
            offset = cellbyte_count + 164
            tmp = unpack_from(">4s", self.get_data(status_data, b"\xB5", offset, 4))[0].decode()
            self.production = "20" + tmp + "01" if tmp and tmp != "" else None
        except UnicodeDecodeError:
            self.production = None

        offset = cellbyte_count + 174
        self.version = unpack_from(">15s", self.get_data(status_data, b"\xB7", offset, 15))[0].decode().replace("_", " ").strip()

        offset = cellbyte_count + 197
        self.unique_identifier_tmp = sub(
            " +",
            "_",
            (unpack_from(">24s", self.get_data(status_data, b"\xBA", offset, 24))[0].decode().replace("\x00", " ").replace("Input Userda", "").strip()),
        )

        # show wich cells are balancing
        if self.get_min_cell() is not None and self.get_max_cell() is not None:
            for c in range(self.cell_count):
                if self.balancing and (self.get_min_cell() == c or self.get_max_cell() == c):
                    self.cells[c].balance = True
                else:
                    self.cells[c].balance = False

        # logger.info(self.hardware_version)
        return True

    def unique_identifier(self) -> str:
        """
        Used to identify a BMS when multiple BMS are connected
        """
        return self.unique_identifier_tmp

    def to_fet_bits(self, byte_data):
        tmp = bin(byte_data)[2:].rjust(3, ZERO_CHAR)
        self.charge_fet = is_bit_set(tmp[2])
        self.discharge_fet = is_bit_set(tmp[1])
        self.balancing = is_bit_set(tmp[0])

    def to_balance_bits(self, byte_data):
        tmp = bin(byte_data)[2:]
        self.balance_fet = is_bit_set(tmp)

    def get_balancing(self):
        return 1 if self.balancing else 0

    def get_min_cell(self):
        min_voltage = 9999
        min_cell = None
        for c in range(min(len(self.cells), self.cell_count)):
            if self.cells[c].voltage is not None and min_voltage > self.cells[c].voltage:
                min_voltage = self.cells[c].voltage
                min_cell = c
        return min_cell

    def get_max_cell(self):
        max_voltage = 0
        max_cell = None
        for c in range(min(len(self.cells), self.cell_count)):
            if self.cells[c].voltage is not None and max_voltage < self.cells[c].voltage:
                max_voltage = self.cells[c].voltage
                max_cell = c
        return max_cell

    def to_protection_bits(self, byte_data):
        """
        Bit 0: Low capacity alarm: 1 warning only, 0 nomal -> OK
        Bit 1: MOS tube overtemperature alarm: 1 alarm, 0 nomal -> OK
        Bit 2: Charge over voltage alarm: 1 alarm, 0 nomal -> OK
        Bit 3: Discharge undervoltage alarm: 1 alarm, 0 nomal -> OK
        Bit 4: Battery overtemperature alarm: 1 alarm, 0 nomal -> OK
        Bit 5: Charge overcurrent alarm: 1 alarm, 0 nomal -> OK
        Bit 6: discharge over current alarm: 1 alarm, 0 nomal -> OK
        Bit 7: core differential pressure alarm: 1 alarm, 0 nomal -> OK
        Bit 8: overtemperature alarm in the battery box: 1 alarm, 0 nomal -> OK
        Bit 9: Battery low temperature alarm: 1 alarm, 0 nomal -> OK
        Bit 10: Unit overvoltage: 1 alarm, 0 nomal -> OK
        Bit 11: Unit undervoltage: 1 alarm, 0 nomal -> OK
        Bit 12:309_A protection: 1 alarm, 0 nomal
        Bit 13:309_B protection: 1 alarm, 0 nomal
        """
        pos = 13
        tmp = bin(byte_data)[15 - pos :].rjust(pos + 1, ZERO_CHAR)
        # logger.debug(tmp)

        # low capacity alarm
        self.protection.low_soc = 2 if is_bit_set(tmp[pos - 0]) else 0
        # MOSFET temperature alarm
        self.protection.high_internal_temperature = 2 if is_bit_set(tmp[pos - 1]) else 0
        # charge over voltage alarm
        # TODO: check if "self.soc_reset_requested is False" works,
        # else use "self.soc_reset_last_reached < int(time()) - (60 * 60)"
        self.protection.high_voltage = 2 if is_bit_set(tmp[pos - 2]) else 0
        # discharge under voltage alarm
        self.protection.low_voltage = 2 if is_bit_set(tmp[pos - 3]) else 0
        # charge overcurrent alarm
        self.protection.high_charge_current = 1 if is_bit_set(tmp[pos - 5]) else 0
        # discharge over current alarm
        self.protection.high_discharge_current = 1 if is_bit_set(tmp[pos - 6]) else 0
        # core differential pressure alarm
        self.protection.cell_imbalance = 1 if is_bit_set(tmp[pos - 7]) else 0
        # battery overtemperature alarm OR overtemperature alarm in the battery box
        alarm_temperature_high = 1 if is_bit_set(tmp[pos - 4]) or is_bit_set(tmp[pos - 8]) else 0
        # battery low temperature alarm
        alarm_temperature_low = 1 if is_bit_set(tmp[pos - 9]) else 0
        # cell overvoltage alarm
        self.protection.high_cell_voltage = 1 if is_bit_set(tmp[pos - 10]) else 0
        # cell undervoltage alarm
        self.protection.low_cell_voltage = 1 if is_bit_set(tmp[pos - 11]) else 0
        # check if low/high temp alarm arise during charging
        self.protection.high_charge_temperature = 1 if self.current > 0 and alarm_temperature_high == 1 else 0
        self.protection.low_charge_temperature = 1 if self.current > 0 and alarm_temperature_low == 1 else 0
        # check if low/high temp alarm arise during discharging
        self.protection.high_temperature = 1 if self.current <= 0 and alarm_temperature_high == 1 else 0
        self.protection.low_temperature = 1 if self.current <= 0 and alarm_temperature_low == 1 else 0

    def read_serial_data_jkbms(self, command: str) -> bool:
        """
        use the read_serial_data() function to read the data and then do BMS specific checks (crc, start bytes, etc)
        :param command: the command to be sent to the bms
        :return: True if everything is fine, else False
        """
        data = read_serial_data(
            command,
            self.port,
            self.baud_rate,
            self.LENGTH_POS,
            self.LENGTH_CHECK,
            None,
            self.LENGTH_SIZE,
        )
        if data is False:
            return False

        start, length = unpack_from(">HH", data)
        end, crc_hi, crc_lo = unpack_from(">BHH", data[-5:])

        s = sum(data[0:-4])

        logger.debug("bytearray: " + bytearray_to_string(data))

        if start == 0x4E57 and end == 0x68 and s == crc_lo:
            return data[10 : length - 7]
        elif s != crc_lo:
            logger.error("CRC checksum mismatch: Expected 0x%04x, Got 0x%04x" % (crc_lo, s))
            return False
        else:
            logger.error(">>> ERROR: Incorrect Reply ")
            return False
