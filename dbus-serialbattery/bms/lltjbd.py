# -*- coding: utf-8 -*-

# Notes
# Updated by https://github.com/idstein

from battery import Protection, Battery, Cell
from utils import (
    bytearray_to_string,
    is_bit_set,
    kelvin_to_celsius,
    read_serial_data,
    logger,
    ZERO_CHAR,
    SOC_LOW_ALARM,
    SOC_LOW_WARNING,
)
from struct import unpack_from, pack
import struct
import sys

# Protocol registers
REG_ENTER_FACTORY = 0x00
REG_EXIT_FACTORY = 0x01
# REG_UNKNOWN = 0x02
REG_GENERAL = 0x03
REG_CELL = 0x04
REG_HARDWARE = 0x05
# Firmware 0x16+
REG_USE_PASSWORD = 0x06
REG_SET_PASSWORD = 0x07
# REG_UNKNOWN2 = 0x08 - Maybe define master password?
REG_CLEAR_PASSWORD = 0x09

REG_FRESET = 0x0A

REG_DESIGN_CAP = 0x10
REG_CYCLE_CAP = 0x11
REG_CAP_100 = 0x12
REG_CAP_0 = 0x13
REG_SELF_DSG_RATE = 0x14
REG_MFG_DATE = 0x15
REG_SERIAL_NUM = 0x16
REG_CYCLE_CNT = 0x17
REG_CHGOT = 0x18
REG_CHGOT_REL = 0x19
REG_CHGUT = 0x1A
REG_CHGUT_REL = 0x1B
REG_DSGOT = 0x1C
REG_DSGOT_REL = 0x1D
REG_DSGUT = 0x1E
REG_DSGUT_REL = 0x1F
REG_POVP = 0x20
REG_POVP_REL = 0x21
REG_PUVP = 0x22
REG_PUVP_REL = 0x23
REG_COVP = 0x24
REG_COVP_REL = 0x25
REG_CUVP = 0x26
REG_CUVP_REL = 0x27
REG_CHGOC = 0x28
REG_DSGOC = 0x29
REG_BAL_START = 0x2A
REG_BAL_WINDOW = 0x2B
REG_SHUNT_RES = 0x2C
REG_FUNC_CONFIG = 0x2D
REG_NTC_CONFIG = 0x2E
REG_CELL_CNT = 0x2F
REG_FET_TIME = 0x30
REG_LED_TIME = 0x31
REG_CAP_80 = 0x32
REG_CAP_60 = 0x33
REG_CAP_40 = 0x34
REG_CAP_20 = 0x35
REG_COVP_HIGH = 0x36
REG_CUVP_HIGH = 0x37
REG_SC_DSGOC2 = 0x38
REG_CXVP_HIGH_DELAY_SC_REL = 0x39
REG_CHG_T_DELAYS = 0x3A
REG_DSG_T_DELAYS = 0x3B
REG_PACK_V_DELAYS = 0x3C
REG_CELL_V_DELAYS = 0x3D
REG_CHGOC_DELAYS = 0x3E
REG_DSGOC_DELAYS = 0x3F
# Cut-off voltage turns off GPS protection board
REG_GPS_OFF = 0x40
# Cut-off voltage delay for GPS protection board
REG_GPS_OFF_TIME = 0x41
REG_CAP_90 = 0x42
REG_CAP_70 = 0x43
REG_CAP_50 = 0x44
REG_CAP_30 = 0x45
REG_CAP_10 = 0x46
# REG_CAP2_100 = 0x47

# [0x48, 0x9F] - 87 registers

REG_MFGNAME = 0xA0
REG_MODEL = 0xA1
REG_BARCODE = 0xA2
REG_ERROR = 0xAA
# 0xAB
# 0xAC
REG_CAL_CUR_IDLE = 0xAD
REG_CAL_CUR_CHG = 0xAE
REG_CAL_CUR_DSG = 0xAF

