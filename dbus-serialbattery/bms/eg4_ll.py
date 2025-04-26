# -*- coding: utf-8 -*-

# Notes
# Added by https://github.com/tuxntoast

# from batters import Protection
from battery import Battery, Cell
from utils import logger
from struct import unpack_from
from time import sleep
from pprint import pformat
import serial, struct, sys
import utils, datetime

#    Author: Pfitz
#    Date: 07 Mar 2025
#    Features:
#     UI reporting for all BMS in Communication chain
#     Multi BMS communication Chain Support
#     Cell Voltage Implemented
#     Hardware Name / Version / Serial Implemented
#     Error / Warn / Protection Implemented
#        - Looks like the Code might not be totally correct OR the BMS has
#          moments where a random is returned but only during one BMS poll
#     SoH / SoC State Implemented
#     Temp Implemented
#     Balancing Support
#     Battery Voltage / Current
#     Support for 12v/24v/48v BMS

# Battery Tested on:
# 2x Eg4 LL 12v 400 AH
# Venus OS v3.52 running on Cerbo GX - dbus-serialbattery v2.0.20250228dev
# One RS232 Cable to USB is needed to connect Cerbo GX to the master BMS
# A Cat5/Cat6 cable can be used to connected the Master BMS RS485 secondary port to the
# first port of the BMS below it. BMS units can be "Daisy Chained" until your full bank is connected
# In config.ini set line 167 "BATTERY_ADDRESSES with the hex ID of each unit in your BMS chain 
# BATTERY_ADDRESSES = 0x10, 0x01
# would collect and report on BMS ID 16 and 01 in a Daisy Chained montioring setup
#
# The master unit or first unit should have a Dip Switch ID set to 16 or 64 depending on your unit and version
# All other BMS in the communication chain should have a Dip switch setting of 1 - 15 or 1 - 63 depending on your units
#


