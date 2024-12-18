# -*- coding: utf-8 -*-

# Sinowealth is disabled by default as it causes issues with other devices
# can be enabled by specifying it in the BMS_TYPE setting in the "config.ini"
# https://github.com/Louisvdw/dbus-serialbattery/commit/7aab4c850a5c8d9c205efefc155fe62bb527da8e

from battery import Battery, Cell
from utils import kelvin_to_celsius, read_serial_data, logger
from struct import unpack_from
import sys


class Sinowealth(Battery):
    def __init__(self, port, baud, address):
        super(Sinowealth, self).__init__(port, baud, address)
        self.poll_interval = 2000
        self.type = self.BATTERYTYPE
        self.history.exclude_values_to_calculate = ["charge_cycles"]
        self.temperature_sensors = None

    # command bytes [StartFlag=0A][Command byte][response dataLength=2 to 20 bytes][checksum]
    command_base = b"\x0A\x00\x04"
    command_cell_base = b"\x01"
    command_total_voltage = b"\x0B"
    command_temperature_ext1 = b"\x0C"
    command_temperature_ext2 = b"\x0D"
    command_temperature_int1 = b"\x0E"
    command_temperature_int2 = b"\x0F"
    command_current = b"\x10"
    command_capacity = b"\x11"
    command_remaining_capacity = b"\x12"
    command_soc = b"\x13"
    command_cycle_count = b"\x14"
    command_status = b"\x15"
    command_battery_status = b"\x16"
    command_pack_config = b"\x17"

    command_cell_base = b"\x01"
    BATTERYTYPE = "Sinowealth"
    LENGTH_CHECK = 0
    LENGTH_POS = 0

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
        # hardcoded parameters, to be requested from the BMS in the future
        # self.max_battery_charge_current = utils.MAX_BATTERY_CHARGE_CURRENT
        # self.max_battery_discharge_current = utils.MAX_BATTERY_DISCHARGE_CURRENT

        if self.cell_count is None:
            self.read_pack_config_data()

        self.hardware_version = "Daly/Sinowealth BMS " + str(self.cell_count) + "S"
        logger.debug(self.hardware_version)

        if not self.read_capacity():
            return False

        for c in range(self.cell_count):
            self.cells.append(Cell(False))
        return True

    def refresh_data(self):
        result = self.read_soc()
        result = result and self.read_status_data()
        result = result and self.read_battery_status()
        result = result and self.read_pack_voltage()
        result = result and self.read_pack_current()
        result = result and self.read_cell_data()
        result = result and self.read_temperature_data()
        result = result and self.read_remaining_capacity()
        result = result and self.read_cycle_count()
        return result

    def read_status_data(self):
        status_data = self.read_serial_data_sinowealth(self.command_status)
        # check if connection success
        if status_data is False:
            return False

        # BMS status command layout (from screenshot)
        # [0]     -       -        -        -        -        VDQ     FD      FC
        # [1]     -       FAST_DSG MID_DSG  SLOW_DSG DSGING   CHGING  DSGMOS  CHGMOS
        self.discharge_fet = bool(status_data[1] >> 1 & int(1))  # DSGMOS
        self.charge_fet = bool(status_data[1] & int(1))  # CHGMOS
        logger.debug(
            ">>> INFO: Discharge fet: %s, charge fet: %s",
            self.discharge_fet,
            self.charge_fet,
        )

        if self.cell_count is None:
            self.read_pack_config_data()
        return True

    def read_battery_status(self):
        battery_status = self.read_serial_data_sinowealth(self.command_battery_status)
        # check if connection success
        if battery_status is False:
            return False

        # Battery status command layout (from screenshot)
        # [0]     -       CTO     AFE_SC  AFE_OV  UTD     UTC     OTD     OTC
        # [1]     -       -       -       -       OCD     OC      UV      OV
        self.protection.high_voltage = 2 if bool(battery_status[1] & int(1)) else 0  # OV
        self.protection.low_voltage = 2 if bool(battery_status[1] >> 1 & int(1)) else 0  # UV
        self.protection.high_charge_current = 2 if bool(battery_status[1] >> 2 & int(1)) or bool(battery_status[1] >> 3 & int(1)) else 0  # OC (OCC?)| OCD
        self.protection.high_charge_temperature = 2 if bool(battery_status[0] & int(1)) else 0  # OTC
        self.protection.high_temperature = 2 if bool(battery_status[0] >> 1 & int(1)) else 0  # OTD
        self.protection.low_charge_temperature = 2 if bool(battery_status[0] >> 2 & int(1)) else 0  # UTC
        self.protection.low_temperature = 2 if bool(battery_status[0] >> 3 & int(1)) else 0  # UTD
        return True

    def read_soc(self):
        soc_data = self.read_serial_data_sinowealth(self.command_soc)
        # check if connection success
        if soc_data is False:
            return False
        logger.debug(">>> INFO: current SOC: %u", soc_data[1])
        soc = soc_data[1]
        self.soc = soc
        return True

    def read_cycle_count(self):
        # TODO: cyclecount does not match cycles in the app
        cycle_count = self.read_serial_data_sinowealth(self.command_cycle_count)
        # check if connection success
        if cycle_count is False:
            return False
        self.history.charge_cycles = int(unpack_from(">H", cycle_count[:2])[0])
        logger.debug(">>> INFO: current cycle count: %u", self.history.charge_cycles)
        return True

    def read_pack_voltage(self):
        pack_voltage_data = self.read_serial_data_sinowealth(self.command_total_voltage)
        if pack_voltage_data is False:
            return False
        pack_voltage = unpack_from(">H", pack_voltage_data[:-1])
        pack_voltage = pack_voltage[0] / 1000
        self.voltage = pack_voltage
        logger.debug(">>> INFO: current pack voltage: %f", self.voltage)
        return True

    def read_pack_current(self):
        current_data = self.read_serial_data_sinowealth(self.command_current)
        if current_data is False:
            return False
        current = unpack_from(">i", current_data[:-1])
        current = current[0] / 1000
        logger.debug(">>> INFO: current pack current: %f", current)

        self.current = current
        return True

    def read_remaining_capacity(self):
        remaining_capacity_data = self.read_serial_data_sinowealth(self.command_remaining_capacity)
        if remaining_capacity_data is False:
            return False
        remaining_capacity = unpack_from(">i", remaining_capacity_data[:-1])
        self.capacity_remain = remaining_capacity[0] / 1000
        logger.debug(">>> INFO: remaining battery capacity: %f Ah", self.capacity_remain)
        return True

    def read_capacity(self):
        capacity_data = self.read_serial_data_sinowealth(self.command_capacity)
        if capacity_data is False:
            return False
        capacity = unpack_from(">i", capacity_data[:-1])
        capacity = capacity[0] / 1000
        logger.debug(">>> INFO: Battery capacity: %f Ah", capacity)

        self.capacity = capacity
        return True

    def read_pack_config_data(self):
        # TODO: detect correct chipset, currently the pack_config_map register is parsed as,
        # SH367303 / 367305 / 367306 / 39F003 / 39F004 / BMS_10. So these are the currently supported chips
        pack_config_data = self.read_serial_data_sinowealth(self.command_pack_config)
        if pack_config_data is False:
            return False
        cell_cnt_mask = int(7)
        self.cell_count = (pack_config_data[1] & cell_cnt_mask) + 3
        if self.cell_count < 1 or self.cell_count > 32:
            logger.error(">>> ERROR: No valid cell count returnd: %u", self.cell_count)
            return False
        logger.debug(">>> INFO: Number of cells: %u", self.cell_count)
        temperature_sens_mask = int(~(1 << 6))
        self.temperature_sensors = 1 if (pack_config_data[1] & temperature_sens_mask) else 2  # one means two
        logger.debug(">>> INFO: Number of temperatur sensors: %u", self.temperature_sensors)
        return True

    def read_cell_data(self):
        if self.cell_count is None:
            self.read_pack_config_data()

        for c in range(self.cell_count):
            self.cells[c].voltage = self.read_cell_voltage(c + 1)
        return True

    def read_cell_voltage(self, cell_index):
        cell_data = self.read_serial_data_sinowealth(cell_index.to_bytes(1, byteorder="little"))
        if cell_data is False:
            return None
        cell_voltage = unpack_from(">H", cell_data[:-1])
        cell_voltage = cell_voltage[0] / 1000

        logger.debug(">>> INFO: Cell %u voltage: %f V", cell_index, cell_voltage)
        return cell_voltage

    def read_temperature_data(self):
        if self.temperature_sensors is None:
            return False

        temperature_ext1_data = self.read_serial_data_sinowealth(self.command_temperature_ext1)
        if temperature_ext1_data is False:
            return False

        temperature_ext1 = unpack_from(">H", temperature_ext1_data[:-1])
        self.to_temperature(1, kelvin_to_celsius(temperature_ext1[0] / 10))
        logger.debug(">>> INFO: BMS external temperature 1: %f C", self.temperature_1)

        if self.temperature_sensors == 2:
            temperature_ext2_data = self.read_serial_data_sinowealth(self.command_temperature_ext2)
            if temperature_ext2_data is False:
                return False

            temperature_ext2 = unpack_from(">H", temperature_ext2_data[:-1])
            self.to_temperature(2, kelvin_to_celsius(temperature_ext2[0] / 10))
            logger.debug(">>> INFO: BMS external temperature 2: %f C", self.temperature_2)

        # Internal temperature 1 seems to give a logical value
        temperature_int1_data = self.read_serial_data_sinowealth(self.command_temperature_int1)
        if temperature_int1_data is False:
            return False

        temperature_int1 = unpack_from(">H", temperature_int1_data[:-1])
        logger.debug(
            ">>> INFO: BMS internal temperature 1: %f C",
            kelvin_to_celsius(temperature_int1[0] / 10),
        )

        # Internal temperature 2 seems to give a useless value
        temperature_int2_data = self.read_serial_data_sinowealth(self.command_temperature_int2)
        if temperature_int2_data is False:
            return False

        temperature_int2 = unpack_from(">H", temperature_int2_data[:-1])
        logger.debug(
            ">>> INFO: BMS internal temperature 2: %f C",
            kelvin_to_celsius(temperature_int2[0] / 10),
        )
        return True

    def generate_command(self, command):
        buffer = bytearray(self.command_base)
        buffer[1] = command[0]
        return buffer

    def read_serial_data_sinowealth(self, command):
        data = read_serial_data(
            self.generate_command(command),
            self.port,
            self.baud_rate,
            self.LENGTH_POS,
            self.LENGTH_CHECK,
            int(self.generate_command(command)[2]),
        )
        if data is False:
            return False

        return bytearray(data)
