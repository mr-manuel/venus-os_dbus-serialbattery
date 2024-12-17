# -*- coding: utf-8 -*-

# NOTES
# This part is maintained by https://github.com/MacGH23

import sys
import traceback
from time import time
from utils import logger
import utils


class DbusHelper:
    """
    This class is used to handle all the BMS communication. For easier comparision it still named dbushelper
    """

    EMPTY_DICT = {}

    def __init__(self, battery, bms_address=None):
        self.battery = battery
        self.bms_address = bms_address
        self.instance = 1
        self.settings = None
        self.error = {"count": 0, "timestamp_first": None, "timestamp_last": None}
        self.cell_voltages_good = None
        self.path_battery = None
        self.save_charge_details_last = {
            "allow_max_voltage": self.battery.allow_max_voltage,
            "max_voltage_start_time": self.battery.max_voltage_start_time,
            "soc_reset_last_reached": self.battery.soc_reset_last_reached,
            "soc_calc": (self.battery.soc_calc if self.battery.soc_calc is not None else ""),
        }

    def publish_battery(self, loop):
        # This is called every battery.poll_interval milli second as set up per battery type to read and update the data
        try:
            # Call the battery's refresh_data function
            result = self.battery.refresh_data()
            if result:
                # reset error variables
                self.error["count"] = 0
                self.battery.online = True
                self.battery.connection_info = "Connected"

                # unblock charge/discharge, if it was blocked when battery went offline
                if utils.BLOCK_ON_DISCONNECT:
                    self.battery.block_because_disconnect = False

                # reset cell voltages good
                if self.cell_voltages_good is not None:
                    self.cell_voltages_good = None

            else:
                # update error variables
                if self.error["count"] == 0:
                    self.error["timestamp_first"] = int(time())

                self.error["timestamp_last"] = int(time())
                self.error["count"] += 1

        except Exception:
            traceback.print_exc()

    def Log_Data(self):
        # Update SOC, DC and System items
        print("yes")
        logger.debug("cell_count:" + str(self.battery.cell_count))
        logger.debug("soc       :" + str(round(self.battery.soc, 2)))
        logger.debug("Voltage:   " + str(round(self.battery.voltage, 2)))
        logger.debug("current:   " + str(round(self.battery.current, 2)))
        logger.debug("GetTemp:   " + str(self.battery.get_temp()))
        #        logger.debug("Caprema:   " + str(self.battery.get_capacity_remain()))
        logger.debug("capacity:  " + str(self.battery.capacity))
        #        midpoint, deviation = self.battery.get_midvoltage()
        #        logger.debug("midpoint:  " + str(midpoint))
        #        logger.debug("deviation: " + str(deviation))

        # Update battery extras
        #        logger.debug("deviation: " + str(self.battery.cycles))
        #        logger.debug("totaldrw : " + str(self.battery.total_ah_drawn))
        #        logger.debug("online:    " + str(self.battery.online))
        #        logger.debug("mintemp:   " + str(self.battery.get_min_temp()))
        #        logger.debug("maxtemp:   " + str(self.battery.get_max_temp()))
        logger.debug("mos_temp:  " + str(self.battery.temp_mos))
        logger.debug("temp1:     " + str(self.battery.temp1))
        logger.debug("temp2:     " + str(self.battery.temp2))
        logger.debug("temp3:     " + str(self.battery.temp3))
        logger.debug("temp4:     " + str(self.battery.temp4))

        # Updates from cells
        #        logger.debug("min_cell_desc:   " + str(self.battery.get_min_cell_desc()))
        #        logger.debug("max_cell_desc:   " + str(self.battery.get_max_cell_desc()))
        #        logger.debug("min_cell_voltage:" + str(self.battery.get_min_cell_voltage()))
        #        logger.debug("max_cell_voltage:" + str(self.battery.get_max_cell_voltage()))
        #        logger.debug("balancing:       " + str(self.battery.get_balancing()))

        # Update the alarms
        logger.debug("voltage_low:     " + str(self.battery.protection.voltage_low))
        logger.debug("voltage_cell_low:" + str(self.battery.protection.voltage_cell_low))
        logger.debug("voltage_high:    " + str(self.battery.protection.voltage_high))
        logger.debug("soc_low:         " + str(self.battery.protection.soc_low))
        logger.debug("current_over:    " + str(self.battery.protection.current_over))
        logger.debug("current_under:   " + str(self.battery.protection.current_under))
        logger.debug("cell_imbalance:  " + str(self.battery.protection.cell_imbalance))
        logger.debug("internal_failure:" + str(self.battery.protection.internal_failure))
        logger.debug("temp_high_charge:" + str(self.battery.protection.temp_high_charge))
        logger.debug("temp_low_charge: " + str(self.battery.protection.temp_low_charge))
        logger.debug("temp_low_discharge:" + str(self.battery.protection.temp_low_discharge))
        logger.debug("block_because_disconnect:" + str(self.battery.block_because_disconnect))
        logger.debug("temp_high_internal:" + str(self.battery.protection.temp_high_internal))

        # cell voltages
        if utils.BATTERY_CELL_DATA_FORMAT > 0:
            try:
                voltage_sum = 0
                for i in range(self.battery.cell_count):
                    voltage = self.battery.get_cell_voltage(i)
                    logger.debug("Cell Voltage " + str(i) + " : " + str(round(voltage, 2)))
                    if utils.BATTERY_CELL_DATA_FORMAT & 1:
                        logger.debug("Balance:" + str(self.battery.get_cell_balancing(i)))
                    if voltage:
                        voltage_sum += voltage
                logger.debug("Voltage Sum:" + str(voltage_sum))

            except Exception:
                exception_type, exception_object, exception_traceback = sys.exc_info()
                file = exception_traceback.tb_frame.f_code.co_filename
                line = exception_traceback.tb_lineno
                logger.error("Non blocking exception occurred: " + f"{repr(exception_object)} of type {exception_type} in {file} line #{line}")
                pass

                logger.debug(str(self.battery.current_avg))

        if self.battery.soc is not None:
            logger.debug("logged to dbus [%s]" % str(round(self.battery.soc, 2)))
            self.battery.log_cell_data()
