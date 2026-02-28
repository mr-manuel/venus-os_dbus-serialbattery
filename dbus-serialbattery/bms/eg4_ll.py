# -*- coding: utf-8 -*-

# Notes
# Added by https://github.com/tuxntoast

import datetime
import serial
import struct
import sys
import time
import utils
from pprint import pformat
from time import sleep

from battery import Battery, Cell
from utils import logger

#    Author: Pfitz
#    Date: 31 Jan 2026
#    Features:
#     DBus-Serial Multi Battery Monitoring Support
#     Driver Error, Protect and Warning Alerting
#     Driver Balancing Monitoring
#     BMS Config Polling on Startup for Alert Values
#     Support for 12v/24v/48v BMS

# Driver Developed On:
# 2x Eg4 LL 12v 400 AH
# Venus OS v3.67 running on Cerbo GX - dbus-serialbattery v2.0.20250729
# first port of the BMS below it. BMS units can be "Daisy Chained" until your full bank is connected
# Update BATTERY_ADDRESSES in config.ini to define the BMS ID in your communication chain
# Example: BATTERY_ADDRESSES = 0x10, 0x01 would be to conect and report on BMS ID 16 and 1


class EG4_LL(Battery):
    def __init__(self, port, baud, address):
        super(EG4_LL, self).__init__(port, baud, address)
        self.has_settings = 0
        self.reset_soc = 0
        self.soc_to_set = None
        self.type = self.BATTERYTYPE
        self.runtime = 0  # TROUBLESHOOTING for no reply errors
        self.data = {}

    statuslogger = False  # Prints to STDOut After Each BMS Poll
    LoadBMSSettings = True  # Load BMS Config on Startup && Use Driver Based Alarms
    protectionLogger = True  # Print to STDOut when BMS raises an error
    crcchecksumlogger = False  # Print to stdout when the BMS Reply fails the CRC checksum

    battery_stats = {}
    serialTimeout = 2  # Serial Connection timeout

    BATTERYTYPE = "EG4-LL"

    hwCommandRoot = b"\x03\x00\x69\x00\x17"
    cellCommandRoot = b"\x03\x00\x00\x00\x27"
    bmsConfigCommandRoot = b"\x03\x00\x2d\x00\x5b"

    def unique_identifier(self):
        return self.serial_number

    def custom_name(self) -> str:
        return f"{self.BATTERYTYPE}:{self.Id}" if hasattr(self, "Id") else self.BATTERYTYPE

    def open_serial(self):
        ser = serial.Serial(
            self.port,
            baudrate=self.baud_rate,
            timeout=self.serialTimeout,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
        )
        if ser.isOpen():
            return ser
        else:
            return False

    def test_connection(self):
        try:
            self.battery_stats = {}
            self.Id = int.from_bytes(self.address, "big")
            self.ser = self.open_serial()
            logger.info(f"Waiting for BMS ID {self.Id} to initialize...")
            sleep(1.0)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            command = self.eg4CommandGen((self.Id.to_bytes(1, "big") + self.hwCommandRoot))
            reply = self.read_eg4ll_command(command)
            if reply is False:
                return False
            else:
                serial = reply[33:48].decode("utf-8") + str(self.Id)
                logger.error(f"Connected to BMS ID: {pformat(serial)}")
                self.serial_number = serial
                self.poll_interval = (self.serialTimeout * 1000) * 3
                self.custom_field = self.BATTERYTYPE + ":" + format(self.Id, "02d")
                cell_poll = self.read_battery_bank()
                if cell_poll is True:
                    return True
                else:
                    return False
        except Exception:
            (
                exception_type,
                exception_object,
                exception_traceback,
            ) = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
            return False

    def read_battery_bank(self) -> bool:
        cell_reply = self.read_cell_details(self.Id)
        if not cell_reply:
            return False
        bank_stats = self.battery_stats.get(self.Id)
        first_run = bank_stats is None
        protection_status = self.lookup_protection(cell_reply)
        cell_reply["protection"] = protection_status
        warning_status = self.lookup_warning(cell_reply)
        cell_reply["warning"] = warning_status
        error_status = self.lookup_error(cell_reply)
        cell_reply["error"] = error_status
        bms_status = self.lookup_status(cell_reply)
        cell_reply["status"] = bms_status
        heater_status = self.lookup_heater(cell_reply)
        cell_reply["heater_state"] = heater_status

        # First-time initialization → fetch static HW/BMS data once
        if first_run:
            if self.LoadBMSSettings is True:
                extra_reply = self.read_bms_config()
                if extra_reply is False:
                    self.LoadBMSSettings = False
                    extra_reply = self.read_hw_details(self.Id)
            else:
                extra_reply = self.read_hw_details(self.Id)
            if not extra_reply:
                return False
            else:
                bank_stats = {**extra_reply, **cell_reply}
                if self.LoadBMSSettings is True:
                    self.alarm_mgr = EG4AlarmManager(self.data, eg4ll_logger_cb=self.eg4ll_logger)

            self.cell_count = int(cell_reply["cell_count"])
            self.min_battery_voltage = utils.MIN_CELL_VOLTAGE * cell_reply["cell_count"]
            self.max_battery_voltage = utils.MAX_CELL_VOLTAGE * cell_reply["cell_count"]
            self.capacity = bank_stats["capacity"]
            self.serial_number = bank_stats["hw_serial"]
            self.version = bank_stats["hw_make"]
            self.hardware_version = bank_stats["hw_version"]
        else:
            # Battery already initialized → only update cell data
            bank_stats.update(cell_reply)
        # ---- Balancing state ----
        balancing_map = {0: "Off", 1: "Balancing", 2: "Finished"}
        code = self.balancingStat(bank_stats)
        bank_stats["balancing_code"] = code
        bank_stats["balancing_text"] = balancing_map.get(code, "UNKNOWN")
        self.reportBatteryBank(bank_stats)
        # Evaluate alarms
        alarm_status = {}
        if self.LoadBMSSettings is True:
            alarm_status = self.alarm_mgr.evaluate(new_data=bank_stats)
            # update_alarm_dbus must come before any logging so protection attributes
            # reflect the current alarm state when the logger reads them
            self.update_alarm_dbus(alarm_status)
            self.battery_stats[self.Id] = bank_stats = {**bank_stats, **alarm_status}
        else:
            self.battery_stats[self.Id] = bank_stats
        # Print Stats of Packs when first connected
        if first_run and not getattr(self, "_initial_status_logged", False):
            self.eg4ll_logger(bank_stats, 1, alarm_status)
            self._initial_status_logged = True
            return True
        # Log when driver-level alarm state changes (after update_alarm_dbus so protection attrs are current)
        if self.LoadBMSSettings is True and self.alarm_mgr._alarms_changed:
            active_alarms = {k: v for k, v in alarm_status.items() if v != 0}
            if active_alarms:
                logger.error("** BMS Error, Protect or Warning Event Code Found In Polling Cycle **")
                self.eg4ll_logger(bank_stats, 2, active_alarms)
                return True
        # Call BMS_stats when BMS hardware registers report an event
        elif any(bank_stats.get(k, "0000") != "0000" for k in ["protection_hex", "warning_hex", "error_hex"]):
            if self.protectionLogger is True:
                logger.error("** BMS Error, Protect or Warning Event Code Found In Polling Cycle **")
                self.eg4ll_logger(bank_stats, 2, alarm_status)
                return True
        # Call logger if the status is not normal
        elif bank_stats.get("status_hex", "0000") not in {"0000", "0200", "0100"}:
            self.eg4ll_logger(bank_stats, 3, alarm_status)
            return True
        elif self.statuslogger is True:
            self.eg4ll_logger(bank_stats, 1, alarm_status)
        return True

    def get_settings(self):
        result = self.read_battery_bank()
        if result is not True:
            return False
        return True

    def refresh_data(self):
        # This will be called for every iteration
        result = self.read_battery_bank()
        if result is False:
            return False
        return True

    def read_gen_data(self):
        result = self.read_battery_bank()
        if result is False:
            return False
        return True

    def read_hw_details(self, id):
        battery = {}
        command = self.eg4CommandGen((id.to_bytes(1, "big") + self.hwCommandRoot))
        result = self.read_eg4ll_command(command)
        if result is False:
            return False
        battery.update({"hw_make": result[2:25].decode("utf-8")})
        battery.update({"hw_version": result[27:33].decode("utf-8")})
        battery.update({"hw_serial": result[33:48].decode("utf-8") + str(id)})
        battery.update({"hwLastPoll": (datetime.datetime.now())})
        return battery

    def read_cell_details(self, id):
        """Modified version with cell voltage validation"""
        command = self.eg4CommandGen(id.to_bytes(1, "big") + self.cellCommandRoot)
        packet = self.read_eg4ll_command(command)
        if not packet:
            return False

        # Parsing helpers
        def u16(o):
            return int.from_bytes(packet[o : o + 2], "big")

        def s16(o):
            return int.from_bytes(packet[o : o + 2], "big", signed=True)

        def u32(o):
            return int.from_bytes(packet[o : o + 4], "big")

        def s8(o):
            return int.from_bytes(packet[o : o + 1], "big", signed=True)

        CELL_START = 7
        MAX_CELLS = 16
        # Basic battery info
        battery = {
            "voltage": u16(3) / 100,
            "current": s16(5) / 100,
            "capacity_remain": u16(45),
            "capacity": u32(65) / 3600 / 1000,
            "max_battery_charge_current": u16(47),
            "soc": u16(51),
            "soh": u16(49),
            "cycles": u32(61),
            "temperature_mos": s16(39),
            "cell_count": min(u16(75), MAX_CELLS),
            "status_hex": packet[54:56].hex().upper(),
            "warning_hex": packet[55:57].hex().upper(),
            "protection_hex": packet[57:59].hex().upper(),
            "error_hex": packet[59:61].hex().upper(),
            "heater_hex": packet[53:54].hex().upper(),
            "cellLastPoll": datetime.datetime.now(),
            "BMS_Id": id,
        }
        # Parse cell voltages
        cells = []
        for i in range(battery["cell_count"]):
            raw = u16(CELL_START + i * 2)
            voltage = raw / 1000
            battery[f"cell{i+1}"] = voltage
            cells.append(voltage)
        # Calculate cell stats
        valid_cells = [v for v in cells if v > 0.0]
        if valid_cells:
            battery["cell_voltage"] = round(sum(valid_cells), 3)
            battery["cell_max"] = max(valid_cells)
            battery["cell_min"] = min(valid_cells)
        else:
            battery["cell_voltage"] = 0.0
            battery["cell_max"] = 0.0
            battery["cell_min"] = 0.0
        # Temperature handling
        temp1 = s8(69)
        temp2 = s8(70)
        temp3 = s8(71)
        temp4 = s8(72)
        battery["temp1"] = temp1
        battery["temp2"] = temp2
        temps = [temp1, temp2]
        if temp3 != 0:
            battery["temp3"] = temp3
            temps.append(temp3)
        if temp4 != 0:
            battery["temp4"] = temp4
            temps.append(temp4)
        battery["temp_min"] = min(temps)
        battery["temp_max"] = max(temps)
        return battery

    def reportBatteryBank(self, packet):
        self.voltage = packet["cell_voltage"]
        self.current = packet["current"]
        self.capacity_remain = packet["capacity_remain"]
        self.soc = packet["soc"]
        self.soh = packet["soh"]
        self.cycles = packet["cycles"]
        self.temperature_1 = packet["temp1"]
        self.temperature_2 = packet["temp2"]
        if not (self.temperature_3 == 0) and (self.temperature_4 == 0):
            self.temperature_3 = packet["temp3"]
            self.temperature_4 = packet["temp4"]
        self.temperature_mos = packet["temperature_mos"]
        self.cell_min_voltage = packet["cell_min"]
        self.cell_max_voltage = packet["cell_max"]
        self.temp_min = min(self.temperature_1, self.temperature_2)
        self.temp_max = max(self.temperature_1, self.temperature_2)
        self.cells = [Cell(True) for _ in range(0, self.cell_count)]
        for i, cell in enumerate(self.cells):
            self.cells[int(i)].voltage = packet["cell" + str(i + 1)]
        return True

    def _state_str(self, val):
        if val == 0:
            return "Ok"
        elif val == 1:
            return "Warning"
        elif val == 2:
            return "Protect"
        return f"UNKNOWN({val})"

    def _fet_str(self, val):
        return "Enabled" if val else "Disabled"

    def eg4ll_logger(self, packet, logLevel, alarm_msg=None):
        logger.info("===== HW Info =====")
        if logLevel == 1:
            logger.info(f'  Battery Make/Model: {packet["hw_make"]}')
            logger.info(f'  Hardware Version: {packet["hw_version"]}')
        logger.info(f'  Serial Number: {packet["hw_serial"]}')
        if logLevel != 3:
            logger.info("===== Temp =====")
            logger.info(f"  Temp 1: {packet['temp1']}c | Temp 2: {packet['temp2']}c | Temp Mos: {packet['temperature_mos']}c")
            if "temp3" in packet and "temp4" in packet:
                logger.info(f"  Temp 3: {packet['temp3']}c | Temp 4: {packet['temp4']}c")
            logger.info(f"  Temp Max: {packet['temp_max']} | Temp Min: {packet['temp_min']}")
            logger.info(f"  Heater {packet['BMS_Id']} Status: {packet['heater_state']}")
        logger.info(f"  === BMS ID-{packet['BMS_Id']} ===")
        logger.info("    Voltage: " + "%.3fv" % packet["cell_voltage"] + " | Current: " + str(packet["current"]) + "A")
        logger.info(f"    Capacity: {packet['capacity_remain']} of {packet['capacity']} AH")
        logger.info(f"    Balancing State: {packet['balancing_text']}")
        logger.info(f"    State: {packet['status']}")
        logger.info(f"    Last Update: {packet['cellLastPoll']}")
        if logLevel == 1:
            logger.info(f"    SoH: {packet['soh']}% | Cycle Count: {packet['cycles']}")
            logger.info(f"    SoC: {packet['soc']}%")
        if logLevel in {1, 2}:
            logger.info("  === Warning/Alarms ===")
            logger.info(f"      {packet['warning']}")
            logger.info(f"      {packet['protection']}")
            logger.info(f"      {packet['error']}")
            if self.LoadBMSSettings and alarm_msg:
                if logLevel == 1:
                    logger.info("   === Alarm States ===")
                    for alarm_name, state in alarm_msg.items():
                        if state == 0:
                            level = "OK"
                        elif state == 1:
                            level = "WARNING"
                        else:
                            level = "PROTECTION"
                        logger.info(f"      {alarm_name}: {level}")
                elif logLevel == 2:
                    active_alarms = {name: state for name, state in alarm_msg.items() if state != 0}
                    logger.info("   === Active Alarms ===")
                    if active_alarms:
                        for alarm_name, state in active_alarms.items():
                            if state == 1:
                                level = "WARNING"
                            else:
                                level = "PROTECTION"
                            logger.info(f"      {alarm_name}: {level}")
                    else:
                        logger.info("      NONE")
            logger.info("   === Active Controls ===")
            pv_high = self._state_str(self.protection.high_voltage)
            cv_high = self._state_str(self.protection.high_cell_voltage)
            pv_low = self._state_str(self.protection.low_voltage)
            cv_low = self._state_str(self.protection.low_cell_voltage)
            tc_high = self._state_str(self.protection.high_charge_temperature)
            tc_low = self._state_str(self.protection.low_charge_temperature)
            td_high = self._state_str(self.protection.high_temperature)
            td_low = self._state_str(self.protection.low_temperature)
            cc_over = self._state_str(self.protection.high_charge_current)
            dc_over = self._state_str(self.protection.high_discharge_current)
            logger.info(f"     Pack High Voltage // Cell High Voltage: {pv_high}-{cv_high}")
            logger.info(f"     Pack Low Voltage // Cell Low Voltage: {pv_low}-{cv_low}")
            logger.info(f"     High Temp Charge // Low Temp Charge: {tc_high}-{tc_low}")
            logger.info(f"     High Temp Discharge // Low Temp Discharge: {td_high}-{td_low}")
            logger.info(f"     Charge Over Current // Discharge Over Current: {cc_over}-{dc_over}")
            logger.info(
                f"     Charging // Discharging // Balancer: "
                f"{self._fet_str(self.charge_fet)}-{self._fet_str(self.discharge_fet)}-{self._fet_str(self.balance_fet)}"
            )
        logger.info("    === Cell Stats ===")
        for cellId in range(1, packet["cell_count"] + 1):
            cell_key = f"cell{cellId}"
            if cell_key in packet:  # safety check
                logger.info(f"      Cell {cellId}: {packet[cell_key]}v")
        logger.info(f"  Cell Max/Min/Diff: ({packet['cell_max']}/{packet['cell_min']}/{round((packet['cell_max'] - packet['cell_min']), 3)})v")
        return True

    def update_alarm_dbus(self, alarm_status):
        self.protection.high_voltage = alarm_status.get("Pack_OV", 0)
        self.protection.high_cell_voltage = alarm_status.get("Cell_OV", 0)
        self.protection.low_voltage = alarm_status.get("Pack_UV", 0)
        self.protection.low_cell_voltage = alarm_status.get("Cell_UV", 0)
        self.protection.low_soc = alarm_status.get("Low_Cap", 0)
        self.charge_fet = self.alarm_mgr.charge_fet
        self.discharge_fet = self.alarm_mgr.discharge_fet
        self.protection.high_charge_current = alarm_status.get("Over_Charge_Current", 0)
        self.protection.high_discharge_current = max(alarm_status.get("Over_Discharge_Current", 0), alarm_status.get("Load_Short", 0))
        self.protection.high_charge_temperature = alarm_status.get("Charge_OT", 0)
        self.protection.high_temperature = alarm_status.get("Discharge_OT", 0)
        self.protection.low_charge_temperature = alarm_status.get("Charge_UT", 0)
        self.protection.low_temperature = alarm_status.get("Discharge_UT", 0)

    def lookup_warning(self, packet):
        warning_alarm = ""
        code = packet["warning_hex"]
        if code == "0000":
            warning_alarm += "No Warnings - " + code
        else:
            warning_alarm += "Warning: " + code + " - UNKNOWN"
        return warning_alarm

    def lookup_protection(self, packet):
        protection_alarm = ""
        code = packet["protection_hex"]
        if code == "0000":
            protection_alarm += "No Protection Events - " + code
        else:
            protection_alarm += "Protection UNKNOWN: " + code
        return protection_alarm

    def lookup_error(self, packet):
        code = packet["error_hex"]
        error_alarm = ""
        if code == "0000":
            error_alarm = "No Errors - " + code
        else:
            error_alarm = "UNKNOWN Error: " + code
        return error_alarm

    def lookup_status(self, packet):
        status_code = ""
        if packet["status_hex"] == "0000":
            status_code = "Active/Standby"
        elif packet["status_hex"] == "0100":
            status_code = "Active/Charging"
        elif packet["status_hex"] == "0200":
            status_code = "Active/Discharging"
        elif packet["status_hex"] == "0008":
            status_code = "Inactive/Protect"
        elif packet["status_hex"] == "0800":
            status_code = "Active/Charging Limit"
        else:
            status_code = "UNKNOWN Status - " + packet["status_hex"]
        return status_code

    def lookup_heater(self, packet):
        if packet["heater_hex"] == "80":
            heater_state = True
        else:
            heater_state = False
        return heater_state

    def get_balancing(self):
        balacing_state = self.balancingStat(self.battery_stats[self.Id])
        return balacing_state

    def balancingStat(self, packet):
        balancer_delta = float(packet.get("Balance_Volt_Diff") or 0.040)
        balancer_min_voltage = float(packet.get("Balance_Volt") or 3.40)
        cell_count = packet.get("cell_count")
        cell_min = packet.get("cell_min")
        cell_max = packet.get("cell_max")
        if cell_count is None or cell_min is None or cell_max is None:
            self.balacing_state = 0
            self.balance_fet = False
            return self.balacing_state
        delta_v = round(cell_max - cell_min, 3)
        # ---- Rule 1: all cells below balance voltage ----
        if cell_min < balancer_min_voltage:
            self.balacing_state = 0
            self.balance_fet = False
            return self.balacing_state
        # ---- Rule 3: top balancing finished ----
        if cell_min >= utils.MAX_CELL_VOLTAGE and delta_v <= balancer_delta:
            if self.balacing_state != 2:
                logger.info(f"BMS {packet['BMS_Id']} balancing finished")
                self.eg4ll_logger(packet, 3)
            self.balacing_state = 2
            self.balance_fet = False
            return self.balacing_state
        # ---- Rule 2: balancing active ----
        if cell_min >= balancer_min_voltage and delta_v > balancer_delta:
            self.balacing_state = 1
            self.balance_fet = True
            return self.balacing_state
        # ---- Default: monitoring / idle ----
        self.balacing_state = 0
        self.balance_fet = False
        return self.balacing_state

    def get_max_temperature(self):
        if not (self.temperature_3 == 0) and (self.temperature_4 == 0):
            temp_max = max(self.temperature_1, self.temperature_2, self.temperature_3, self.temperature_4)
        else:
            temp_max = max(self.temperature_1, self.temperature_2)
        return temp_max

    def get_min_temperature(self):
        if not (self.temperature_3 == 0) and (self.temperature_4 == 0):
            temp_min = min(self.temperature_1, self.temperature_2, self.temperature_3, self.temperature_4)
        else:
            temp_min = min(self.temperature_1, self.temperature_2)
        return temp_min

    def read_bms_config(self):
        logger.info("Polling BMS for config settings...")
        command = self.eg4CommandGen(self.Id.to_bytes(1, "big") + self.bmsConfigCommandRoot)
        packet = self.read_eg4ll_command(command)
        if not packet:
            logger.error("Failed to read BMS config, will use defaults")
            return False

        # --- Helper functions ---
        def get_int(packet, start, end, signed=False, modifier=1, round_decimals=None):
            if len(packet) < end:
                return None
            value = int.from_bytes(packet[start:end], "big", signed=signed) * modifier
            if round_decimals is not None:
                value = round(value, round_decimals)
            return value

        def get_temp(packet, start, end):
            if len(packet) < end:
                return None
            return int.from_bytes(packet[start:end], "big", signed=True) - 50

        def decode_string(packet, start, end):
            if len(packet) < end:
                return ""
            return packet[start:end].decode("utf-8", errors="ignore").strip("\x00")

        BMSConf = {}
        # --- Voltage thresholds ---
        BMSConf["Balance_Volt"] = get_int(packet, 25, 27, modifier=1 / 1000, round_decimals=3)
        BMSConf["Balance_Volt_Diff"] = get_int(packet, 27, 29, modifier=1 / 1000, round_decimals=3)
        BMSConf["Low_Cap_Warn"] = get_int(packet, 29, 31)
        BMSConf["Cell_UV_Warn"] = get_int(packet, 35, 37, modifier=1 / 1000, round_decimals=3)
        BMSConf["Cell_OV_Warn"] = get_int(packet, 47, 49, modifier=1 / 1000, round_decimals=3)
        BMSConf["Cell_UV_Protect"] = get_int(packet, 37, 39, modifier=1 / 1000, round_decimals=3)
        BMSConf["Cell_OV_Protect"] = get_int(packet, 49, 51, modifier=1 / 1000, round_decimals=3)
        BMSConf["Cell_UV_Release"] = get_int(packet, 39, 41, modifier=1 / 1000, round_decimals=3)
        BMSConf["Cell_OV_Release"] = get_int(packet, 51, 53, modifier=1 / 1000, round_decimals=3)
        BMSConf["Pack_UV_Warn"] = get_int(packet, 41, 43, modifier=1 / 100, round_decimals=2)
        BMSConf["Pack_OV_Warn"] = get_int(packet, 53, 55, modifier=1 / 100, round_decimals=2)
        BMSConf["Pack_UV_Protect"] = get_int(packet, 43, 45, modifier=1 / 100, round_decimals=2)
        BMSConf["Pack_OV_Protect"] = get_int(packet, 55, 57, modifier=1 / 100, round_decimals=2)
        BMSConf["Pack_UV_Release"] = get_int(packet, 45, 47, modifier=1 / 100, round_decimals=2)
        BMSConf["Pack_OV_Release"] = get_int(packet, 57, 59, modifier=1 / 100, round_decimals=2)
        # --- Temperature thresholds ---
        temp_fields = [
            ("Charge_UT_Warn", 93, 95),
            ("Charge_UT_Protect", 95, 97),
            ("Charge_UT_Release", 97, 99),
            ("Charge_OT_Warn", 99, 101),
            ("Charge_OT_Protect", 101, 103),
            ("Charge_OT_Release", 103, 105),
            ("Discharge_UT_Warn", 105, 107),
            ("Discharge_UT_Protect", 107, 109),
            ("Discharge_UT_Release", 109, 111),
            ("Discharge_OT_Warn", 111, 113),
            ("Discharge_OT_Protect", 113, 115),
            ("Discharge_OT_Release", 115, 117),
            ("PCB_OT_Warn", 117, 119),
            ("PCB_OT_Protect", 119, 121),
            ("PCB_OT_Release", 121, 123),
        ]
        for suffix, start, end in temp_fields:
            BMSConf[suffix] = get_temp(packet, start, end)
        # --- Current protections and delays ---
        current_fields = [
            ("Charge_OC1_Protect", 73, 75, 1 / 100),
            ("Charge_OC1_Delay", 83, 85, 1),
            ("Charge_OC2_Protect", 79, 81, 1 / 100),
            ("Charge_OC2_Delay", 85, 87, 1),
            ("Discharge_OC1_Protect", 75, 77, 1 / 100),
            ("Discharge_OC1_Delay", 87, 89, 1),
            ("Discharge_OC2_Protect", 81, 83, 1 / 100),
            ("Discharge_OC2_Delay", 89, 91, 1),
            ("Charge_Release", 71, 73, 1),
            ("Charge_OC_Times", 91, 92, 1),
            ("Discharge_Release", 69, 71, 1),
            ("Discharge_OC_Times", 92, 93, 1),
            ("Load_Short_Current", 77, 79, 1 / 100),
        ]
        for key, start, end, modifier in current_fields:
            BMSConf[key] = get_int(packet, start, end, modifier=modifier, round_decimals=2)
        BMSConf["hw_make"] = decode_string(packet, 123, 145)
        BMSConf["hw_version"] = decode_string(packet, 146, 153)
        BMSConf["hw_serial"] = decode_string(packet, 153, 167) + str(self.Id)
        BMSConf["hwLastPoll"] = datetime.datetime.now()
        logger.info("BMS Config Pulled Settings:\n%s", pformat(BMSConf))
        return BMSConf

    def eg4CommandGen(self, data: bytes) -> bytes:
        crc = 0xFFFF
        poly = 0xA001
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ poly
                else:
                    crc >>= 1
                crc &= 0xFFFF  # keep 16-bit
        return data + struct.pack("<H", crc)

    def validate_crc(self, data: bytes) -> bool:
        """
        Validate Modbus CRC-16 on received data.
        Returns True if CRC is valid, False otherwise.
        """
        if len(data) < 3:
            return False
        # Split payload and received CRC
        payload = data[:-2]
        received_crc = struct.unpack("<H", data[-2:])[0]
        # Calculate expected CRC (Modbus CRC-16)
        crc = 0xFFFF
        poly = 0xA001
        for byte in payload:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ poly
                else:
                    crc >>= 1
                crc &= 0xFFFF
        return crc == received_crc

    def read_eg4ll_command(self, command):
        try:
            bms_id = command[0]
            cmd_id = command[3]
            if cmd_id == 0x69:
                command_string = "Hardware"
                reply_length = 51
                poll_timeout = 1.5
            elif cmd_id == 0x00:
                command_string = "Cell"
                reply_length = 83
                poll_timeout = 2.0
            elif cmd_id == 0x2D:
                command_string = "Config"
                reply_length = 187
                poll_timeout = 2.5
            else:
                logger.error(f"ERROR - Unknown command ID: 0x{cmd_id:02X} for BMS ID: {bms_id}")
                return False
            if not self.ser or not self.ser.is_open:
                logger.error("ERROR - Serial Port Not Open!")
                self.ser = self.open_serial()
                if not self.ser:
                    return False
            # Retry loop with CRC validation
            received_len = 0
            for attempt in range(1, 4):
                try:
                    self.ser.reset_input_buffer()
                    self.ser.reset_output_buffer()
                    self.ser.write(command)
                    sleep(0.035)
                    buffer = bytearray()
                    start_time = time.time()
                    # Read with timeout
                    while len(buffer) < reply_length:
                        if (time.time() - start_time) > poll_timeout:
                            break
                        waiting = self.ser.in_waiting
                        if waiting:
                            buffer.extend(self.ser.read(waiting))
                        else:
                            sleep(0.01)
                    received_len = len(buffer)
                    # Check length
                    if received_len >= reply_length:
                        reply_data = bytes(buffer[:reply_length])
                        # VALIDATE CRC
                        if not self.validate_crc(reply_data):
                            continue  # Retry on CRC failure
                        # CRC valid
                        self._eg4_ll_initialized = True
                        return reply_data
                except serial.SerialException as e:
                    logger.error(f"Serial error on attempt {attempt} for BMS {bms_id}: {e}")
                    try:
                        self.ser.close()
                    except Exception:
                        pass
                    sleep(2.0)
                    self.ser = self.open_serial()
                    if not self.ser:
                        return False
            # All attempts failed
            logger.error(
                f"ERROR - All retry attempts failed! " f"BMS ID: {bms_id} Command: {command_string} " f"Received: {received_len} Expected: {reply_length}"
            )
            return False
        except serial.SerialException as e:
            logger.error(e)
            return False


