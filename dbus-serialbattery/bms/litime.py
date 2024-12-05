# -*- coding: utf-8 -*-
from battery import Battery, Cell
from utils import logger
import utils
from bms.syncron_ble import Syncron_Ble
from struct import unpack_from
import time

import sys

class LiTime_Ble(Battery):
    def __init__(self, port, baud, address):
        super(LiTime_Ble, self).__init__(port, baud, address)
        self.type = self.BATTERYTYPE
        self.address = address
        self.poll_interval = 2000

    BATTERYTYPE = "LiTime"

    query_battery_status = bytes([0x00, 0x00, 0x04, 0x01, 0x13, 0x55, 0xAA, 0x17])
    ble_handle = None

    last_remian_ah = 0
    last_remian_ah_time = 0
    last_remian_ah_initiation = 0
    current_based_on_remaning = 0
    last_few_currents = []


    def test_connection(self):
        """
        call a function that will connect to the battery, send a command and retrieve the result.
        The result or call should be unique to this BMS. Battery name or version, etc.
        Return True if success, False for failure
        """
        logger.info("test_connection")
        self.ble_handle = Syncron_Ble(self.address, read_characteristic = "0000ffe1-0000-1000-8000-00805f9b34fb", write_characteristic = "0000ffe2-0000-1000-8000-00805f9b34fb")
        self.request_and_proccess_battery_staus()
        self.get_settings()

        return True

    def unique_identifier(self) -> str:
        return self.address

    def connection_name(self) -> str:
      return "BLE " + self.address

    def custom_name(self) -> str:
        return "Bat: " + self.type + " " + self.address[-5:]

    def parse_status(self, data):
        measured_total_voltage, cells_added_together_voltage = unpack_from("II", data, 8)
        measured_total_voltage /= 1000
        cells_added_together_voltage /= 1000

        heat, balance_memory_active, protection_state, failure_state, is_balancing, battery_state, SOC, SOH, discharges_count, discharges_amph_count = unpack_from("IIIIIHHIII", data, 68)

        nr_of_cells = 0
        cellv_str = ""
        for byte_pos in range(16, 48, 2):
            cell_volt, = unpack_from("H", data, byte_pos)
            if cell_volt != 0:
                if len(self.cells) >= nr_of_cells:
                    self.cells.append(Cell(False))
                cell_volt = cell_volt/1000
                self.cells[nr_of_cells].voltage = cell_volt
                self.cells[nr_of_cells].balance = (is_balancing & pow(2, nr_of_cells)) != 0
                cellv_str += str(cell_volt)+","
                nr_of_cells += 1

        self.cell_count = nr_of_cells

        current, cell_temp, mosfet_temp, unknown_temp, not_known1, not_known2, remaining_amph, full_charge_capacity_amph, not_known3 = unpack_from("ihhhHHHHH", data, 48)

        #current sensor is very inaccurate
        current = current/1000

        remaining_amph /= 100
        full_charge_capacity_amph /= 100

        #Debug data
        #print(f"current: {current}, cell_temp: {cell_temp}, mosfet_temp: {mosfet_temp}, unknown_temp: {unknown_temp}, not_known1: {not_known1}, not_known2: {not_known2}")
        #print(f"remaining_amph: {remaining_amph}, full_charge_capacity_amph: {full_charge_capacity_amph}, not_known3: {not_known3}")
        #print(f"heat: {heat}, b_m_a: {balance_memory_active}, protection_state: {protection_state}, failure_state: {failure_state}, is_balancing: {is_balancing}, battery_state: {battery_state}, SOC: {SOC}, SOH: {SOH}, discharges_count: {discharges_count}, discharges_amph_count: {discharges_amph_count}")

        self.capacity = full_charge_capacity_amph
        self.voltage = measured_total_voltage
        self.soc = SOC

        if is_balancing != 0:
             self.balance_fet = True
        else:
             self.balance_fet = False

        #Debug data
        #f = open("/data/charge_log.txt", "a")
        #timestr = time.ctime()
        #f.write(f"timestr: {timestr} curr: {current}, nk1: {not_known1}, nk2: {not_known2}, n3: {not_known3},  SOC: {SOC}, tot_v: {measured_total_voltage}, add_v: {cells_added_together_voltage}, protect_state: {protection_state}, fail_state: {failure_state}, is_bal: {bin(is_balancing)}, bat_st: {battery_state}, heat: {heat}, b_m_a: {balance_memory_active}, rem_ah: {remaining_amph} {cellv_str}\n")
        #f.close()

        #Due to the fact that the current reading is very inacurare we try to calculate current draw from remaining_amph
        current_based_on_remaning = 0
        if self.last_remian_ah == 0:
            self.current = 0
            self.last_remian_ah = remaining_amph
            self.last_remian_ah_time = time.time()

        now_time = time.time()
        time_since_last_update = int(now_time - self.last_remian_ah_time)
        if self.last_remian_ah != remaining_amph:
            last_remian_ah_time_diff = float(now_time - self.last_remian_ah_time)/3600
            last_remian_ah_change_diff = remaining_amph - self.last_remian_ah
            self.last_remian_ah = remaining_amph
            self.last_remian_ah_time = now_time
            if self.last_remian_ah_initiation == 0:#since we dont know how long the last reasing has been active we need to wait for another reading
                self.last_remian_ah_initiation = 1
            else:
                self.current_based_on_remaning = last_remian_ah_change_diff/last_remian_ah_time_diff
                self.last_remian_ah_initiation = 2

        #Calculate average current over last 5 messurments due to sensor inacuracy
        self.last_few_currents.append(current)
        if len(self.last_few_currents) > 5:
            self.last_few_currents.pop(0)

        last_few_avg = sum(self.last_few_currents)/len(self.last_few_currents)

        Use_Reason = ""
        #if last update was long ago we use the current reported by the bms despite it beeing unstable, we also use the current from the BMS if there is a very large discrepency betwen them
        if time_since_last_update > 25:
            self.current = last_few_avg
            Use_Reason = "curr: over 120s since last remaining_amph update"

        elif self.last_remian_ah_initiation != 2:
            self.current = last_few_avg
            Use_Reason = "curr: last_remian_ah not initiated with base values"

        elif time_since_last_update > 5 and (self.current_based_on_remaning + 3 < self.current or self.current_based_on_remaning - 3 > self.current):
            self.current = last_few_avg
            Use_Reason = "curr: Large differances betwen base and curr despite recent base update"

        else:
            self.current = self.current_based_on_remaning
            Use_Reason = "base"

        #Debug data
        #logger.info(f"{Use_Reason}, current:{current:.3f}, last_few_avg: {last_few_avg:.3f}, base: {self.current_based_on_remaning:.3f}")


        # status of the battery if charging is enabled (bool)
        self.charge_fet = True
        if battery_state == 4:
            self.charge_fet = False

        # status of the battery if discharging is enabled (bool) (there might be other values of heat or battery_state that could indicate that discharge is disabled)
        self.discharge_fet = True
        if heat == 0x80 or protection_state in (0x20, 0x80):
            self.discharge_fet = False

        # temperature sensor 1 in °C (float)
        temp1 = cell_temp
        self.to_temp(1, temp1)

        # temperature sensor 2 in °C (float)
        temp2 = unknown_temp
        self.to_temp(2, temp2)

        # temperature sensor MOSFET in °C (float)
        temp_mos = mosfet_temp
        self.to_temp(0, temp_mos)

        self.capacity_remaining = remaining_amph
        self.history.total_ah_drawn = discharges_amph_count
        self.history.full_discharges = discharges_count

    def get_settings(self):

        self.max_battery_voltage = utils.MAX_CELL_VOLTAGE * self.cell_count
        self.min_battery_voltage = utils.MIN_CELL_VOLTAGE * self.cell_count
        return True

    def request_and_proccess_battery_staus(self):
        #logger.info("requesting battery status")
        data = self.ble_handle.send_data(self.query_battery_status)
        self.parse_status(data)

    def refresh_data(self):
        """
        This is called each time the library wants data (1 second)
        """

        self.request_and_proccess_battery_staus()

        return True