class EG4_LL(Battery):
    def __init__(self, port, baud, address):

        super(EG4_LL, self).__init__(port, baud, address)
        self.cell_min_voltage = 0
        self.cell_max_voltage = None
        self.has_settings = 0
        self.reset_soc = 0
        self.soc_to_set = None
        self.type = self.BATTERYTYPE
        self.runtime = 0  # TROUBLESHOOTING for no reply errors

    statuslogger = False
    # When BMS returns a Warning/Error/Protection Alarm, Print that Error code
    # and BMS Stats to Driver Log file. This would help a user figure out what might be happening
    protectionLogger = False

    battery_stats = {}
    serialTimeout = 2

    BATTERYTYPE = "EG4-LL"

    hwCommandRoot = b"\x03\x00\x69\x00\x17"
    cellCommandRoot = b"\x03\x00\x00\x00\x27"
    bmsConfigCommandRoot = b"\x03\x00\x2D\x00\x5B"

    def unique_identifier(self):
        return self.serial_number

    def custom_name(self):
        self.custom_name = self.BATTERYTYPE+"_ID:"+str(self.Id)
        return self.custom_name

    def open_serial(self):
        ser = serial.Serial(self.port,
            baudrate=self.baud_rate,
            timeout=self.serialTimeout,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS)
        if ser.isOpen() == True:
            return ser
        else:
            return False

    def test_connection(self):
        try:
            self.battery_stats = {}
            self.Id = int.from_bytes(self.address, "big")
            self.ser = self.open_serial()
            BMS_list = self.discovery_pack(self.Id)
            if BMS_list is False:
                return False
            else:
                logger.info(f"Connected to BMS ID: {pformat(BMS_list)}")
                self.poll_interval = (((self.serialTimeout)*1000)*3)
                self.custom_field = self.BATTERYTYPE+":"+str(self.Id)
                cell_poll = self.read_battery_bank()
                self.cell_count = int(self.battery_stats[self.Id]["cell_count"])
                if cell_poll is not False:
                    self.status_logger()
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
            logger.error(
                f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}"
            )

    def read_battery_bank(self):
        cell_reply = self.read_cell_details(self.Id)
        if cell_reply is not False:
            if self.Id in self.battery_stats:
                self.battery_stats[self.Id] = { **self.battery_stats[self.Id], **cell_reply }
            else:
                hw_reply = self.read_hw_details(self.Id)
                if hw_reply is not False:
                    self.cell_count = int(cell_reply["cell_count"])
                    self.min_battery_voltage = float(utils.MIN_CELL_VOLTAGE * self.cell_count)
                    self.max_battery_voltage = float(utils.MAX_CELL_VOLTAGE * self.cell_count)
                    self.capacity = cell_reply["capacity"]
                    self.battery_stats[self.Id] = { **cell_reply, **hw_reply }
                else:
                    return False
        else:
            return False
        result = self.reportBatteryBank()
        if self.statuslogger is True:
            self.status_logger()
        if result is True:
            return True
        return False

    def get_settings(self):
        result = self.read_battery_bank()
        if result is not True:
            return False
        self.status_logger()
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

    def discovery_pack(self, Id):
        bmsChain = {}
        command = self.eg4CommandGen((Id.to_bytes(1, 'big') + self.hwCommandRoot))
        reply = self.read_eg4ll_command(command)
        if reply is not False:
            serial = (reply[33:48].decode("utf-8")+str(Id))
            bmsChain.update({Id: serial})
            self.serial_number = serial
            return bmsChain
        else:
            return False


    def read_hw_details(self, id):
        battery = {}
        command = self.eg4CommandGen((id.to_bytes(1, 'big') + self.hwCommandRoot))
        result = self.read_eg4ll_command(command)
        if result is False:
            return False

        battery.update({"hw_make" : result[2:25].decode("utf-8")})
        battery.update({"hw_version" : result[27:33].decode("utf-8")})
        battery.update({"hw_serial" : (result[33:48].decode("utf-8")+str(id))})
        battery.update({"hwLastPoll" : (datetime.datetime.now())})
        self.serial_number = battery["hw_serial"]
        self.version = battery["hw_make"]
        self.hardware_version = battery["hw_version"]

        return battery

    def read_cell_details(self, id):

        battery = {}
        command = self.eg4CommandGen((id.to_bytes(1, 'big') + self.cellCommandRoot))
        packet = self.read_eg4ll_command(command)
        if packet is False:
            return False
        battery.update({"voltage" : int.from_bytes(packet[3:5], "big") / 100})
        battery.update({"current" : int.from_bytes(packet[5:7], "big", signed=True) / 100})
        battery.update({"capacity_remain" : int.from_bytes(packet[45:47], "big")})
        battery.update({"capacity" : int.from_bytes(packet[65:69], "big") / 3600 / 1000})
        battery.update({"max_battery_charge_current" : int.from_bytes(packet[47:49], "big")})
        battery.update({"soc" : int.from_bytes(packet[51:53], "big")})
        battery.update({"soh" : int.from_bytes(packet[49:51], "big")})
        battery.update({"cycles" : int.from_bytes(packet[61:65], "big")})
        battery.update({"temp1" : int.from_bytes(packet[69:70], "big", signed=True)})
        battery.update({"temp2" : int.from_bytes(packet[70:71], "big", signed=True)})
        battery.update({"temp_mos" : int.from_bytes(packet[39:41], "big", signed=True)})
        battery.update({"temp_max" : max(battery["temp1"], battery["temp2"])})
        battery.update({"temp_min" : min(battery["temp1"], battery["temp2"])})
        battery.update({"cell_count" : int.from_bytes(packet[75:77], "big")})
        battery.update({"status_hex" : packet[54:56].hex().upper()})
        battery.update({"warning_hex" : packet[55:57].hex().upper()})
        battery.update({"protection_hex" : packet[57:59].hex().upper()})
        battery.update({"error_hex" : packet[59:61].hex().upper()})
        battery.update({"heater_status" : packet[53:54].hex().upper()})
        battery.update({"cellLastPoll" : (datetime.datetime.now())})
        startByte = 7
        endByte = 9
        cellId = 1
        cellVoltageList = []
        cellVoltageSum = 0
        # Debug Cell Mis Reporting 
        if battery["cell_count"] != self.cell_count:
            logger.error(f"Battery: {id.to_bytes(1, 'big')} Cell Count: {battery['cell_count']}")
            logger.error(f"BMS Reply: {packet.hex().upper()}")
        while cellId <= battery["cell_count"]:
            cellNum = "cell"+str(cellId)
            cellVolt = int.from_bytes(packet[startByte:endByte], "big")/1000
            battery.update({cellNum : cellVolt})
            cellVoltageSum += float(battery[cellNum])
            cellVoltageList.append(battery.get(cellNum))
            startByte += 2
            endByte += 2
            cellId += 1
        battery.update({"cell_voltage" : cellVoltageSum})
        battery.update({"cell_max" : max(cellVoltageList)})
        battery.update({"cell_min" : min(cellVoltageList)})

        balancing_code = self.balancingStat(min(cellVoltageList), max(cellVoltageList))
        battery.update({"balancing_code" : balancing_code})
        if balancing_code == 2:
            battery.update({"balancing_text" : "Finished"})
        elif balancing_code == 1:
            battery.update({"balancing_text" : "Balancing"})
        elif balancing_code == 0:
            battery.update({"balancing_text" : "Off"})
        else:
            battery.update({"balancing_text" : "UNKNOWN"})

        return battery

    def reportBatteryBank(self):
        self.voltage = self.battery_stats[self.Id]["cell_voltage"]
        self.current = self.battery_stats[self.Id]["current"]
        self.capacity_remain = self.battery_stats[self.Id]["capacity_remain"]
        self.soc = self.battery_stats[self.Id]["soc"]
        self.soh = self.battery_stats[self.Id]["soh"]
        self.cycles = self.battery_stats[self.Id]["cycles"]
        self.temp1 = self.battery_stats[self.Id]["temp1"]
        self.temp2 = self.battery_stats[self.Id]["temp2"]
        self.temp_mos = self.battery_stats[self.Id]["temp_mos"]
        self.cell_min_voltage = self.battery_stats[self.Id]["cell_min"]
        self.cell_max_voltage = self.battery_stats[self.Id]["cell_max"]
        self.lookup_protection(self.battery_stats)
        self.lookup_warning(self.battery_stats)
        self.lookup_error(self.battery_stats)
        self.temp_max = max(self.temp1, self.temp2)
        self.temp_min = min(self.temp1, self.temp2)
        self.cells = [Cell(True) for _ in range(0, self.cell_count)]
        for i, cell in enumerate(self.cells):
            self.cells[int(i)].voltage = self.battery_stats[self.Id]['cell'+str(i+1)]

        return True

    def bms_stats(self):
        logger.info("== Pack Details =====")
        logger.info(f"  == BMS ID-{self.Id} ===")
        logger.info(f"    == Temp ==")
        logger.info(f"      Temp 1: {self.temp1}c | Temp 2: {self.temp2}c | Temp Mos: {self.temp_mos}c")
        logger.info("     == BMS Data ==")
        logger.info("       Voltage: "
            + "%.3fv" % self.voltage
            + " | Current: "
            + str(self.current)
            + "A"
        )
        logger.info(f"       Capacity Left: {self.capacity_remain} of {self.capacity} AH")
        logger.info(f"       Balancing State: {self.battery_stats[self.Id]['balancing_text']}")
        logger.info(f"       State: {self.lookup_status(self.battery_stats[self.Id]['status_hex'])}")
        logger.info(f"       Last Update: {self.battery_stats[self.Id]['cellLastPoll']}")
        logger.info("     == Cell Stats ==")
        cellId = 1
        while cellId <= self.battery_stats[self.Id]['cell_count']:
            logger.info(f"       Cell {str(cellId)} Voltage: {self.battery_stats[self.Id]['cell'+str(cellId)]}")
            cellId += 1
        logger.info(f"       Cell Max/Min/Diff: ({self.battery_stats[self.Id]['cell_max']}/{self.battery_stats[self.Id]['cell_min']}/{round((self.battery_stats[self.Id]['cell_max'] - self.battery_stats[self.Id]['cell_min']), 3)})v")
        return True

    def status_logger(self):
        logger.info("===== HW Info =====")
        logger.info(f'Battery Make/Model: {self.battery_stats[self.Id]["hw_make"]}')
        logger.info(f'Hardware Version: {self.battery_stats[self.Id]["hw_version"]}')
        logger.info(f'Serial Number: {self.battery_stats[self.Id]["hw_serial"]}')
        logger.info("===== Temp =====")
        logger.info(f"Temp 1: {self.temp1}c | Temp 2: {self.temp2}c | Temp Mos: {self.temp_mos}c")
        logger.info(f"Temp Max: {self.temp_max} | Temp Min: {self.temp_min}")
        logger.info(f"Heater {self.Id} Status: {self.lookup_heater(self.battery_stats[self.Id]['heater_status'])}")
        logger.info("===== BMS Data =====")
        logger.info("Voltage: "
            + "%.3fv" % self.voltage
            + " | Current: "
            + str(self.current)
            + "A"
        )
        logger.info(f"Capacity Left: {self.capacity_remain} of {self.capacity} AH")
        logger.info(f"SoC: {self.soc}%")
        logger.info(f"SoH: {self.soh}% | Cycle Count: {self.cycles}")
        logger.info(f"Balancing State: {self.battery_stats[self.Id]['balancing_text']}")
        logger.info("===== Warning/Alarms =====")
        logger.info(f"  {self.lookup_warning(self.battery_stats)}")
        logger.info(f"  {self.lookup_protection(self.battery_stats)}")
        logger.info(f"  {self.lookup_error(self.battery_stats)}")
        logger.info("===== Pack Details =====")
        logger.info(f"  === BMS ID-{self.Id} ===")
        logger.info(f"  State: {self.lookup_status(self.battery_stats[self.Id]['status_hex'])}")
        logger.info(f"  Pack Balancing: {self.battery_stats[self.Id]['balancing_text']}")
        logger.info(f"  Last Update: {self.battery_stats[self.Id]['cellLastPoll']}")
        logger.info(f"  Pack Voltage: {round((self.battery_stats[self.Id]['cell_voltage']),3)}v | Pack Current: {round((self.battery_stats[self.Id]['current']),2)}a")
        logger.info("    = Cell Stats =")
        cellId = 1
        while cellId <= self.battery_stats[self.Id]['cell_count']:
            logger.info(f"  Cell {str(cellId)} Voltage: {self.battery_stats[self.Id]['cell'+str(cellId)]}")
            cellId += 1
        logger.info(f"  Cell Max/Min/Diff: ({self.battery_stats[self.Id]['cell_max']}/{self.battery_stats[self.Id]['cell_min']}/{round((self.battery_stats[self.Id]['cell_max'] - self.battery_stats[self.Id]['cell_min']), 3)})v")
        return True

    def lookup_warning(self, batteryBankStats):
        code = batteryBankStats[self.Id]["warning_hex"]
        warning_alarm = ""
        if code == "0000":
            warning_alarm += "No Warnings - "+code
        elif code == "0001":
            warning_alarm += "Warning: "+code+" - Pack Over Voltage"
            self.voltage_high = 1
            self.charge_fet = False
        elif code == "0002":
            warning_alarm += "Warning: "+code+" - Cell Over Voltage"
            self.voltage_cell_high = 1
            self.charge_fet = False
        elif code == "0004":
            warning_alarm += "Warning: "+code+" - Pack Under Voltage"
            self.voltage_low = 1
            self.discharge_fet = False
        elif code == "0008":
            warning_alarm += "Warning: "+code+" - Cell Under Voltage"
            self.voltage_cell_low = 1
            self.discharge_fet = False
        elif code == "0010":
            warning_alarm += "Warning: "+code+" - Charge Over Current"
            self.current_over = 1
        elif code == "0020":
            warning_alarm += "Warning: "+code+" - Discharge Over Current"
            self.current_over = 1
        elif code == "0040":
            warning_alarm += "Warning: "+code+" - Ambient High Temp"
            self.temp_high_internal = 1
        elif code == "0080":
            warning_alarm += "Warning: "+code+" - Mosfets High Temp"
            self.temp_high_internal = 1
        elif code == "0100":
            warning_alarm += "Warning: "+code+" - Charge Under Temp" # Testing: 0100=Charge Under Temp
            self.temp_high_charge = 1
        elif code == "0200":
            warning_alarm += "Warning: "+code+" - Discharge Over Temp"
            self.temp_high_discharge = 1
        elif code == "0400":
            warning_alarm += "Warning: "+code+" - Charge Under Temp"
            self.temp_low_charge = 1
        elif code == "1000":
            warning_alarm += "Warning: "+code+" - Low Capacity"
            self.soc_low = 1
            self.discharge_fet = False
        elif code == "2000":
            warning_alarm += "Warning: "+code+" - Float Stoped"
        elif code == "4000":
            warning_alarm += "Warning: "+code+" - UNKNOWN"
            self.internal_failure = 1
        else:
            warning_alarm += "Warning: "+code+" - UNKNOWN"
        if self.protectionLogger is True:
            if code != "0000":
                logger.error(f"{warning_alarm}")
                self.bms_stats()
        return warning_alarm

    def lookup_protection(self, batteryBankStats):
        code = batteryBankStats[self.Id]["protection_hex"]
        protection_alarm = ""
        if code == "0000":
            protection_alarm += "No Protection Events - "+code
            self.charge_fet = True
            self.discharge_fet = True
        elif code == "0001":
            protection_alarm += "Protection: "+code+" - Pack Over Voltage"
            self.voltage_high = 2
            self.charge_fet = False
        elif code == "0002":
            protection_alarm += "Protection: "+code+" - Cell Over Voltage"
            self.voltage_cell_high = 2
            self.charge_fet = False
        elif code == "0004":
            protection_alarm += "Protection: "+code+" - Pack Under Voltage"
            self.voltage_low = 2
            self.discharge_fet = False
        elif code == "0008":
            protection_alarm += "Protection: "+code+" - Cell Under Voltage"
            self.voltage_cell_low = 2
            self.discharge_fet = False
        elif code == "0010":
            protection_alarm += "Protection: "+code+" - Charge Over Current"
            self.current_over = 2
        elif code == "0020":
            protection_alarm += "Protection: "+code+" - Discharge Over Current"
            self.current_over = 2
        elif code == "0040":
            protection_alarm += "Protection: "+code+" - High Ambient Temp"
            self.temp_high_internal = 2
            self.charge_fet = False
        elif code == "0080":
            protection_alarm += "Protection: "+code+" - Mosfets High Temp"
            self.temp_high_internal = 2
            self.charge_fet = False
        elif code == "0100":
            protection_alarm += "Protection: "+code+" - Charge Over Temp"
            self.temp_high_charge = 2
            self.charge_fet = False
            self.discharge_fet = False
        elif code == "0200":
            protection_alarm += "Protection: "+code+" - Discharge Over Temp"
            self.temp_high_discharge = 2
            self.charge_fet = False
            self.discharge_fet = False
        elif code == "0400":
            protection_alarm += "Protection: "+code+" - Charge Under Temp"
            self.temp_low_charge = 2
            self.charge_fet = False
        elif code == "0800":
            protection_alarm += "Protection: "+code+" - Discharge Under Temp"
            self.temp_low_charge = 2
            self.discharge_fet = False
        elif code == "1000":
            protection_alarm += "Protection: "+code+" - Low Capacity"
            self.soc_low = 2
            self.discharge_fet = False
        elif code == "2000":
            protection_alarm += "Protection: "+code+" - Discharge SC"
            self.discharge_fet = False
        else:
            protection_alarm += "Protection UNKNOWN: "+code
        if self.protectionLogger is True:
            if code != "0000":
                logger.error(f"{protection_alarm}")
                self.bms_stats()
        return protection_alarm

    def lookup_error(self, batteryBankStats):
        code = batteryBankStats[self.Id]["error_hex"]
        error_alarm = ""
        if code == "0000":
            error_alarm = f"No Errors - "+code
        elif code == "0001":
            error_alarm = f"Error: "+code+" - Voltage Error"
        elif code == "0002":
            error_alarm = f"Error: "+code+" - Temperature Error"
        elif code == "0004":
            error_alarm = f"Error: "+code+" - Current Flow Error"
        elif code == "0010":
            error_alarm = f"Error: "+code+" - Cell Unbalanced"
        else:
            error_alarm = "UNKNOWN: "+code
        if self.protectionLogger is True:
            if code != "0000":
                logger.error(f"{error_alarm}")
                self.bms_stats()
        return error_alarm

    def lookup_status(self, status_hex):
        status_code = "UNKNOWN"
        if status_hex == "0000":
            status_code = "Inactive/Standby"
        elif status_hex == "0001":
            status_code = "Inactive/Charging"
        elif status_hex == "0002":
            status_code = "Inactive/Discharging"
        elif status_hex == "0004":
            status_code = "Inactive/Protect"
        elif status_hex == "0008":
            status_code = "Inactive/Charging Limit"
        elif status_hex == "8000":
            status_code = "Active/Standby"
        elif status_hex == "8001":
            status_code = "Active/Charging"
        elif status_hex == "8002":
            status_code = "Active/Discharging"
        elif status_hex == "8004":
            status_code = "Active/Protect"
        elif status_hex == "8008":
            status_code = "Active/Charging Limit"
        return status_code

    def lookup_heater(self, heater_status):
        if heater_status == "00":
            heater_state = False
        elif heater_status == "80":
            heater_state = True
        return heater_state

    def get_balancing(self):
        balancer_current_delta = .40
        balancer_voltage = 3.40
        if (self.battery_stats[self.Id]['cell_max'] > balancer_voltage) and (round((self.battery_stats[self.Id]['cell_max'] - self.battery_stats[self.Id]['cell_min']), 3) <= balancer_current_delta):
            balacing_state = 2
            self.balance_fet = False
            self.balancing = False
        elif (self.battery_stats[self.Id]['cell_max'] - self.battery_stats[self.Id]['cell_min']) >= balancer_current_delta:
            balacing_state = 1
            self.balance_fet = True
            self.balancing = True
        else:
            balacing_state = 0
            self.balance_fet = False
            self.balancing = False
        return balacing_state

    def balancingStat(self, cellMin, cellMax):
        balancer_current_delta = .40
        balancer_voltage = 3.40
        if (cellMax > balancer_voltage) and (round((cellMax - cellMin), 3) <= balancer_current_delta):
            balacing_state = 2
        elif (cellMax - cellMin) >= balancer_current_delta:
            balacing_state = 1
        else:
            balacing_state = 0
        return balacing_state

    def get_max_temperature(self):
        self.temp1 = self.battery_stats[self.Id]["temp1"]
        self.temp2 = self.battery_stats[self.Id]["temp2"]
        temp_max = max(self.temp1, self.temp2)
        return temp_max

    def get_min_temperature(self):
        self.temp1 = self.battery_stats[self.Id]["temp1"]
        self.temp2 = self.battery_stats[self.Id]["temp2"]
        temp_min = min(self.temp1, self.temp2)
        return temp_min

    def read_bms_config(self):
        logger.info("Executed read_bms_config function... function needs to be written")
        return True

    def eg4CommandGen(self, data: bytes):
        # CRC-16-ModBus Algorithm
        poly = 0xA001
        crc = 0xFFFF
        for b in data:
            crc ^= (0xFF & b)
            for _ in range(0, 8):
                if (crc & 0x0001):
                    crc = ((crc >> 1) & 0xFFFF) ^ poly
                else:
                    crc = ((crc >> 1) & 0xFFFF)
        reverseHex = struct.pack('<H', crc)
        command = data + reverseHex
        return command

    # Read data from previously opened serial port
    def read_eg4ll_command(self, command):
        attemptCount = 0
        try:
            CommandHex = command.hex(":").upper()
            bmsId = int(CommandHex[0:2], 16)
            cmdId = CommandHex[9:11]

            if cmdId == "69":
                commandString = "Hardware"
                reply_length = 51
            elif cmdId == "00":
                commandString = "Cell"
                reply_length = 83
            elif cmdId == "2D":
                commandString = "Config"
            else:
                commandString = "UNKNOWN"

            if self.ser.isOpen() == True:
                while attemptCount <= 3:
                    self.ser.reset_input_buffer()
                    self.ser.reset_output_buffer()
                    self.ser.write(command)
                    pollCount = 0
                    toread = self.ser.inWaiting()
                    attemptCount += 1
                    while toread < reply_length:
                        sleep(0.035)
                        toread = self.ser.inWaiting()
                        pollCount += 1
                        if toread == reply_length:
                            break
                        if pollCount > 50:
                            if attemptCount == 3 and cmdId == "00":
                                logger.error(f'No Reply - BMS ID: {bmsId} Command: {commandString} - Attempt: {attemptCount}')
                                return False
                            elif cmdId == "69":
                                logger.error(f'No Reply - BMS ID: {bmsId} Command: {commandString}')
                                return False
                            elif cmdId != "00":
                                return False
                            else:
                                break
                    if toread == reply_length:
                        break
                res = self.ser.read(toread)
                data = bytearray(res)
            else:
                logger.error(f'ERROR - Serial Port Not Open!')
                self.ser = self.open_serial()
                return False

            if toread == reply_length:
                return data
            else:
                logger.error(f'ERROR - Reply not meet expected length! BMS ID: {bmsId} Command: {commandString}')
                return False
        except serial.SerialException as e:
            logger.error(e)
            return False