REG_CAL_V_CELL_01 = 0xB0
REG_CAL_V_CELL_02 = 0xB1
REG_CAL_V_CELL_03 = 0xB2
REG_CAL_V_CELL_04 = 0xB3
REG_CAL_V_CELL_05 = 0xB4
REG_CAL_V_CELL_06 = 0xB5
REG_CAL_V_CELL_07 = 0xB6
REG_CAL_V_CELL_08 = 0xB7
REG_CAL_V_CELL_09 = 0xB8
REG_CAL_V_CELL_10 = 0xB9
REG_CAL_V_CELL_11 = 0xBA
REG_CAL_V_CELL_12 = 0xBB
REG_CAL_V_CELL_13 = 0xBC
REG_CAL_V_CELL_14 = 0xBD
REG_CAL_V_CELL_15 = 0xBE
REG_CAL_V_CELL_16 = 0xBF
REG_CAL_V_CELL_17 = 0xC0
REG_CAL_V_CELL_18 = 0xC1
REG_CAL_V_CELL_19 = 0xC2
REG_CAL_V_CELL_20 = 0xC3
REG_CAL_V_CELL_21 = 0xC4
REG_CAL_V_CELL_22 = 0xC5
REG_CAL_V_CELL_23 = 0xC6
REG_CAL_V_CELL_24 = 0xC7
REG_CAL_V_CELL_25 = 0xC8
REG_CAL_V_CELL_26 = 0xC9
REG_CAL_V_CELL_27 = 0xCA
REG_CAL_V_CELL_28 = 0xCB
REG_CAL_V_CELL_29 = 0xCC
REG_CAL_V_CELL_30 = 0xCD
REG_CAL_V_CELL_31 = 0xCE
REG_CAL_V_CELL_32 = 0xCF

REG_CAL_T_NTC_0 = 0xD0
REG_CAL_T_NTC_1 = 0xD1
REG_CAL_T_NTC_2 = 0xD2
REG_CAL_T_NTC_3 = 0xD3
REG_CAL_T_NTC_4 = 0xD4
REG_CAL_T_NTC_5 = 0xD5
REG_CAL_T_NTC_6 = 0xD6
REG_CAL_T_NTC_7 = 0xD7

REG_CAP_REMAINING = 0xE0
REG_CTRL_MOSFET = 0xE1
REG_CTRL_BALANCE = 0xE2
REG_RESET = 0xE3

# Protocol commands
CMD_ENTER_FACTORY_MODE = b"\x56\x78"
CMD_EXIT_FACTORY_MODE = b"\x00\x00"
CMD_EXIT_AND_SAVE_FACTORY_MODE = b"\x28\x28"

# Weak current switch function
FUNC_SW_EN = 0x0001  # bit 0
# Load lock function used to disconnect the load when short circuit is required to recover
FUNC_LOAD_EN = 0x0002  # bit 1
# Enable balancer function
FUNC_BALANCE_EN = 0x0004  # bit 2
# Charge balance, only turn on balance when charging
FUNC_BALANCE_CHARGING_ONLY = 0x0008  # bit 3
# LED power indicator function
FUNC_LED = 0x0010  # bit 4
# Compatible with LED modes
FUNC_LED_NUM = 0x0020  # bit 5
# With history recording
FUNC_RTC = 0x0040  # bit 6
# whether it is necessary to set the range when it is currently used for FCC update
FUNC_EDV = 0x0080  # bit 7
# Additional GPS protection board is connected
FUNC_GPS_EN = 0x0100  # bit 8
# Enable onboard buzzer / GPS protection board buzzer?
FUNC_BUZZER_EN = 0x0200  # bit 9


def checksum(payload):
    return (0x10000 - sum(payload)) % 0x10000


def cmd(op, reg, data):
    payload = [reg, len(data)] + list(data)
    chksum = checksum(payload)
    data = [0xDD, op] + payload + [chksum, 0x77]
    format = f">BB{len(payload)}BHB"
    return struct.pack(format, *data)


def readCmd(reg, data=None):
    if data is None:
        data = []
    return cmd(0xA5, reg, data)


def writeCmd(reg, data=None):
    if data is None:
        data = []
    return cmd(0x5A, reg, data)


