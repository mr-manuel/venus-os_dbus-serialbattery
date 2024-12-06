# -*- coding: utf-8 -*-

# NOTES
# Please see "Add/Request a new BMS" https://mr-manuel.github.io/venus-os_dbus-serialbattery_docs/general/supported-bms#add-by-opening-a-pull-request
# in the documentation for a checklist what you have to do, when adding a new BMS

# avoid importing wildcards, remove unused imports
from battery import Battery, Cell
from utils import read_serial_data, logger
from struct import unpack_from
import sys


class BatteryTemplate(Battery):
    def __init__(self, port, baud, address):
        super(BatteryTemplate, self).__init__(port, baud, address)
        self.type = self.BATTERYTYPE

        # If the BMS could be connected over RS485/Modbus and an address can be configured
        # please use the address in your commands. This will allow multiple batteries to be connected
        # on the same USB to RS485 adapter
        self.address = address

    BATTERYTYPE = "Template"

    # BMS specific, could be removed, if not needed
    LENGTH_CHECK = 4

    # BMS specific, could be removed, if not needed
    LENGTH_POS = 3

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

    def unique_identifier(self) -> str:
        """
        Used to identify a BMS when multiple BMS are connected
        Provide a unique identifier from the BMS to identify a BMS, if multiple same BMS are connected
        e.g. the serial number
        If there is no such value, please remove this function
        """
        return self.serial_number

    def get_settings(self):
        """
        After successful connection get_settings() will be called to set up the battery
        Set all values that only need to be set once
        Return True if success, False for failure
        """

        # MANDATORY values to set
        # does not need to be in this function, but has to be set at least once
        # could also be read in a function that is called from refresh_data()
        #
        # if not available from battery, then add a section in the `config.default.ini`
        # under ; --------- BMS specific settings ---------
        """
        # number of connected cells (int)
        self.cell_count = VALUE_FROM_BMS

        # capacity of the battery in ampere hours (float)
        self.capacity = VALUE_FROM_BMS
        """

        # OPTIONAL values to set
        # does not need to be in this function
        # could also be read in a function that is called from refresh_data()
        """
        # maximum charge current in amps (float)
        self.max_battery_charge_current = VALUE_FROM_BMS

        # maximum discharge current in amps (float)
        self.max_battery_discharge_current = VALUE_FROM_BMS

        # custom field, that the user can set in the BMS software (str)
        self.custom_field = VALUE_FROM_BMS

        # maximum voltage of the battery in V (float)
        self.max_battery_voltage_bms = VALUE_FROM_BMS

        # minimum voltage of the battery in V (float)
        self.min_battery_voltage_bms = VALUE_FROM_BMS

        # production date of the battery (str)
        self.production = VALUE_FROM_BMS

        # hardware version of the BMS (str)
        self.hardware_version = VALUE_FROM_BMS
        self.hardware_version = f"TemplateBMS {self.hardware_version} {self.cell_count}S ({self.production})"

        # serial number of the battery (str)
        self.serial_number = VALUE_FROM_BMS
        """

        # init the cell array once
        if len(self.cells) == 0:
            for _ in range(self.cell_count):
                self.cells.append(Cell(False))

        return True

    def refresh_data(self):
        """
        call all functions that will refresh the battery data.
        This will be called for every iteration (1 second)
        Return True if success, False for failure
        """
        result = self.read_status_data()

        # only read next dafa if the first one was successful
        result = result and self.read_cell_data()

        # this is only an example, you can combine all into one function
        # or split it up into more functions, whatever fits best for your BMS

        return result

    def read_status_data(self):
        # read the status data
        status_data = self.read_serial_data_template(self.command_status)

        # check if connection was successful
        if status_data is False:
            return False

        # unpack the data
        (
            value_1,
            value_2,
            value_3,
            value_4,
            value_5,
        ) = unpack_from(">bb??bhx", status_data)

        # Integrate a check to be sure, that the received data is from the BMS type you are making this driver for

        # MANDATORY values to set
        """
        # voltage of the battery in volts (float)
        self.voltage = VALUE_FROM_BMS

        # current of the battery in amps (float)
        self.current = VALUE_FROM_BMS

        # state of charge in percent (float)
        self.soc = VALUE_FROM_BMS

        # temperature sensor 1 in °C (float)
        temp1 = VALUE_FROM_BMS
        self.to_temp(1, temp1)

        # status of the battery if charging is enabled (bool)
        self.charge_fet = VALUE_FROM_BMS

        # status of the battery if discharging is enabled (bool)
        self.discharge_fet = VALUE_FROM_BMS
        """

        # OPTIONAL values to set
        """
        # remaining capacity of the battery in ampere hours (float)
        # if not available, then it's calculated from the SOC and the capacity
        self.capacity_remaining = VALUE_FROM_BMS

        # temperature sensor 2 in °C (float)
        temp2 = VALUE_FROM_BMS
        self.to_temp(2, temp2)

        # temperature sensor 3 in °C (float)
        temp3 = VALUE_FROM_BMS
        self.to_temp(3, temp3)

        # temperature sensor 4 in °C (float)
        temp4 = VALUE_FROM_BMS
        self.to_temp(4, temp4)

        # temperature sensor MOSFET in °C (float)
        temp_mos = VALUE_FROM_BMS
        self.to_temp(0, temp_mos)

        # status of the battery if balancing is enabled (bool)
        self.balance_fet = VALUE_FROM_BMS

        # PROTECTION values
        # 2 = alarm, 1 = warningm 0 = ok
        # high battery voltage alarm (int)
        self.protection.high_voltage = VALUE_FROM_BMS

        # high cell voltage alarm (int)
        self.protection.high_cell_voltage = VALUE_FROM_BMS

        # low battery voltage alarm (int)
        self.protection.low_voltage = VALUE_FROM_BMS

        # low cell voltage alarm (int)
        self.protection.low_cell_voltage = VALUE_FROM_BMS

        # low SOC alarm (int)
        self.protection.low_soc = VALUE_FROM_BMS

        # high charge current alarm (int)
        self.protection.high_charge_current = VALUE_FROM_BMS

        # high discharge current alarm (int)
        self.protection.high_discharge_current = VALUE_FROM_BMS

        # cell imbalance alarm (int)
        self.protection.cell_imbalance = VALUE_FROM_BMS

        # internal failure alarm (int)
        self.protection.internal_failure = VALUE_FROM_BMS

        # high charge temperature alarm (int)
        self.protection.high_charge_temp = VALUE_FROM_BMS

        # low charge temperature alarm (int)
        self.protection.low_charge_temp = VALUE_FROM_BMS

        # high temperature alarm (int)
        self.protection.high_temperature = VALUE_FROM_BMS

        # low temperature alarm (int)
        self.protection.low_temperature = VALUE_FROM_BMS

        # high internal temperature alarm (int)
        self.protection.high_internal_temp = VALUE_FROM_BMS

        # fuse blown alarm (int)
        self.protection.fuse_blown = VALUE_FROM_BMS

        # HISTORY values
        # Deepest discharge in Ampere hours (float)
        self.history.deepest_discharge = VALUE_FROM_BMS

        # Last discharge in Ampere hours (float)
        self.history.last_discharge = VALUE_FROM_BMS

        # Average discharge in Ampere hours (float)
        self.history.average_discharge = VALUE_FROM_BMS

        # Number of charge cycles (int)
        self.history.charge_cycles = VALUE_FROM_BMS

        # Number of full discharges (int)
        self.history.full_discharges = VALUE_FROM_BMS

        # Total Ah drawn (lifetime) (float)
        self.history.total_ah_drawn = VALUE_FROM_BMS

        # Minimum voltage in Volts (lifetime) (float)
        self.history.minimum_voltage = VALUE_FROM_BMS

        # Maximum voltage in Volts (lifetime) (float)
        self.history.maximum_voltage = VALUE_FROM_BMS

        # Minimum cell voltage in Volts (lifetime) (float)
        self.history.minimum_cell_voltage = VALUE_FROM_BMS

        # Maximum cell voltage in Volts (lifetime) (float)
        self.history.maximum_cell_voltage = VALUE_FROM_BMS

        # Time since last full charge in seconds (int)
        self.history.time_since_last_full_charge = VALUE_FROM_BMS

        # Number of low voltage alarms (int)
        self.history.low_voltage_alarms = VALUE_FROM_BMS

        # Number of high voltage alarms (int)
        self.history.high_voltage_alarms = VALUE_FROM_BMS

        # Minimum temperature in Celsius (lifetime)
        self.history.minimum_temperature = VALUE_FROM_BMS

        # Maximum temperature in Celsius (lifetime)
        self.history.maximum_temperature = VALUE_FROM_BMS

        # Discharged energy in kilo Watt hours (int)
        self.history.discharged_energy = VALUE_FROM_BMS

        # Charged energy in kilo Watt hours (int)
        self.history.charged_energy = VALUE_FROM_BMS
        """

        logger.info(self.hardware_version)
        return True

    def read_cell_data(self):
        # read the cell data
        cell_data = self.read_serial_data_template(self.command_cells)

        # check if connection was successful
        if cell_data is False:
            return False

        # MANDATORY values to set
        """
        # set voltage of each cell in volts (float)
        for c in range(self.cell_count):
            self.cells[c].voltage = VALUE_FROM_BMS
        """

        # OPTIONAL values to set
        """
        # set balance status of each cell, if available
        for c in range(self.cell_count):
            # balance status of the cell (bool)
            self.cells[c].balance = VALUE_FROM_BMS


        # set balance status, if only a common balance status is available (bool)
        # not needed, if balance status is available for each cell
        self.balancing: bool = VALUE_FROM_BMS
        if self.get_min_cell() is not None and self.get_max_cell() is not None:
            for c in range(self.cell_count):
                if self.balancing and (
                    self.get_min_cell() == c or self.get_max_cell() == c
                ):
                    self.cells[c].balance = True
                else:
                    self.cells[c].balance = False
        """

        return True

    def read_serial_data_template(self, command):
        # use the read_serial_data() function to read the data and then do BMS spesific checks (crc, start bytes, etc)
        data = read_serial_data(command, self.port, self.baud_rate, self.LENGTH_POS, self.LENGTH_CHECK)
        if data is False:
            logger.error(">>> ERROR: No reply - returning")
            return False

        start, flag, command_ret, length = unpack_from("BBBB", data)
        checksum = sum(data[:-1]) & 0xFF

        if start == 165 and length == 8 and checksum == data[12]:
            return data[4 : length + 4]
        else:
            logger.error(">>> ERROR: Incorrect Reply")
            return False
