# -*- coding: utf-8 -*-

# NOTES
# Victron CAN protocol support for JBD BMS.
# This is quite similar to Pylon CAN protocol, so maybe in the future this file can be extended to support both.
#
# Tested with JBD UP16S015:
# - Change CAN protocol in the BMS settings to "Victron"
# - Depending on your BMS model, these instructions might be applicable, explaining how to chain the BMSs and set the DIP switches:
#   https://cdn.shopify.com/s/files/1/0253/9752/6580/files/48V100AH_-24-08-21-min.pdf?v=1728522535
# - Use Victron Type A cable to connect CAN1 port on the BMS to Cerbo (regular ethernet cable won't work!):
#   https://www.victronenergy.com/live/battery_compatibility:can-bus_bms-cable
# - In Cerbo settings -> Connectivity set the CAN port profile to "CAN-bus BMS LV (500 kbit/s)"

from __future__ import absolute_import, division, print_function, unicode_literals
from battery import Battery, Cell
from utils import (
    get_connection_error_message,
    logger,
)
from struct import unpack_from
from time import sleep
import sys


class LltJbd_Can(Battery):
    def __init__(self, port, baud, address):
        super(LltJbd_Can, self).__init__(port, baud, address)
        self.cell_count = 0
        self.type = self.BATTERYTYPE
        self.history.exclude_values_to_calculate = ["charge_cycles"]

        # Storage for multi-part messages
        self.bms_model_part1 = None
        self.bms_model_part2 = None
        self.bms_serial_part1 = None
        self.bms_serial_part2 = None

    BATTERYTYPE = "LLT/JBD"

    # CAN frame identifiers
    INVERTER_REPLY = "INVERTER_REPLY"
    INVERTER_ID = "INVERTER_ID"
    DVCC_INSTRUCTIONS = "DVCC_INSTRUCTIONS"
    SOC_SOH = "SOC_SOH"
    VOLTAGE_CURRENT_TEMP = "VOLTAGE_CURRENT_TEMP"
    ALARMS_WARNINGS = "ALARMS_WARNINGS"
    MANUFACTURER = "MANUFACTURER"
    BATTERY_INFO = "BATTERY_INFO"
    BMS_MODEL_1 = "BMS_MODEL_1"
    BMS_MODEL_2 = "BMS_MODEL_2"
    PACKS_ONLINE = "PACKS_ONLINE"
    CELL_VOLTAGE_RANGE = "CELL_VOLTAGE_RANGE"
    MIN_VOLTAGE_CELL_ID = "MIN_VOLTAGE_CELL_ID"
    MAX_VOLTAGE_CELL_ID = "MAX_VOLTAGE_CELL_ID"
    MIN_TEMP_CELL_ID = "MIN_TEMP_CELL_ID"
    MAX_TEMP_CELL_ID = "MAX_TEMP_CELL_ID"
    ENERGY_CHARGED_DISCHARGED = "ENERGY_CHARGED_DISCHARGED"
    CAPACITY = "CAPACITY"
    SERIAL_1 = "SERIAL_1"
    SERIAL_2 = "SERIAL_2"
    PRODUCT_ID = "PRODUCT_ID"

    CAN_FRAMES = {
        INVERTER_REPLY: [0x305],
        INVERTER_ID: [0x307],
        DVCC_INSTRUCTIONS: [0x351],
        SOC_SOH: [0x355],
        VOLTAGE_CURRENT_TEMP: [0x356],
        ALARMS_WARNINGS: [0x35A],
        MANUFACTURER: [0x35E],
        BATTERY_INFO: [0x35F],
        BMS_MODEL_1: [0x370],
        BMS_MODEL_2: [0x371],
        PACKS_ONLINE: [0x372],
        CELL_VOLTAGE_RANGE: [0x373],
        # Cell IDs are in format "ID:01.01" where the first number is the pack number and the second number is the cell in the pack.
        # At least on some BMS firmwares JBD implemented number conversion incorrectly, so cell numbers overflow to characters past "9" in the ASCII table.
        # Cells 10-15 have IDs from ID:01.0: to ID:01.0?, and cell 16 confusingly shows up as ID:01.10
        MIN_VOLTAGE_CELL_ID: [0x374],
        MAX_VOLTAGE_CELL_ID: [0x375],
        MIN_TEMP_CELL_ID: [0x376],
        MAX_TEMP_CELL_ID: [0x377],
        ENERGY_CHARGED_DISCHARGED: [0x378],  # Returns all 0.
        # JBD BMS appears to take only the capacity of the master battery pack and multiply it by the number of the packs regardless of the actual capacity of
        # the other packs.
        CAPACITY: [0x379],
        # JBD BMS by default returns a dummy non-unique value in 0x380 and 0x381 frames, but it can be reprogrammed in the BMS software.
        SERIAL_1: [0x380],
        SERIAL_2: [0x381],
        PRODUCT_ID: [0x382],
    }

    # Constants to track when we received all essential data
    DATA_CHECK_SOC = 1
    DATA_CHECK_VOLTAGE_CURRENT_TEMP = 2
    DATA_CHECK_CAPACITY = 4
    DATA_CHECK_CELL_VOLTAGES = 8
    DATA_CHECK_MAX = 16

    # Protection constants
    PROTECTION_OK = 0
    PROTECTION_WARNING = 1
    PROTECTION_ALARM = 2

    def connection_name(self) -> str:
        return f"CAN socketcan:{self.port}"

    def test_connection(self):
        """
        Test connection to the battery by attempting to read data.
        Return True if success, False for failure.
        """
        result = False
        try:
            result = self.get_settings()
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
        This method is here for completeness, but when JBD BMSs are chained, on CAN only the master BMS is visible, and it reports the aggregate values from
        all BMSs.
        """

        # Fall back to the default unique_identifier implementation when serial number has the default dummy value.
        if self.serial_number is None or self.serial_number == "JBD87654321":
            return super(LltJbd_Can, self)

        return self.serial_number

    def get_settings(self):
        """
        Get initial settings from the BMS.
        This is called once after successful connection.
        """
        # JBD BMS doesn't require initial setup commands, it broadcasts all data

        self.charge_fet = True
        self.discharge_fet = True
        return True

    def refresh_data(self):
        """
        Refresh battery data by reading CAN frames.
        Called every iteration (1 second).
        """
        result = self.read_jbd_can()

        if result is False:
            return False

        return True

    def bytes_to_string(self, data):
        """Convert bytes to string, stripping null bytes"""
        return data.rstrip(b"\x00").decode("ascii", errors="ignore")

    def convert_protection_value(self, data, byte_offset, bit_index):
        # Check for alarm state
        if (data[byte_offset] & (1 << bit_index)) != 0:
            return self.PROTECTION_ALARM
        # Check for warning state. Warnings have the same bit structure, just 4 bytes later.
        if (data[byte_offset + 4] & (1 << bit_index)) != 0:
            return self.PROTECTION_WARNING
        return self.PROTECTION_OK

    def to_protection_bits(self, data):
        """
        Parse alarm and warning data from frame 0x35A.
        TODO: This code is unverified!
        Source: https://www.genetrysolar.com/wp-content/uploads/wpforo/default_attachments/IPB/s3_g308908/monthly_2023_02/1016944466_can-bus_bms_protocol20210417_pdf.b32c1954d6145579b857d66191327e30 # noqa: E501
        """
        # TODO: verify whether high_cell_voltage and low_cell_voltage are actually for cell or overall battery voltage
        high_cell_voltage = self.convert_protection_value(data, 0, 2)
        low_cell_voltage = self.convert_protection_value(data, 0, 4)
        high_temperature = self.convert_protection_value(data, 0, 6)
        low_temperature = self.convert_protection_value(data, 1, 0)
        high_charge_temperature = self.convert_protection_value(data, 1, 2)
        low_charge_temperature = self.convert_protection_value(data, 1, 4)
        high_discharge_current = self.convert_protection_value(data, 1, 6)
        high_charge_current = self.convert_protection_value(data, 2, 0)
        short_circuit = self.convert_protection_value(data, 2, 4)
        internal_fault = self.convert_protection_value(data, 2, 6)
        cell_imbalance = self.convert_protection_value(data, 3, 0)

        self.protection.high_cell_voltage = high_cell_voltage
        self.protection.low_cell_voltage = low_cell_voltage
        self.protection.cell_imbalance = cell_imbalance
        self.protection.high_discharge_current = max(high_discharge_current, short_circuit)
        self.protection.high_charge_current = high_charge_current
        self.protection.high_charge_temperature = high_charge_temperature
        self.protection.high_temperature = high_temperature
        self.protection.low_charge_temperature = low_charge_temperature
        self.protection.low_temperature = low_temperature
        self.protection.internal_failure = internal_fault

    def read_jbd_can(self):
        """Read and parse all CAN frames from JBD BMS"""

        # Track which data we've received
        data_check = 0

        for frame_id, data in self.can_transport_interface.can_message_cache_callback().items():

            # 0x351: BMS DVCC Instructions
            if frame_id in self.CAN_FRAMES[self.DVCC_INSTRUCTIONS]:
                charge_voltage = unpack_from("<H", data, 0)[0] / 10
                charge_current_limit = unpack_from("<H", data, 2)[0] / 10
                discharge_current_limit = unpack_from("<H", data, 4)[0] / 10
                discharge_voltage = unpack_from("<H", data, 6)[0] / 10

                self.max_battery_charge_current = charge_current_limit
                self.max_battery_discharge_current = discharge_current_limit
                self.max_battery_voltage = charge_voltage
                self.min_battery_voltage = discharge_voltage

            # 0x355: SOC and SOH
            elif frame_id in self.CAN_FRAMES[self.SOC_SOH]:
                # soc = unpack_from("<H", data, 0)[0]
                soh = unpack_from("<H", data, 2)[0]
                soc_highres = unpack_from("<H", data, 4)[0] / 100

                self.soc = soc_highres
                self.soh = soh

                data_check |= self.DATA_CHECK_SOC

            # 0x356: Voltage, Current, Temperature, Cycles
            elif frame_id in self.CAN_FRAMES[self.VOLTAGE_CURRENT_TEMP]:
                voltage = unpack_from("<H", data, 0)[0] / 100
                current = unpack_from("<h", data, 2)[0] / 10  # signed
                temperature = unpack_from("<h", data, 4)[0] / 10  # signed
                cycles = unpack_from("<H", data, 6)[0]

                self.voltage = voltage
                self.current = current
                self.to_temperature(1, temperature)
                self.history.charge_cycles = cycles

                data_check |= self.DATA_CHECK_VOLTAGE_CURRENT_TEMP

            # 0x35A: Alarms and Warnings
            elif frame_id in self.CAN_FRAMES[self.ALARMS_WARNINGS]:
                self.to_protection_bits(data)

            # 0x35F: Battery Type, Firmware Version, Capacity, Product ID
            elif frame_id in self.CAN_FRAMES[self.BATTERY_INFO]:
                # battery_type = self.bytes_to_string(data[0:2])
                firmware_version = unpack_from("<H", data, 2)[0]
                capacity_ah = unpack_from("<H", data, 4)[0]
                # product_id = unpack_from("<H", data, 6)[0]

                # Capacity returned here is actually 0 on JBD UP16S015. Frame 0x379 has the non-zero capacity instead.
                if capacity_ah > 0:
                    self.capacity = capacity_ah
                    data_check |= self.DATA_CHECK_CAPACITY

                self.version = f"0x{firmware_version:04X}"

            # 0x370: BMS Model (Part 1)
            elif frame_id in self.CAN_FRAMES[self.BMS_MODEL_1]:
                self.bms_model_part1 = self.bytes_to_string(data)

            # 0x371: BMS Model (Part 2)
            elif frame_id in self.CAN_FRAMES[self.BMS_MODEL_2]:
                self.bms_model_part2 = self.bytes_to_string(data)
                if self.bms_model_part1:
                    full_model = self.bms_model_part1 + self.bms_model_part2
                    self.hardware_version = full_model

            # 0x373: Cell Voltage and Temperature Range
            elif frame_id in self.CAN_FRAMES[self.CELL_VOLTAGE_RANGE]:
                min_cell_v = unpack_from("<H", data, 0)[0] / 1000
                max_cell_v = unpack_from("<H", data, 2)[0] / 1000
                min_temp_k = unpack_from("<H", data, 4)[0]
                max_temp_k = unpack_from("<H", data, 6)[0]

                # Convert Kelvin to Celsius
                min_temp_c = min_temp_k - 273
                max_temp_c = max_temp_k - 273

                self.cell_min_voltage = min_cell_v
                self.cell_max_voltage = max_cell_v

                self.to_temperature(2, min_temp_c)
                self.to_temperature(3, max_temp_c)

                data_check |= self.DATA_CHECK_CELL_VOLTAGES

            # TODO: integrate this file with the rest of the system where needed, and change the BMS type in the config accordingly

            # 0x379: Capacity
            elif frame_id in self.CAN_FRAMES[self.CAPACITY]:
                capacity_ah = unpack_from("<H", data, 0)[0]
                if capacity_ah > 0:
                    self.capacity = capacity_ah
                    data_check |= self.DATA_CHECK_CAPACITY

            # 0x380: BMS Serial Number (Part 1)
            elif frame_id in self.CAN_FRAMES[self.SERIAL_1]:
                self.bms_serial_part1 = self.bytes_to_string(data)

            # 0x381: BMS Serial Number (Part 2)
            elif frame_id in self.CAN_FRAMES[self.SERIAL_2]:
                self.bms_serial_part2 = self.bytes_to_string(data)
                if self.bms_serial_part1:
                    self.serial = self.bms_serial_part1 + self.bms_serial_part2

        # Check if we received essential data
        if data_check == 0:
            get_connection_error_message(self.online)
            return False

        # Wait for more data if not all essential frames are received
        if data_check < self.DATA_CHECK_MAX - 1:
            logger.debug(">>> INFO: Not all data available yet - waiting for next iteration")
            sleep(1)
            return True

        if self.cell_min_voltage > 0 and self.cell_max_voltage > 0:
            avg_cell_voltage = (self.cell_min_voltage + self.cell_max_voltage) / 2

            # Estimate cell count from total voltage and average cell voltage if not yet determined
            if self.cell_count == 0 and self.voltage > 0:
                self.cell_count = int(round(self.voltage / avg_cell_voltage, 0))
                self.cells = [Cell(False) for _ in range(self.cell_count)]

            rounded_avg_cell_voltage = round(avg_cell_voltage, 3)
            for i in range(len(self.cells)):
                self.cells[i].voltage = rounded_avg_cell_voltage
            if len(self.cells) >= 2:
                self.cells[0].voltage = self.cell_min_voltage
                self.cells[1].voltage = self.cell_max_voltage

        # Set hardware version if not already set
        if self.hardware_version is None:
            self.hardware_version = f"LLT/JBD CAN {self.cell_count}S"

        return True