class LltJbdProtection(Protection):
    def __init__(self):
        super(LltJbdProtection, self).__init__()
        self.voltage_cell_high = False
        self.voltage_cell_low = False
        self.short = False
        self.IC_inspection = False
        self.software_lock = False

    def set_voltage_cell_high(self, value):
        self.voltage_cell_high = value
        self.cell_imbalance = 2 if self.voltage_cell_low or self.voltage_cell_high else 0

    def set_voltage_cell_low(self, value):
        self.voltage_cell_low = value
        self.cell_imbalance = 2 if self.voltage_cell_low or self.voltage_cell_high else 0

    def set_short(self, value):
        self.short = value
        self.set_cell_imbalance(2 if self.short or self.IC_inspection or self.software_lock else 0)

    def set_ic_inspection(self, value):
        self.IC_inspection = value
        self.set_cell_imbalance(2 if self.short or self.IC_inspection or self.software_lock else 0)

    def set_software_lock(self, value):
        self.software_lock = value
        self.set_cell_imbalance(2 if self.short or self.IC_inspection or self.software_lock else 0)


class LltJbd(Battery):
    def __init__(self, port, baud, address):
        super(LltJbd, self).__init__(port, baud, address)
        self.protection = LltJbdProtection()
        self.type = self.BATTERYTYPE
        self.address = address
        self._product_name: str = ""
        self.has_settings = False
        self.reset_soc = 100
        self.soc_to_set = None
        self.factory_mode = False
        self.writable = False
        self.trigger_force_disable_discharge = None
        self.trigger_force_disable_charge = None
        self.trigger_disable_balancer = None
        self.cycle_capacity = None
        # list of available callbacks, in order to display the buttons in the GUI
        self.available_callbacks = [
            "force_charging_off_callback",
            "force_discharging_off_callback",
            "turn_balancing_off_callback",
        ]
        self.history.exclude_values_to_calculate = ["charge_cycles"]

    BATTERYTYPE = "LLT/JBD"
    LENGTH_CHECK = 6
    LENGTH_POS = 3

    command_general = readCmd(REG_GENERAL)  # b"\xDD\xA5\x03\x00\xFF\xFD\x77"
    command_cell = readCmd(REG_CELL)  # b"\xDD\xA5\x04\x00\xFF\xFC\x77"
    command_hardware = readCmd(REG_HARDWARE)  # b"\xDD\xA5\x05\x00\xFF\xFB\x77"

    def test_connection(self):
        """
        call a function that will connect to the battery, send a command and retrieve the result.
        The result or call should be unique to this BMS. Battery name or version, etc.
        Return True if success, False for failure
        """
        result = False
        try:
            # LLT/JBD does not seem to support addresses, so launch only on address 0x00
            # For BLE devices the address is never 0x00, ignore it in that case (baud_rate is -1 in that case)
            if self.address != b"\x00" and self.baud_rate != -1:
                return False

            # 1) Read name of BMS
            # 2) Try read BMS settings
            # 3) Refresh general data
            result = self.read_hardware_data() and self.get_settings() and self.refresh_data()
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

    def product_name(self) -> str:
        return self._product_name

    def get_settings(self):
        if not self.read_gen_data():
            return False

        with self.eeprom(writable=False):
            cycle_cap = self.read_serial_data_llt(readCmd(REG_CYCLE_CAP))

            if cycle_cap:
                self.cycle_capacity = float(unpack_from(">H", cycle_cap)[0])

            charge_over_current = self.read_serial_data_llt(readCmd(REG_CHGOC))

            if charge_over_current:
                self.max_battery_charge_current = abs(float(unpack_from(">h", charge_over_current)[0] / 100.0))

            discharge_over_current = self.read_serial_data_llt(readCmd(REG_DSGOC))

            if discharge_over_current:
                self.max_battery_discharge_current = abs(float(unpack_from(">h", discharge_over_current)[0] / -100.0))

            func_config = self.read_serial_data_llt(readCmd(REG_FUNC_CONFIG))

            if func_config:
                self.func_config = unpack_from(">H", func_config)[0]
                self.balance_fet = (self.func_config & FUNC_BALANCE_EN) != 0

        return True

    def reset_soc_callback(self, path, value):
        if value is None:
            return False

        if value < 0 or value > 100:
            return False

        self.reset_soc = value
        self.soc_to_set = value

        return True

    def write_soc(self):
        if self.soc_to_set is None or self.soc_to_set != 100 or not self.voltage:
            return False

        logger.info(f"write soc {self.soc_to_set}%")
        self.soc_to_set = None  # Reset value, so we will set it only once

        # TODO implement logic to map current pack readings into
        # REG_CAP_100, REG_CAP_90, REG_CAP_80, REG_CAP_70, REG_CAP_60, ...
        with self.eeprom(writable=True):
            pack_voltage = struct.pack(">H", int(self.voltage * 10))
            self.read_serial_data_llt(writeCmd(REG_CAP_100, pack_voltage))

    def force_charging_off_callback(self, path, value):
        if value is None:
            return False

        if value == 0:
            self.trigger_force_disable_charge = False
            return True

        if value == 1:
            self.trigger_force_disable_charge = True
            return True

        return False

    def force_discharging_off_callback(self, path, value):
        if value is None:
            return False

        if value == 0:
            self.trigger_force_disable_discharge = False
            return True

        if value == 1:
            self.trigger_force_disable_discharge = True
            return True

        return False

    def write_charge_discharge_mos(self):
        if self.trigger_force_disable_charge is None and self.trigger_force_disable_discharge is None:
            return False

        charge_disabled = 0 if self.charge_fet else 1
        if self.trigger_force_disable_charge is not None:
            charge_disabled = 1 if self.trigger_force_disable_charge else 0
            logger.info(f"write force disable charging: {'true' if self.trigger_force_disable_charge else 'false'}")
        self.trigger_force_disable_charge = None

        discharge_disabled = 0 if self.discharge_fet else 1
        if self.trigger_force_disable_discharge is not None:
            discharge_disabled = 1 if self.trigger_force_disable_discharge else 0
            logger.info(f"write force disable discharging: {'true' if self.trigger_force_disable_discharge else 'false'}")
        self.trigger_force_disable_discharge = None

        logger.debug(
            f"trigger_force_disable_charge: {self.trigger_force_disable_charge} - " + f"trigger_force_disable_discharge: {self.trigger_force_disable_discharge}"
        )
        logger.debug(f"CHARGE: charge_disabled: {charge_disabled} - " + f"charge_fet: {self.charge_fet}")
        logger.debug(f"DISCHARGE: discharge_disabled: {discharge_disabled} - " + f"discharge_fet: {self.discharge_fet}")

        mosdata = pack(">BB", 0, charge_disabled | (discharge_disabled << 1))

        reply = self.read_serial_data_llt(writeCmd(REG_CTRL_MOSFET, mosdata))

        if reply is False:
            logger.error("write force disable charge/discharge failed")
            return False

    def turn_balancing_off_callback(self, path, value):
        if value is None:
            return False

        if value == 0:
            self.trigger_disable_balancer = False
            return True

        if value == 1:
            self.trigger_disable_balancer = True
            return True

        return False

    def write_balancer(self):
        if self.trigger_disable_balancer is None:
            return False

        disable_balancer = self.trigger_disable_balancer
        logger.info(f"write disable balancer: {'true' if self.trigger_disable_balancer else 'false'}")
        self.trigger_disable_balancer = None
        new_func_config = None

        with self.eeprom():
            func_config = self.read_serial_data_llt(readCmd(REG_FUNC_CONFIG))

            if func_config:
                self.func_config = unpack_from(">H", func_config)[0]
                balancer_enabled = self.func_config & FUNC_BALANCE_EN

                # Balance is enabled, force disable OR balancer is disabled and force enable
                if (balancer_enabled != 0 and disable_balancer) or (balancer_enabled == 0 and not disable_balancer):
                    new_func_config = self.func_config ^ FUNC_BALANCE_EN

        if new_func_config:
            new_func_config_bytes = pack(">H", new_func_config)

            with self.eeprom(writable=True):
                reply = self.read_serial_data_llt(writeCmd(REG_FUNC_CONFIG, new_func_config_bytes))

                if reply is False:
                    logger.error("write force disable balancer failed")
                    return False
                else:
                    self.func_config = new_func_config
                    self.balance_fet = (self.func_config & FUNC_BALANCE_EN) != 0

        return True

    def refresh_data(self):
        self.write_charge_discharge_mos()
        self.write_balancer()
        return self.read_gen_data() and self.read_cell_data()

    def to_protection_bits(self, byte_data):
        tmp = bin(byte_data)[2:].rjust(13, ZERO_CHAR)

        self.protection.high_voltage = 2 if is_bit_set(tmp[10]) else 0
        self.protection.low_voltage = 2 if is_bit_set(tmp[9]) else 0
        self.protection.high_charge_temperature = 1 if is_bit_set(tmp[8]) else 0
        self.protection.low_charge_temperature = 1 if is_bit_set(tmp[7]) else 0
        self.protection.high_temperature = 1 if is_bit_set(tmp[6]) else 0
        self.protection.low_temperature = 1 if is_bit_set(tmp[5]) else 0
        self.protection.high_charge_current = 1 if is_bit_set(tmp[4]) else 0
        self.protection.high_discharge_current = 1 if is_bit_set(tmp[3]) else 0

        # Software implementations for low soc
        self.protection.low_soc = 2 if self.soc < SOC_LOW_ALARM else 1 if self.soc < SOC_LOW_WARNING else 0

        # extra protection flags for LltJbd
        self.protection.set_voltage_cell_low = is_bit_set(tmp[11])
        self.protection.set_voltage_cell_high = is_bit_set(tmp[12])
        self.protection.set_software_lock = is_bit_set(tmp[0])
        self.protection.set_IC_inspection = is_bit_set(tmp[1])
        self.protection.set_short = is_bit_set(tmp[2])

    def to_cell_bits(self, byte_data, byte_data_high):
        # init the cell array once
        if len(self.cells) == 0:
            for _ in range(self.cell_count):
                logger.debug("#" + str(_))
                self.cells.append(Cell(False))

        # get up to the first 16 cells
        tmp = bin(byte_data)[2:].rjust(min(self.cell_count, 16), ZERO_CHAR)
        # 4 cells
        # tmp = 0101
        # 16 cells
        # tmp = 0101010101010101

        tmp_reversed = list(reversed(tmp))
        # print(tmp_reversed) --> ['1', '0', '1', '0', '1', '0', '1', '0', '1', '0', '1', '0', '1', '0', '1', '0']
        # [cell1, cell2, cell3, ...]

        if self.cell_count > 16:
            tmp2 = bin(byte_data_high)[2:].rjust(self.cell_count - 16, ZERO_CHAR)
            # tmp = 1100110011001100
            tmp_reversed = tmp_reversed + list(reversed(tmp2))
            # print(tmp_reversed) --> [
            # '1', '0', '1', '0', '1', '0', '1', '0', '1', '0', '1', '0', '1', '0', '1', '0',
            # '0', '0', '1', '1', '0', '0', '1', '1', '0', '0', '1', '1', '0', '0', '1', '1'
            # ]
            # [
            # cell1, cell2, ..., cell16,
            # cell17, cell18, ..., cell32
            # ]

        for c in range(self.cell_count):
            if is_bit_set(tmp_reversed[c]):
                self.cells[c].balance = True
            else:
                self.cells[c].balance = False

        """
        # clear the list
        for c in self.cells:
            self.cells.remove(c)
        # get up to the first 16 cells
        tmp = bin(byte_data)[2:].rjust(min(self.cell_count, 16), ZERO_CHAR)
        for bit in reversed(tmp):
            self.cells.append(Cell(is_bit_set(bit)))
        # get any cells above 16
        if self.cell_count > 16:
            tmp = bin(byte_data_high)[2:].rjust(self.cell_count - 16, ZERO_CHAR)
            for bit in reversed(tmp):
                self.cells.append(Cell(is_bit_set(bit)))
        """

    def to_fet_bits(self, byte_data):
        tmp = bin(byte_data)[2:].rjust(2, ZERO_CHAR)
        self.charge_fet = is_bit_set(tmp[1])
        self.discharge_fet = is_bit_set(tmp[0])

    def read_gen_data(self):
        gen_data = self.read_serial_data_llt(self.command_general)
        # check if connect success
        if gen_data is False or len(gen_data) < 23:
            return False

        (
            voltage,
            current,
            capacity_remain,
            capacity,
            self.history.charge_cycles,
            self.production,
            balance,
            balance2,
            protection,
            version,
            soc,
            fet,
            self.cell_count,
            temperature_sensors,
        ) = unpack_from(">HhHHHHhHHBBBBB", gen_data)

        self.voltage = voltage / 100
        self.current = current / 100

        # Some requested, that the SOC is calculated by using the cycle_capacity and capacity_remain
        # but this is not possible, because the values do not match and are very random
        # See https://github.com/mr-manuel/venus-os_dbus-serialbattery/issues/47#issuecomment-2239210663

        # https://github.com/Louisvdw/dbus-serialbattery/issues/769#issuecomment-1720805325
        # if not self.cycle_capacity or self.cycle_capacity < capacity_remain:
        #     self.cycle_capacity = capacity

        # self.soc = round(100 * capacity_remain / capacity, 2)

        self.soc = soc

        self.capacity_remain = capacity_remain / 100
        self.capacity = capacity / 100
        self.to_cell_bits(balance, balance2)
        self.hardware_version = float(str(version >> 4 & 0x0F) + "." + str(version & 0x0F))
        self.to_fet_bits(fet)
        self.to_protection_bits(protection)

        # 0 = MOS, 1 = temp 1, 2 = temp 2
        for t in range(temperature_sensors):
            if len(gen_data) < 23 + (2 * t) + 2:
                logger.warn(
                    "Expected %d temperature sensors, but received only %d sensor readings!",
                    temperature_sensors,
                    t,
                )
                return True
            temperature = unpack_from(">H", gen_data, 23 + (2 * t))[0]
            # if there is only one sensor, use it as the main temperature sensor
            if temperature_sensors == 1:
                self.to_temperature(1, kelvin_to_celsius(temperature / 10))
            else:
                self.to_temperature(t, kelvin_to_celsius(temperature / 10))

        return True

    def read_cell_data(self):
        cell_data = self.read_serial_data_llt(self.command_cell)
        # check if connect success
        if cell_data is False or len(cell_data) < self.cell_count * 2:
            return False

        for c in range(self.cell_count):
            try:
                cell_volts = unpack_from(">H", cell_data, c * 2)
                if len(cell_volts) != 0:
                    self.cells[c].voltage = cell_volts[0] / 1000
            except struct.error:
                self.cells[c].voltage = 0
        return True

    def read_hardware_data(self):
        hardware_data = self.read_serial_data_llt(self.command_hardware)
        # check if connection success
        if hardware_data is False:
            return False

        self._product_name = unpack_from(">" + str(len(hardware_data)) + "s", hardware_data)[0].decode("ascii", errors="ignore")
        logger.debug(self._product_name)
        return True

    @staticmethod
    def validate_packet(data):
        if data is False:
            return False

        start, op, status, payload_length = unpack_from("BBBB", data)

        logger.debug("bytearray: " + bytearray_to_string(data))

        if start != 0xDD:
            logger.error(">>> ERROR: Invalid response packet. Expected begin packet character 0xDD")
        if status != 0x0:
            logger.warn(">>> WARN: BMS rejected request. Status " + str(status))
            return False
        if len(data) != payload_length + 7:
            logger.error(">>> ERROR: BMS send insufficient data. Received " + str(len(data)) + " expected " + str(payload_length + 7))
            return False
        chk_sum, end = unpack_from(">HB", data, payload_length + 4)
        if end != 0x77:
            logger.error(">>> ERROR: Incorrect Reply. Expected end packet character 0x77")
            return False
        if chk_sum != checksum(data[2:-3]):
            logger.error(">>> ERROR: Invalid checksum.")
            return False

        payload = data[4 : payload_length + 4]

        return payload

    def read_serial_data_llt(self, command):
        data = read_serial_data(
            command,
            self.port,
            self.baud_rate,
            self.LENGTH_POS,
            self.LENGTH_CHECK,
            battery_online=self.online,
        )
        return self.validate_packet(data)

    def __enter__(self):
        if self.read_serial_data_llt(writeCmd(REG_ENTER_FACTORY, CMD_ENTER_FACTORY_MODE)):
            self.factory_mode = True

    def __exit__(self, type, value, traceback):
        cmd_value = CMD_EXIT_AND_SAVE_FACTORY_MODE if self.writable else CMD_EXIT_FACTORY_MODE
        if self.factory_mode:
            if not self.read_serial_data_llt(writeCmd(REG_EXIT_FACTORY, cmd_value)):
                logger.error(">>> ERROR: Unable to exit factory mode.")
            else:
                self.factory_mode = False
                self.writable = False

    def eeprom(self, writable=False):
        self.writable = writable
        return self
