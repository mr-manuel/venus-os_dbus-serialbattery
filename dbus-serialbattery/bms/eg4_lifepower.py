# -*- coding: utf-8 -*-

# Notes
# Added by https://github.com/dchiquito
# https://github.com/Louisvdw/dbus-serialbattery/pull/212

from __future__ import absolute_import, division, print_function, unicode_literals
from battery import Battery, Cell
from utils import read_serial_data, logger, bytearray_to_string
from struct import unpack_from
import re
import sys


class EG4_Lifepower(Battery):
    def __init__(self, port, baud, address):
        super(EG4_Lifepower, self).__init__(port, baud, address)
        self.type = self.BATTERYTYPE
        self.address = address
        self.command_general = b"\x7E" + address + b"\x01\x00" + self.get_command_general_part() + b"\x0D"
        self.command_hardware_version = b"\x7E" + address + b"\x42\x00\xFC\x0D"
        self.command_firmware_version = b"\x7E" + address + b"\x33\x00" + self.get_command_general_part() + b"\x0D"
        self.history.exclude_values_to_calculate = ["charge_cycles"]

    balancing = 0
    BATTERYTYPE = "EG4 Lifepower"
    LENGTH_CHECK = 5
    LENGTH_POS = 3
    LENGTH_FIXED = None

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

    def get_command_general_part(self):
        """
        Get the second last byte of the command_general command

        0x00:\x7E\x01\x01\x00\x00\x0D
        0x01:\x7E\x01\x01\x00\xFE\x0D
        0x02:\x7E\x02\x01\x00\xFC\x0D
        0x03:\x7E\x03\x01\x00\xFE\x0D
        0x04:\x7E\x04\x01\x00\xF8\x0D
        0x05:\x7E\x05\x01\x00\xFE\x0D
        0x06:\x7E\x06\x01\x00\xFC\x0D
        0x07:\x7E\x07\x01\x00\xFE\x0D
        0x08:\x7E\x08\x01\x00\xF0\x0D
        0x09:\x7E\x09\x01\x00\xFE\x0D
        0x0A:\x7E\x0A\x01\x00\xFC\x0D
        0x0B:\x7E\x0B\x01\x00\xFE\x0D
        0x0C:\x7E\x0C\x01\x00\xF8\x0D
        0x0D:\x7E\x0D\x01\x00\xFE\x0D
        0x0E:\x7E\x0E\x01\x00\xFC\x0D
        0x0F:\x7E\x0D\x01\x00\xFE\x0D
        """
        if self.address == b"\x00":
            return b"\x00"
        elif self.address == b"\x02" or self.address == b"\x06" or self.address == b"\x0A" or self.address == b"\x0E":
            return b"\xFC"
        elif self.address == b"\x04" or self.address == b"\x0C":
            return b"\xF8"
        elif self.address == b"\x08":
            return b"\xF0"
        else:
            return b"\xFE"

    def get_settings(self):
        # After successful connection get_settings() will be called to set up the battery
        # Set the current limits, populate cell count, etc
        # Return True if success, False for failure
        result = False
        result_2 = False

        hardware_version = self.read_serial_data_eg4(self.command_hardware_version)
        if hardware_version:
            # I get some characters that I'm not able to figure out the encoding, probably chinese so I discard it
            # Also remove any special character that is not printable or make no sense.
            self.hardware_version = re.sub(
                r"[^a-zA-Z0-9-._ ]",
                "",
                str(hardware_version, encoding="utf-8", errors="ignore"),
            )
            logger.info(f"Hardware Version for address {bytearray_to_string(self.address)}: {self.hardware_version}")

            result = True

        version = self.read_serial_data_eg4(self.command_firmware_version)
        if version:
            self.version = re.sub(
                r"[^a-zA-Z0-9-._ ]",
                "",
                str(version, encoding="utf-8", errors="ignore"),
            )
            logger.info(f"Firmware Version for address {bytearray_to_string(self.address)}: {self.version}")

            result_2 = True

        # polling every second seems to create some error messages
        # change to 2 seconds
        self.poll_interval = 2000

        return result or result_2

    def refresh_data(self):
        # call all functions that will refresh the battery data.
        # This will be called for every iteration (1 second)
        # Return True if success, False for failure
        return self.read_status_data()

    def read_status_data(self):
        status_data = self.read_serial_data_eg4(self.command_general)
        # check if connection success
        if status_data is False:
            return False

        # Data pulled from https://github.com/slim-bean/powermon

        groups = []
        i = 4
        for j in range(0, 10):
            # groups are formatted like:
            # {group number} {length} ...length shorts...
            # So the first group might be:
            # 01 02 0a 0b 0c 0d
            group_len = status_data[i + 1]
            end = i + 2 + (group_len * 2)
            group_payload = status_data[i + 2 : end]
            groups.append([unpack_from(">H", group_payload, i)[0] for i in range(0, len(group_payload), 2)])
            i = end

        # Cells
        self.cell_count = len(groups[0])

        self.cells = [Cell(True) for _ in range(0, self.cell_count)]
        for i, cell in enumerate(self.cells):
            # there is a situation where the MSB bit of the high byte may come set
            # I got that when I got a high voltage alarm from the unit.
            # make sure that bit is 0, by doing an AND with 32767 (01111111 1111111)
            cell.voltage = (groups[0][i] & 32767) / 1000

        # Current
        self.current = (30000 - groups[1][0]) / 100

        # State of charge
        self.soc = groups[2][0] / 100

        # Full battery capacity
        self.capacity = groups[3][0] / 100

        # Temperature
        self.temp_sensors = 6
        self.temp1 = (groups[4][0] & 0xFF) - 50
        self.temp2 = (groups[4][1] & 0xFF) - 50
        self.temp3 = (groups[4][2] & 0xFF) - 50
        self.temp4 = (groups[4][3] & 0xFF) - 50
        self.temp5 = (groups[4][4] & 0xFF) - 50
        self.temp6 = (groups[4][5] & 0xFF) - 50

        # Alarms
        # 4th bit: Over Current Protection
        self.protection.high_charge_current = 2 if (groups[5][1] & 0b00001000) > 0 else 0
        # 5th bit: Over voltage protection
        self.protection.high_voltage = 2 if (groups[5][1] & 0b00010000) > 0 else 0
        # 6th bit: Under voltage protection
        self.protection.low_voltage = 2 if (groups[5][1] & 0b00100000) > 0 else 0
        # 7th bit: Charging over temp protection
        self.protection.high_charge_temp = 2 if (groups[5][1] & 0b01000000) > 0 else 0
        # 8th bit: Charging under temp protection
        self.protection.low_charge_temp = 2 if (groups[5][1] & 0b10000000) > 0 else 0

        # Cycle counter
        self.history.charge_cycles = groups[6][0]

        # Voltage
        self.voltage = groups[7][0] / 100
        return True

    def get_balancing(self):
        return 1 if self.balancing or self.balancing == 2 else 0

    def read_serial_data_eg4(self, command):
        # use the read_serial_data() function to read the data and then do BMS
        # specific checks (crc, start bytes, etc)
        data = read_serial_data(
            command,
            self.port,
            self.baud_rate,
            self.LENGTH_POS,
            self.LENGTH_CHECK,
            self.LENGTH_FIXED,
        )
        if data is False:
            logger.debug(">>> ERROR: Incorrect Data")
            return False

        # 0x0D always terminates the response
        if data[-1] == 13:
            return data
        else:
            logger.error(">>> ERROR: Incorrect Reply")
            return False
