# -*- coding: utf-8 -*-

# Notes
# Added by https://github.com/wollew
# https://github.com/Louisvdw/dbus-serialbattery/pull/530

from battery import Protection, Battery, Cell
from utils import logger
import serial
import sys


class Seplos(Battery):
    def __init__(self, port, baud, address):
        super(Seplos, self).__init__(port, baud, address)
        self.address = address
        self.type = self.BATTERYTYPE
        self.poll_interval = 5000
        self.history.exclude_values_to_calculate = ["charge_cycles"]

    BATTERYTYPE = "Seplos"

    COMMAND_STATUS = 0x42
    COMMAND_ALARM = 0x44
    COMMAND_PROTOCOL_VERSION = 0x4F
    COMMAND_VENDOR_INFO = 0x51

    @staticmethod
    def int_from_1byte_hex_ascii(data: bytes, offset: int, signed=False):
        return int.from_bytes(
            bytes.fromhex(data[offset : offset + 2].decode("ascii")),
            byteorder="big",
            signed=signed,
        )

    @staticmethod
    def int_from_2byte_hex_ascii(data: bytes, offset: int, signed=False):
        return int.from_bytes(
            bytes.fromhex(data[offset : offset + 4].decode("ascii")),
            byteorder="big",
            signed=signed,
        )

    @staticmethod
    def get_checksum(frame: bytes) -> int:
        """implements the Seplos checksum algorithm, returns 4 bytes"""
        checksum = 0
        for b in frame:
            checksum += b
        checksum %= 0xFFFF
        checksum ^= 0xFFFF
        checksum += 1
        return checksum

    @staticmethod
    def get_info_length(info: bytes) -> int:
        """implements the Seplos checksum for the info length"""
        lenid = len(info)
        if lenid == 0:
            return 0

        lchksum = (lenid & 0xF) + ((lenid >> 4) & 0xF) + ((lenid >> 8) & 0xF)
        lchksum %= 16
        lchksum ^= 0xF
        lchksum += 1

        return (lchksum << 12) + lenid

    @staticmethod
    def encode_cmd(address: bytes, cid2: int, info: bytes = b"") -> bytes:
        """encodes a command sent to a battery (cid1=0x46)"""
        try:
            cid1 = 0x46

            info_length = Seplos.get_info_length(info)

            address_int = int.from_bytes(address, byteorder="big")

            frame = "{:02X}{:02X}{:02X}{:02X}{:04X}".format(0x20, address_int, cid1, cid2, info_length).encode()
            frame += info

            checksum = Seplos.get_checksum(frame)
            encoded = b"~" + frame + "{:04X}".format(checksum).encode() + b"\r"
            return encoded
        except Exception:
            (
                exception_type,
                exception_object,
                exception_traceback,
            ) = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
            return b""

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

        # give the user a feedback that no BMS was found
        if not result:
            logger.error(">>> ERROR: No reply - returning")

        return result

    def get_settings(self):
        # After successful connection get_settings() will be called to set up the battery.
        # Set the current limits, populate cell count, etc.
        # Return True if success, False for failure

        # BMS does not provide max charge-/discharge, so we have to use hardcoded/config values
        # self.max_battery_charge_current = utils.MAX_BATTERY_CHARGE_CURRENT
        # self.max_battery_discharge_current = utils.MAX_BATTERY_DISCHARGE_CURRENT
        if not self.read_status_data():
            return False

        # init the cell array
        for _ in range(self.cell_count):
            self.cells.append(Cell(False))

        return True

    def refresh_data(self):
        # call all functions that will refresh the battery data.
        # This will be called for every iteration (self.poll_interval)
        # Return True if success, False for failure
        result_status = self.read_status_data()
        result_alarm = self.read_alarm_data()

        return result_status and result_alarm

    @staticmethod
    def decode_alarm_byte(data_byte: int, alarm_bit: int, warn_bit: int):
        if data_byte & (1 << alarm_bit) != 0:
            return Protection.ALARM
        if data_byte & (1 << warn_bit) != 0:
            return Protection.WARNING
        return Protection.OK

    def read_alarm_data(self):
        logger.debug("read alarm data")
        data = self.read_serial_data_seplos(self.encode_cmd(self.address, cid2=self.COMMAND_ALARM, info=b"01"))
        # check if we could successfully read data and we have the expected length of 98 bytes
        if data is False or len(data) != 98:
            return False

        try:
            logger.debug("alarm info raw {}".format(data))
            return self.decode_alarm_data(bytes.fromhex(data.decode("ascii")))
        except (ValueError, UnicodeDecodeError) as e:
            logger.warning("could not hex-decode raw alarm data", exc_info=e)
            return False

    def decode_alarm_data(self, data: bytes):
        logger.debug("alarm info decoded {}".format(data))
        voltage_alarm_byte = data[30]
        self.protection.low_cell_voltage = Seplos.decode_alarm_byte(data_byte=voltage_alarm_byte, alarm_bit=3, warn_bit=2)
        self.protection.high_cell_voltage = Seplos.decode_alarm_byte(data_byte=voltage_alarm_byte, alarm_bit=1, warn_bit=0)
        self.protection.low_voltage = Seplos.decode_alarm_byte(data_byte=voltage_alarm_byte, alarm_bit=7, warn_bit=6)
        self.protection.high_voltage = Seplos.decode_alarm_byte(data_byte=voltage_alarm_byte, alarm_bit=5, warn_bit=4)

        temperature_alarm_byte = data[31]
        self.protection.low_charge_temperature = Seplos.decode_alarm_byte(data_byte=temperature_alarm_byte, alarm_bit=3, warn_bit=2)
        self.protection.high_charge_temperature = Seplos.decode_alarm_byte(data_byte=temperature_alarm_byte, alarm_bit=1, warn_bit=0)
        self.protection.low_temperature = Seplos.decode_alarm_byte(data_byte=temperature_alarm_byte, alarm_bit=7, warn_bit=6)
        self.protection.high_temperature = Seplos.decode_alarm_byte(data_byte=temperature_alarm_byte, alarm_bit=5, warn_bit=4)

        current_alarm_byte = data[33]
        self.protection.high_charge_current = Seplos.decode_alarm_byte(data_byte=current_alarm_byte, alarm_bit=1, warn_bit=0)
        self.protection.high_discharge_current = Seplos.decode_alarm_byte(data_byte=current_alarm_byte, alarm_bit=3, warn_bit=2)

        soc_alarm_byte = data[34]
        self.protection.low_soc = Seplos.decode_alarm_byte(data_byte=soc_alarm_byte, alarm_bit=3, warn_bit=2)

        switch_byte = data[35]
        self.discharge_fet = True if switch_byte & 0b01 != 0 else False
        self.charge_fet = True if switch_byte & 0b10 != 0 else False
        return True

    def read_status_data(self):
        logger.debug("read status data")

        data = self.read_serial_data_seplos(self.encode_cmd(self.address, cid2=0x42, info=b"01"))

        # check if reading data was successful and has the expected data length of 150 byte
        if data is False or len(data) != 150:
            return False

        if not self.decode_status_data(data):
            return False

        return True

    def decode_status_data(self, data):
        cell_count_offset = 4
        voltage_offset = 6
        temps_offset = 72
        self.cell_count = Seplos.int_from_1byte_hex_ascii(data=data, offset=cell_count_offset)
        if self.cell_count == len(self.cells):
            for i in range(self.cell_count):
                voltage = Seplos.int_from_2byte_hex_ascii(data, voltage_offset + i * 4) / 1000
                self.cells[i].voltage = voltage
                logger.debug("Voltage cell[{}]={}V".format(i, voltage))

        self.temperature_1 = (Seplos.int_from_2byte_hex_ascii(data, temps_offset + 0 * 4) - 2731) / 10
        self.temperature_2 = (Seplos.int_from_2byte_hex_ascii(data, temps_offset + 1 * 4) - 2731) / 10
        self.temperature_3 = (Seplos.int_from_2byte_hex_ascii(data, temps_offset + 2 * 4) - 2731) / 10
        self.temperature_4 = (Seplos.int_from_2byte_hex_ascii(data, temps_offset + 3 * 4) - 2731) / 10
        temperature_environment = (Seplos.int_from_2byte_hex_ascii(data, temps_offset + 4 * 4) - 2731) / 10  # currently not available in the Battery class
        self.temperature_mos = (Seplos.int_from_2byte_hex_ascii(data, temps_offset + 5 * 4) - 2731) / 10
        logger.debug("Temp cell1={}°C".format(self.temperature_1))
        logger.debug("Temp cell2={}°C".format(self.temperature_2))
        logger.debug("Temp cell3={}°C".format(self.temperature_3))
        logger.debug("Temp cell4={}°C".format(self.temperature_4))
        logger.debug("Environment temperature = {}°C,  Power/MOSFET temperature = {}°C".format(temperature_environment, self.temperature_mos))

        self.current = Seplos.int_from_2byte_hex_ascii(data, offset=96, signed=True) / 100
        self.voltage = Seplos.int_from_2byte_hex_ascii(data, offset=100) / 100
        self.capacity_remain = Seplos.int_from_2byte_hex_ascii(data, offset=104) / 100
        self.capacity = Seplos.int_from_2byte_hex_ascii(data, offset=110) / 100
        self.soc = Seplos.int_from_2byte_hex_ascii(data, offset=114) / 10
        self.history.charge_cycles = Seplos.int_from_2byte_hex_ascii(data, offset=122)
        self.hardware_version = "Seplos BMS {}S".format(self.cell_count)
        logger.debug("Current = {}A , Voltage = {}V".format(self.current, self.voltage))
        logger.debug("Capacity = {}/{}Ah , SOC = {}%".format(self.capacity_remain, self.capacity, self.soc))
        logger.debug("Cycles = {}".format(self.history.charge_cycles))
        logger.debug("HW:" + self.hardware_version)

        return True

    @staticmethod
    def is_valid_frame(data: bytes) -> bool:
        """checks if data contains a valid frame
        * minimum length is 18 Byte
        * checksum needs to be valid
        * also checks for error code as return code in cid2
        * not checked: lchksum
        """
        if len(data) < 18:
            logger.debug("short read, data={}".format(data))
            return False

        chksum = Seplos.get_checksum(data[1:-5])
        if chksum != Seplos.int_from_2byte_hex_ascii(data, -5):
            logger.warning("checksum error")
            return False

        cid2 = data[7:9]
        if cid2 != b"00":
            logger.warning("command returned with error code {}".format(cid2))
            return False

        return True

    def read_serial_data_seplos(self, command):
        logger.debug("read serial data seplos")

        with serial.Serial(self.port, baudrate=self.baud_rate, timeout=1) as ser:
            ser.flushOutput()
            ser.flushInput()
            written = ser.write(command)
            logger.debug("wrote {} bytes to serial port {}, command={}".format(written, self.port, command))

            data = ser.readline()

            if not Seplos.is_valid_frame(data):
                return False

            length_pos = 10
            return_data = data[length_pos + 3 : -5]
            info_length = Seplos.int_from_2byte_hex_ascii(b"0" + data[length_pos:], 0)
            logger.debug("returning info data of length {}, info_length is {} : {}".format(len(return_data), info_length, return_data))

            return return_data
