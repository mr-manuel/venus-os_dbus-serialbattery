# -*- coding: utf-8 -*-

# NOTES
# Added by https://github.com/rogergrant99

# TODO
# 


from __future__ import absolute_import, division, print_function, unicode_literals
from battery import Battery, Cell
from utils import bytearray_to_string, logger
from struct import unpack_from
from time import sleep, time
import sys


class RV_C_Can(Battery):
    def __init__(self, port, baud, address):
        super(RV_C_Can, self).__init__(port, baud, address)
        self.cell_count = 0
        self.type = self.BATTERYTYPE
        self.history.exclude_values_to_calculate = ["charge_cycles", "total_ah_drawn"]

        # If multiple BMS are used simultaneously, the device address can be set via the dip switches on the BMS
        # (default address is 0, all switches down) to change the CAN frame ID sent by the BMS
        self.device_address = int.from_bytes(address, byteorder="big") if address is not None else 0
        self.last_error_time = 0
        self.error_active = False
        self.protocol_version = None

    BATTERYTYPE = "RV-C CAN"

    BATT_STAT1 = "BATT_STAT1"
    BATT_STAT2 = "BATT_STAT2"
    BATT_STAT3 = "BATT_STAT3"
    BATT_STAT4 = "BATT_STAT4"
    BATT_STAT6 = "BATT_STAT6"
    BATT_STAT11 = "BATT_STAT11"

    CAN_FRAMES = {
        BATT_STAT1: [0x19FFFD8F],
        BATT_STAT2: [0x19FFFC8F],
        BATT_STAT3: [0x19FFFB8F],
        BATT_STAT4: [0x19FEC98F],
        BATT_STAT6: [0x19FEC78F],
        BATT_STAT11: [0x19FEA58F],
    }

    def connection_name(self) -> str:
        return f"CAN socketcan:{self.port}" + (f"__{self.device_address}" if self.device_address != 0 else "")

    def unique_identifier(self) -> str:
        """
        Used to identify a BMS when multiple BMS are connected
        Provide a unique identifier from the BMS to identify a BMS, if multiple same BMS are connected
        e.g. the serial number
        If there is no such value, please remove this function
        """
        return self.port + ("__" + bytearray_to_string(self.address).replace("\\", "0") if self.address is not None else "")

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
        return True

    def refresh_data(self):
        # call all functions that will refresh the battery data.
        # This will be called for every iteration (1 second)
        # Return True if success, False for failure
        result = self.read_rv_c_can()
        # check if connection success
        if result is False:
            return False

        return True

    def to_protection_bits(self, byte_data):
        tmp = bin(byte_data | 0xFF00000000)
        # High volts D2 bit 1
        self.protection.high_voltage = 2 if int(tmp[16:17]) > 0 else 0
        # Low volts D2 bit 5
        self.protection.low_voltage = 2 if int(tmp[12:13]) > 0 else 0
        # Low SOC D3 bit 1
        self.protection.low_soc = 2 if int(tmp[24:25]) > 0 else 0
        # LowTemp D3 bit 5
        self.protection.low_temperature = 2 if int(tmp[20:21]) > 0 else 0
        # OverTemp D4 bit 1
        self.protection.high_temperature = 2 if int(tmp[32:33]) > 0 else 0
        # OverCurrent D4 bit 5
        self.protection.high_discharge_current = 2 if int(tmp[28:29]) > 0 else 0
        self.protection.high_charge_current = 2 if int(tmp[28:29]) > 0 else 0

    def reset_protection_bits(self):
        self.protection.high_cell_voltage = 0
        self.protection.low_cell_voltage = 0
        self.protection.high_voltage = 0
        self.protection.low_voltage = 0
        self.protection.cell_imbalance = 0
        self.protection.high_discharge_current = 0
        self.protection.high_charge_current = 0

        # there is just a BMS and Battery temperature_ alarm (not for charge and discharge)
        self.protection.high_charge_temperature = 0
        self.protection.high_temperature = 0
        self.protection.low_charge_temperature = 0
        self.protection.low_temperature = 0
        self.protection.high_charge_temperature = 0
        self.protection.high_temperature = 0
        self.protection.low_soc = 0
        self.protection.internal_failure = 0
        self.protection.internal_failure = 0
        self.protection.internal_failure = 0
        self.protection.internal_failure = 0

    def update_cell_voltages(self, start_index, end_index, data):
        for i in range(start_index, end_index + 1):
            cell_voltage = unpack_from("<H", bytes([data[2], data[3]]))[0] / 80
            if cell_voltage > 0:
                if len(self.cells) <= i:
                    self.cells.insert(i, Cell(False))
                    self.cell_count = len(self.cells)
                self.cells[i].voltage = cell_voltage
        self.voltage = self.get_cell_voltage_sum()

    def read_rv_c_can(self):
        # reset errors after timeout
        if ((time() - self.last_error_time) > 120.0) and self.error_active is True:
            self.error_active = False
            self.reset_protection_bits()

        # check if all needed data is available
        data_check = 0

        for frame_id, data in self.can_transport_interface.can_message_cache_callback().items():
            normalized_arbitration_id = frame_id + self.device_address

            # BATT_STAT1 Voltage
            if normalized_arbitration_id in self.CAN_FRAMES[self.BATT_STAT1]:
                self.update_cell_voltages(0, 3, data)
                current = unpack_from("<L", bytes([data[4], data[5], data[6], data[7] ]))[0] 
                self.current = (2000000000 - current) / 1000
                # check if all needed data is available
                data_check += 2

            # BATT_STAT2 SOC and Temp
            elif normalized_arbitration_id in self.CAN_FRAMES[self.BATT_STAT2]:
                soc = unpack_from("<B", bytes([data[4]]))[0]
                self.soc = soc / 2
                temperature_1 = unpack_from("<H", bytes([data[2], data[3]]))[0]
                temp = (temperature_1 * 0.03125) - 273
                self.to_temperature(1, temp)
                # check if all needed data is available
                data_check += 2

            # BATT_STAT3 Capacity Remaining and State of Health
            elif normalized_arbitration_id in self.CAN_FRAMES[self.BATT_STAT3]:
                self.capacity_remain = unpack_from("<H", bytes([data[3], data[4]]))[0]
                self.soh = unpack_from("<B", bytes([data[2]]))[0] / 2
                # check if all needed data is available
                data_check += 2

            # BATT_STAT4 Target charge current and voltage
            elif normalized_arbitration_id in self.CAN_FRAMES[self.BATT_STAT4]:
                self.max_battery_voltage = unpack_from("<H", bytes([data[3], data[4]]))[0] / 20
                self.max_battery_charge_current = unpack_from("<H", bytes([data[5], data[6]]))[0] / 100

                # check if all needed data is available
                data_check += 4

            # BATT_STAT6 Alarms
            elif normalized_arbitration_id in self.CAN_FRAMES[self.BATT_STAT6]:
                alarms = unpack_from(
                    "<L",
                    bytes([data[0], data[4], data[3], data[2]]),
                )[0]
                self.last_error_time = time()
                self.error_active = True
                self.to_protection_bits(alarms)

                # check if all needed data is available
                data_check += 4

            # BATT_STAT11 Capacity and MOSFET state
            elif normalized_arbitration_id in self.CAN_FRAMES[self.BATT_STAT11]:
                self.capacity = unpack_from("<H", bytes([data[3], data[4]]))[0]
                fet = unpack_from("<B", bytes([data[2]]))[0]
                self.charge_fet = 1 if int(bin(fet | 0x100)[8:9]) > 0 else 0
                self.discharge_fet = 1 if int(bin(fet | 0x100)[10:11]) > 0 else 0
                self.control_allow_discharge = self.charge_fet
                self.control_allow_charge = self.discharge_fet
                # check if all needed data is available
                data_check += 2

        # check if all needed data is available
        if data_check == 0:
            logger.error(">>> ERROR: No reply - returning")
            return False

        # check if all needed data is available, else wait shortly and proceed with next iteration
        if data_check < 16:
            logger.debug(">>> INFO: Not all data available yet - waiting for next iteration")
            sleep(1)
            return True
        self.hardware_version = "RV-C CAN" + ("V1" + str(self.cell_count) + "S" if self.protocol_version == 2 else "")
        return True