class EG4AlarmManager:
    DEFAULTS = {
        "Cell_OV_Warn": 3.6,
        "Cell_OV_Protect": 3.9,
        "Cell_OV_Release": 3.45,
        "Cell_UV_Warn": 2.5,
        "Cell_UV_Protect": 2.0,
        "Cell_UV_Release": 3.1,
        "Charge_UT_Warn": 2,
        "Charge_UT_Protect": 0,
        "Charge_UT_Release": 5,
        "Charge_OT_Warn": 70,
        "Charge_OT_Protect": 75,
        "Charge_OT_Release": 65,
        "Discharge_UT_Warn": -15,
        "Discharge_UT_Protect": -20,
        "Discharge_UT_Release": -10,
        "Discharge_OT_Warn": 70,
        "Discharge_OT_Protect": 75,
        "Discharge_OT_Release": 65,
        "PCB_OT_Warn": 95,
        "PCB_OT_Protect": 100,
        "PCB_OT_Release": 80,
        "Charge_OC1_Protect": 220,
        "Charge_OC1_Delay": 10,
        "Charge_OC2_Protect": 250,
        "Charge_OC2_Delay": 2,
        "Charge_OC_Release": 60,
        "Discharge_OC1_Protect": 220,
        "Discharge_OC1_Delay": 10,
        "Discharge_OC2_Protect": 250,
        "Discharge_OC2_Delay": 2,
        "Discharge_OC_Release": 60,
        "Load_Short_Current": 350,
        "Low_Cap_Warn": 5,
    }

    def __init__(self, bms_data, eg4ll_logger_cb=None):
        """
        Initialize the alarm manager.

        :param bms_data: Dictionary containing BMS telemetry & limit values.
        :param eg4ll_logger_cb: Optional callback function for warnings/protections.
        """
        self.data = bms_data
        self.eg4ll_logger_cb = eg4ll_logger_cb
        self.alarm_states = {}  # Tracks previous state for edge-triggered logging
        self.charge_fet = True
        self.discharge_fet = True
        self._initialized = False
        self._charge_oc_time = {}  # timestamps for Charge OC1/OC2
        self._discharge_oc_time = {}  # timestamps for Discharge OC1/OC2

    def _get(self, key):
        if key in self.data:
            return self.data[key]
        if key in self.DEFAULTS:
            return self.DEFAULTS[key]
        return None

    def _check_high(self, value, warn, protect):
        if protect is not None and value >= protect:
            return 2
        if warn is not None and value >= warn:
            return 1
        return 0

    def _check_low(self, value, warn, protect):
        if protect is not None and value <= protect:
            return 2
        if warn is not None and value <= warn:
            return 1
        return 0

    def evaluate(self, new_data=None):
        """
        Evaluate all alarms, update alarm states, FETs, and edge-triggered logging.
        Optional `new_data` can be passed to refresh telemetry.
        """
        if new_data:
            self.data = new_data
        if not self.data:
            return

        # --- Do not evaluate until live telemetry exists ---
        required_keys = ("cell_max", "cell_min", "temp_max", "temp_min", "current", "cell_voltage", "soc")
        if not all(k in self.data for k in required_keys):
            if not hasattr(self, "_telemetry_warned"):
                self.eg4ll_logger_cb({"info": "Waiting for live telemetry before evaluating alarms"})
                self._telemetry_warned = True
            return {}

        now = time.time()
        alarms = {}

        if not hasattr(self, "_limits_checked"):
            for k in ["Pack_OV_Protect", "Pack_UV_Protect"]:
                if self._get(k) is None:
                    print(f"[EG4AlarmManager] {k} not provided by BMS — alarm disabled")
            self._limits_checked = True

        # --- Cell Voltage ---
        cell_max = self.data.get("cell_max", 0)
        cell_min = self.data.get("cell_min", 0)
        alarms["Cell_OV"] = self._check_high(cell_max, self._get("Cell_OV_Warn"), self._get("Cell_OV_Protect"))
        alarms["Cell_UV"] = self._check_low(cell_min, self._get("Cell_UV_Warn"), self._get("Cell_UV_Protect"))

        # --- Pack Voltage ---
        pack_v = self.data.get("cell_voltage", 0)
        alarms["Pack_OV"] = self._check_high(pack_v, self._get("Pack_OV_Warn"), self._get("Pack_OV_Protect"))
        alarms["Pack_UV"] = self._check_low(pack_v, self._get("Pack_UV_Warn"), self._get("Pack_UV_Protect"))

        # --- Temperature ---
        temp_max = self.data.get("temp_max", 0)
        temp_min = self.data.get("temp_min", 0)
        alarms["Charge_UT"] = self._check_low(temp_min, self._get("Charge_UT_Warn"), self._get("Charge_UT_Protect"))
        alarms["Charge_OT"] = self._check_high(temp_max, self._get("Charge_OT_Warn"), self._get("Charge_OT_Protect"))
        alarms["Discharge_UT"] = self._check_low(temp_min, self._get("Discharge_UT_Warn"), self._get("Discharge_UT_Protect"))
        alarms["Discharge_OT"] = self._check_high(temp_max, self._get("Discharge_OT_Warn"), self._get("Discharge_OT_Protect"))
        alarms["PCB_OT"] = self._check_high(temp_max, self._get("PCB_OT_Warn"), self._get("PCB_OT_Protect"))

        # --- Low Capacity ---
        soc = self.data.get("soc", 100)
        low_cap = self._get("Low_Cap_Warn")
        alarms["Low_Cap"] = 2 if low_cap is not None and soc <= low_cap else 0

        # --- Load Short ---
        current = self.data.get("current", 0)
        ls = self._get("Load_Short_Current")
        alarms["Load_Short"] = 2 if ls is not None and abs(current) >= ls else 0

        # --- Charge/Discharge Overcurrent Timers ---
        def check_overcurrent(value, oc1_prot, oc1_delay, oc2_prot, oc2_delay, last_oc_time):
            state = 0

            if oc2_prot is not None and value >= oc2_prot:
                if "OC2_start" not in last_oc_time:
                    last_oc_time["OC2_start"] = now
                if now - last_oc_time["OC2_start"] >= oc2_delay:
                    state = 2
            else:
                last_oc_time.pop("OC2_start", None)

            if oc1_prot is not None and value >= oc1_prot:
                if "OC1_start" not in last_oc_time:
                    last_oc_time["OC1_start"] = now
                if now - last_oc_time["OC1_start"] >= oc1_delay:
                    state = max(state, 2)
            else:
                last_oc_time.pop("OC1_start", None)

            return state

        alarms["Over_Charge_Current"] = check_overcurrent(
            max(current, 0),
            self._get("Charge_OC1_Protect"),
            self._get("Charge_OC1_Delay"),
            self._get("Charge_OC2_Protect"),
            self._get("Charge_OC2_Delay"),
            self._charge_oc_time,
        )

        alarms["Over_Discharge_Current"] = check_overcurrent(
            abs(min(current, 0)),
            self._get("Discharge_OC1_Protect"),
            self._get("Discharge_OC1_Delay"),
            self._get("Discharge_OC2_Protect"),
            self._get("Discharge_OC2_Delay"),
            self._discharge_oc_time,
        )

        # --- FET control flags ---
        # Voltage and current alarms disable FET on WARNING or PROTECTION (any non-zero state)
        # Temperature alarms only disable FET on PROTECTION (state == 2) due to thermal buffering
        self.charge_fet = all(alarms.get(k, 0) == 0 for k in ["Cell_OV", "Pack_OV", "Load_Short", "Over_Charge_Current"]) and all(
            alarms.get(k, 0) < 2 for k in ["Charge_OT", "Charge_UT"]
        )
        self.discharge_fet = all(alarms.get(k, 0) == 0 for k in ["Cell_UV", "Pack_UV", "Load_Short", "Over_Discharge_Current"]) and all(
            alarms.get(k, 0) < 2 for k in ["Discharge_OT", "Discharge_UT"]
        )

        # --- Edge-triggered state tracking ---
        self._alarms_changed = False
        for alarm, state in alarms.items():
            prev = self.alarm_states.get(alarm, state)
            if state != prev:
                self._alarms_changed = True
            self.alarm_states[alarm] = state

        # Suppress on first valid evaluation
        if not self._initialized:
            self._initialized = True

        return alarms
