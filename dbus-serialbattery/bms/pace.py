# -*- coding: utf-8 -*-

# Notes
# Added by https://github.com/KoljaWindeler

from battery import Battery, Cell
from utils import read_serial_data, logger
import utils
import sys


class Pace(Battery):
    def __init__(self, port, baud, address):
        super(Pace, self).__init__(port, baud, address)
        self.type = self.BATTERYTYPE
        self.unique_identifier_tmp = ""
        self.cell_count = 0
        self.address = address
        self.poll_interval = 5000
        self.cell_voltage_lp = 0.9

    BATTERYTYPE = "PACE RS232"
    LENGTH_CHECK = 0  # ignored
    LENGTH_POS = 2  # ignored
    LENGTH_SIZE = "H"  # ignored

    @property
    def command_status(self):
        return b"\x7E\x32\x35\x30\x30\x34\x36\x34\x32\x45\x30\x30\x32\x46\x46\x46\x44\x30\x36\x0D"

    @property
    def command_software_version(self):
        return b"\x7E\x32\x35\x30\x30\x34\x36\x43\x31\x30\x30\x30\x30\x46\x44\x39\x42\x0D"

    @property
    def command_serial_nr(self):
        return b"\x7E\x32\x35\x30\x30\x34\x36\x43\x32\x30\x30\x30\x30\x46\x44\x39\x41\x0D"

    @property
    def command_fuses(self):  # warn information
        return b"\x7E\x32\x35\x30\x30\x34\x36\x34\x34\x45\x30\x30\x32\x30\x31\x46\x44\x32\x46\x0D"

    def test_connection(self):
        # call a function that will connect to the battery, send a command and retrieve the result.
        # The result or call should be unique to this BMS. Battery name or version, etc.
        # Return True if success, False for failure

        try:
            result = self.get_settings()
            result = result and self.read_status_data()
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
        # After successful  connection get_settings will be call to set up the battery.
        # Set the current limits, populate cell count, etc
        # Return True if success, False for failure
        logger.debug("requesting settings")
        status_data = self.read_serial_data_pace(self.command_status, 160)
        # check if connection success
        if status_data is False:
            return False

        self.cell_count = int(status_data[17:19], 16)
        for i in range(0, self.cell_count):
            self.cells.append(Cell(False))

        # cycles
        self.cycles = int(status_data[127:131], 16)

        # capacity
        self.capacity_remain = int(status_data[117:121], 16) / 100

        self.max_battery_voltage = utils.MAX_CELL_VOLTAGE * self.cell_count
        self.min_battery_voltage = utils.MIN_CELL_VOLTAGE * self.cell_count

        # ######################### SOFTWARE VERSION #############################
        logger.debug("requesting software version")
        # 13 + 5 + 40, should be 58, but doesn't ever trigger, so we use 57, that works fine
        status_data = self.read_serial_data_pace(self.command_software_version, 57)
        if status_data is False:
            return True
        else:
            h = ""
            for i in range(20):  # 20 byte
                h = h + chr(status_data[2 * i + 13]) + chr(status_data[2 * i + 14])
            sw_version = bytearray.fromhex(h).decode("utf-8")  # will be overridden
            logger.debug(sw_version)
            self.hardware_version = sw_version
        # ######################### SERIAL NR #############################
        logger.debug("requesting serial nr")
        # 13 + 5 + 40, should be 58, but doesn't ever trigger, so we use 57, that works fine
        status_data = self.read_serial_data_pace(self.command_serial_nr, 97)
        if status_data is False:
            return True
        else:
            h = ""
            for i in range(20):  # 20 byte
                if not (chr(status_data[2 * i + 13]) == "2" and chr(status_data[2 * i + 14] == "0")):
                    h = h + chr(status_data[2 * i + 13]) + chr(status_data[2 * i + 14])
            serial = bytearray.fromhex(h).decode("utf-8")  # will be overridden
            logger.debug(serial)
            self.unique_identifier_tmp = serial

        # Set fet status once, because it is not available from the BMS
        self.charge_fet = True
        self.discharge_fet = True
        self.balance_fet = True

        return True

    def refresh_data(self):
        # call all functions that will refresh the battery data.
        # This will be called for every iteration (1 second)
        # Return True if success, False for failure
        try:
            result = self.read_fuses_data()
            result = result and self.read_status_data()
            return result
        except Exception:
            return False

    def read_fuses_data(self):
        logger.debug("run read_fuses_data()")
        # same here, should be 96 but we have to request 95 .. have to check why
        status_data = self.read_serial_data_pace(self.command_fuses, 95)
        if status_data is False:
            return False
        # ## reset all warnings ###
        # low capacity alarm
        self.protection.low_soc = 0  # not available at pace
        # pack over voltage alarm [done]
        self.protection.high_voltage = 0
        # over current alarm [done]
        self.protection.high_charge_current = 0
        # discharge over current alarm [done]
        self.protection.high_discharge_current = 0
        # unit undervoltage alarm [done]
        self.protection.low_cell_voltage = 0
        # core differential pressure alarm # not implemented
        self.protection.cell_imbalance = 0
        # MOSFET temperature alarm [done]
        self.protection.high_internal_temp = 0
        # battery overtemperature alarm OR overtemperature alarm in the battery box [done]
        self.protection.high_charge_temp = 0
        self.protection.low_temperature = 0
        # check if low/high temp alarm arise during discharging [done]
        self.protection.high_temperature = 0
        self.protection.low_temperature = 0
        # ## reset all warnings ###

        # location of data depends on number of detected cells and detected temp sensors
        cells = int(status_data[17:19], 16)
        temps = int(status_data[19 + cells * 2 : 21 + cells * 2], 16)

        # see protect state below
        # #######################
        #  logger.error("warning cells:"+str(cells))
        # for i in range(0,cells):
        #     logger.error("warning cell "+str(i)+":"+str(int(status_data[19+i*2:21+i*2])))
        #  logger.error("warning temps:"+str(temps))
        # for i in range(0,temps):
        #     logger.error("warning temps "+str(i)+":"+str(int(status_data[21+cells*2+i*2:23+cells*2+i*2])))
        # ########################

        #  See warn bytes below, lets ignore this here
        # pack_charge_current_warn =    int(status_data[23+cells*2+temps*2:23+cells*2+temps*2+2], 16)
        # pack_discharge_current_warn = int(status_data[25+cells*2+temps*2:25+cells*2+temps*2+2], 16)
        # pack_voltage_warn =           int(status_data[24+cells*2+temps*2:24+cells*2+temps*2+2], 16)

        # #### Protect State 1 #####
        # bit0: Cell voltage high
        # bit1: Cell voltage low
        # bit2: Pack voltage high
        # bit3: Pack voltage low
        # bit4: charge current alarm
        # bit5: dischange current alarm
        # bit6: Short circuite
        # discharge under voltage alarm
        protect_state1 = int(status_data[26 + cells * 2 + temps * 2 : 26 + cells * 2 + temps * 2 + 2], 16)
        if protect_state1.to_bytes(1, "big")[0] & b"\x01"[0]:
            self.protection.high_cell_voltage = 2
        if protect_state1.to_bytes(1, "big")[0] & b"\x02"[0]:
            self.protection.low_cell_voltage = 2
        if protect_state1.to_bytes(1, "big")[0] & b"\x04"[0]:
            self.protection.high_voltage = 2
        if protect_state1.to_bytes(1, "big")[0] & b"\x08"[0]:
            self.protection.low_voltage = 2
        if protect_state1.to_bytes(1, "big")[0] & b"\x10"[0]:
            self.protection.high_charge_current = 2
        if protect_state1.to_bytes(1, "big")[0] & b"\x20"[0]:
            self.protection.high_discharge_current = 2
        if protect_state1.to_bytes(1, "big")[0] & b"\x40"[0]:  # short -> over current
            self.protection.high_charge_current = 2
        if protect_state1.to_bytes(1, "big")[0] & b"\x80"[0]:  # discharge under voltage -> voltage low
            self.protection.low_voltage = 2

        # #### Protect State 2 #####
        # bit0: charge temp high
        # bit1: discharge temp high
        # bit2: charge temp low
        # bit3: discharge temp low
        # bit4: MOS temp high
        # bit5: outside temp high
        # bit6: outside temp low
        protect_state2 = int(status_data[27 + cells * 2 + temps * 2 : 27 + cells * 2 + temps * 2 + 2], 16)
        if protect_state2.to_bytes(1, "big")[0] & b"\x01"[0]:
            self.protection.high_charge_temp = 2
        if protect_state2.to_bytes(1, "big")[0] & b"\x02"[0]:
            self.protection.high_temperature = 2
        if protect_state2.to_bytes(1, "big")[0] & b"\x04"[0]:
            self.protection.low_temperature = 2
        if protect_state2.to_bytes(1, "big")[0] & b"\x08"[0]:
            self.protection.low_temperature = 2
        if protect_state2.to_bytes(1, "big")[0] & b"\x10"[0]:
            self.protection.high_internal_temp = 2
        if protect_state2.to_bytes(1, "big")[0] & b"\x20"[0]:
            self.protection.high_charge_temp = 2
            self.protection.high_temperature = 2
        if protect_state2.to_bytes(1, "big")[0] & b"\x40"[0]:
            self.protection.low_temperature = 2
            self.protection.low_temperature = 2

        # instruction_state =           int(status_data[28+cells*2+temps*2:28+cells*2+temps*2+2], 16)
        # control_state =               int(status_data[29+cells*2+temps*2:29+cells*2+temps*2+2], 16)

        # #### Faulty State #####
        # bit0: Charge MOS faulty
        # bit1: Dischange MOS faulty
        # bit2: NTC faulty
        # bit3: undefined
        # bit4: Cell faulty
        # bit5: Sample fault
        fault_state = int(status_data[30 + cells * 2 + temps * 2 : 30 + cells * 2 + temps * 2 + 2], 16)
        if fault_state.to_bytes(1, "big")[0] & b"\x01"[0]:
            logger.error("Charge MOS fault")
        if fault_state.to_bytes(1, "big")[0] & b"\x02"[0]:
            logger.error("Discharge MOS fault")
        if fault_state.to_bytes(1, "big")[0] & b"\x04"[0]:
            logger.error("NTC fault")
        if fault_state.to_bytes(1, "big")[0] & b"\x10"[0]:
            logger.error("Cell fault")
        if fault_state.to_bytes(1, "big")[0] & b"\x20"[0]:
            logger.error("Sample fault")

        # ##### Calance State #####
        balance_state1 = int(status_data[31 + cells * 2 + temps * 2 : 31 + cells * 2 + temps * 2 + 2], 16)
        # cell 0..7
        balance_state2 = int(status_data[32 + cells * 2 + temps * 2 : 32 + cells * 2 + temps * 2 + 2], 16)
        # cell 8..15
        mask1 = b"\x01"[0]
        mask2 = b"\x10"[0]
        for c in range(8):
            if len(self.cells) >= c:
                if balance_state1.to_bytes(1, "big")[0] & mask1:
                    self.cells[c].balance = True
                else:
                    self.cells[c].balance = False
            if len(self.cells) >= c + 8:
                if balance_state2.to_bytes(1, "big")[0] & mask2:
                    self.cells[c + 8].balance = True
                else:
                    self.cells[c + 8].balance = False
            mask1 = mask1 << 1
            mask2 = mask2 << 1

        # #### Warn State 1 #####
        # bit0: cell voltage high
        # bit1: cell voltage low
        # bit2: pack voltage high
        # bit3: pack voltage low
        # bit4: charge current high
        # bit5: discharge current high
        warn_state1 = int(status_data[33 + cells * 2 + temps * 2 : 33 + cells * 2 + temps * 2 + 2], 16)
        if protect_state1.to_bytes(1, "big")[0] & b"\x01"[0]:
            self.protection.high_cell_voltage = 1
        if protect_state1.to_bytes(1, "big")[0] & b"\x02"[0]:
            self.protection.low_cell_voltage = 1
        if protect_state1.to_bytes(1, "big")[0] & b"\x04"[0]:
            self.protection.high_voltage = 1
        if protect_state1.to_bytes(1, "big")[0] & b"\x08"[0]:
            self.protection.low_voltage = 1
        if protect_state1.to_bytes(1, "big")[0] & b"\x10"[0]:
            self.protection.high_charge_current = 1
        if protect_state1.to_bytes(1, "big")[0] & b"\x20"[0]:
            self.protection.high_discharge_current = 1

        # #### Warn State 2 #####
        # bit0: charge temp high
        # bit1: discharge temp high
        # bit2: charge temp low
        # bit3: discharge temp low
        # bit4: outside temp high
        # bit5: outside temp low
        # bit6: MOS temp high
        # bit7: low power warning
        warn_state2 = int(status_data[34 + cells * 2 + temps * 2 : 34 + cells * 2 + temps * 2 + 2], 16)
        if protect_state2.to_bytes(1, "big")[0] & b"\x01"[0]:
            self.protection.high_charge_temp = 1
        if protect_state2.to_bytes(1, "big")[0] & b"\x02"[0]:
            self.protection.high_temperature = 1
        if protect_state2.to_bytes(1, "big")[0] & b"\x04"[0]:
            self.protection.low_temperature = 1
        if protect_state2.to_bytes(1, "big")[0] & b"\x08"[0]:
            self.protection.low_temperature = 1
        if protect_state2.to_bytes(1, "big")[0] & b"\x10"[0]:
            self.protection.high_internal_temp = 1
        if protect_state2.to_bytes(1, "big")[0] & b"\x20"[0]:
            self.protection.temp_low_internal = 1
        if protect_state2.to_bytes(1, "big")[0] & b"\x40"[0]:
            self.protection.high_charge_temp = 1
            self.protection.high_temperature = 1

        # logger.debug("Pack charg current warn "+str(pack_charge_current_warn))
        # logger.debug("Pack voltage current warn "+str(pack_voltage_warn))
        # logger.debug("Pack discharg current warn "+str(pack_discharge_current_warn))
        logger.debug("Protect state 1 " + str(protect_state1))
        logger.debug("Protect state 2 " + str(protect_state2))
        # logger.debug("Instruction state "+str(instruction_state))
        # logger.debug("control state "+str(control_state))
        logger.debug("fault state " + str(fault_state))
        logger.debug("balance state 1 " + str(balance_state1))
        logger.debug("balance state 2 " + str(balance_state2))
        logger.debug("warn state 1 " + str(warn_state1))
        logger.debug("warn state 2 " + str(warn_state2))

        return True

    def read_status_data(self):
        logger.debug("run read_status_data()")
        status_data = self.read_serial_data_pace(self.command_status, 160)
        # check if connection success
        if status_data is False:
            return False

        #        logger.error("sucess we have data")
        #        be = ''.join(format(x, ' 02X') for x in status_data)
        #        logger.error(be)

        self.cell_count = int(status_data[17:19], 16)
        logger.debug("Cellcount: " + str(self.cell_count))

        for i in range(0, self.cell_count):
            n_v = int(status_data[19 + i * 4 : 19 + i * 4 + 4], 16) / 1000
            if self.cells[i].voltage is None or self.cells[i].voltage == 0:
                self.cells[i].voltage = n_v
                logger.debug("NOT low passing " + str(self.cells[i].voltage))
            else:
                self.cells[i].voltage = self.cell_voltage_lp * self.cells[i].voltage
                self.cells[i].voltage += (1.0 - self.cell_voltage_lp) * n_v
                logger.debug("low passing " + str(n_v) + " to " + str(self.cells[i].voltage))
            logger.debug("Cell Voltage [" + str(i) + "]: " + str(self.cells[i].voltage))

        temperature_sensor_count = int(status_data[83:85], 16)
        logger.debug("Temp sensor count: " + str(temperature_sensor_count))
        for i in range(0, temperature_sensor_count):
            v = int(status_data[85 + i * 4 : 85 + i * 4 + 4], 16) / 100
            logger.debug("Temperature [" + str(i) + "]: " + str(v))
            if i < 4:  # 0,1,2,3 are internal temps
                self.to_temperature(i + 1, v)
            if i == 4:  # mosfet
                self.to_temperature(0, v)

        # Battery voltage
        self.voltage = int(status_data[113:117], 16) / 1000

        # Battery ampere
        if status_data[109] & 0b1000000:
            self.current = (int(status_data[109:113], 16) - 65535) / 100
        else:
            self.current = int(status_data[109:113], 16) / 100

        # cycles
        self.cycles = int(status_data[127:131], 16)

        # capacity
        self.capacity_remain = int(status_data[117:121], 16) / 100
        self.capacity = int(status_data[123:127], 16) / 100
        logger.debug("Capacity: " + str(self.capacity))
        logger.debug("Remaing capacity: " + str(self.capacity_remain))

        # SOC
        self.soc = self.capacity_remain * 100 / self.capacity

        # TODO?
        # self.charge_fet = True
        # self.discharge_fet = True
        # self.balance_fet = True
        # self.balancing = True

        # logging
        for c in range(self.cell_count):
            logger.debug("Cell " + str(c) + " voltage: " + str(self.cells[c].voltage) + "V")
        logger.debug("voltage: " + str(self.voltage) + "V")
        logger.debug("Current: " + str(self.current))
        logger.debug("SOC: " + str(self.soc) + "%")
        return True

    def unique_identifier(self) -> str:
        """
        Used to identify a BMS when multiple BMS are connected
        """
        return self.unique_identifier_tmp

    def get_min_cell(self):
        min_voltage = 9999
        min_cell = None
        for c in range(min(len(self.cells), self.cell_count)):
            if self.cells[c].voltage is not None and min_voltage > self.cells[c].voltage:
                min_voltage = self.cells[c].voltage
                min_cell = c
        return min_cell

    def get_max_cell(self):
        max_voltage = 0
        max_cell = None
        for c in range(min(len(self.cells), self.cell_count)):
            if self.cells[c].voltage is not None and max_voltage < self.cells[c].voltage:
                max_voltage = self.cells[c].voltage
                max_cell = c
        return max_cell

    def read_serial_data_pace(self, command: str, length: int) -> bool:
        """
        use the read_serial_data() function to read the data and then do BMS specific checks (crc, start bytes, etc)
        :param command: the command to be sent to the bms
        :return: True if everything is fine, else False
        """
        data = read_serial_data(
            command,
            self.port,
            self.baud_rate,
            self.LENGTH_POS,  # ignored
            self.LENGTH_CHECK,  # ignored
            length,
            self.LENGTH_SIZE,  # ignored
        )
        if data is False:
            return False

        if data[0] == 0x7E:
            logger.debug("SOI found")
            logger.debug("Version: " + chr(data[1]) + chr(data[2]))
            logger.debug("Adr: " + chr(data[3]) + chr(data[4]))
            payload_length = int(data[10:13], 16)
            if len(data) >= (13 + payload_length + 5):
                # CRC check
                cal_chk = 0
                for i in range(1, len(data) - 5):
                    cal_chk += data[i]
                cal_chk = 0xFFFF - cal_chk % 65536 + 1
                # CRC check
                if cal_chk == int(data[-5:-1], 16):
                    logger.debug("CRC correct, return data")
                    return data
                else:
                    logger.error(">>>ERROR: CRC incorrect")
            else:
                logger.error(">>> ERROR: length incorrect, expected " + str(13 + payload_length + 5) + " but received " + str(len(data)))
                return False
        else:
            logger.error(">>> ERROR: Incorrect Startbyte ")
            return False
