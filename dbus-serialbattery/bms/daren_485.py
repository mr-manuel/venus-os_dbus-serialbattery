# -*- coding: utf-8 -*-

# NOTES
# Added by https://github.com/cpttinkering/venus-os_dbus-serialbattery-daren485
# Adds support for various chinese BMS, based on the 'Daren' BMS,
# e.g. DR-JC03, DR48100JC-03-V2, using the DR-1363 protocol.
# See https://github.com/cpttinkering/daren-485 for protocol research information

# avoid importing wildcards, remove unused imports
from battery import Battery, Cell
from utils import open_serial_port, logger
from time import sleep
from struct import unpack
from re import findall
import sys


class Daren485(Battery):
    def __init__(self, port, baud, address):
        super(Daren485, self).__init__(port, baud, address)
        self.type = self.BATTERYTYPE

        # Uses address to build request commands, so has to be set
        # to address reflecting the position of the DIP-switches on the unit(s), starting at '01'.
        self.address = address
        self.serial_number = ""
        self.history.exclude_values_to_calculate = ["charge_cycles", "total_ah_drawn", "charged_energy", "discharged_energy"]

    BATTERYTYPE = "Daren485"

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
        result = False
        try:
            with open_serial_port(self.port, self.baud_rate) as ser:
                if ser:
                    if ser.is_open:
                        result = self.get_serial(ser)

                        result = result and self.get_cells_params(ser)

                        if result:
                            # init the cell array once
                            if len(self.cells) == 0:
                                for _ in range(self.cell_count):
                                    self.cells.append(Cell(False))

                        result = result and self.get_realtime_data(ser)

                        result = result and self.get_manufacturer_info(ser)

                        result = result and self.get_cap_params(ser)
                    else:
                        logger.error("Error opening serialport!")
                else:
                    logger.error("Error getting serialport!")

        except OSError:
            logger.warning("Couldn't open serial port")

        if not result:  # TROUBLESHOOTING for no reply errors
            logger.debug(f"get_settings: result: {result}." + " If you don't see this warning very often, you can ignore it.")
            logger.error(">>> ERROR: No reply - returning")

        return result

    def refresh_data(self):
        """
        call all functions that will refresh the battery data.
        This will be called for every iteration (1 second)
        Return True if success, False for failure
        """
        result = False
        try:
            with open_serial_port(self.port, self.baud_rate) as ser:
                if ser:
                    if ser.is_open:
                        result = self.get_realtime_data(ser)

                        # get cells_params to get max (dis)charge params,
                        # but use the FET status registers from realtime data
                        # to set them to 0 when needed.
                        result = result and self.get_cells_params(ser)

                        result = result and self.get_cap_params(ser)
                    else:
                        logger.error("Error opening serialport!")
                else:
                    logger.error("Error getting serialport!")

        except OSError:
            logger.warning("Couldn't open serial port")

        if not result:  # TROUBLESHOOTING for no reply errors
            logger.info(f"refresh_data: result: {result}." + " If you don't see this warning very often, you can ignore it.")

        return result

    def get_serial(self, ser):
        """
        Read serial from device by calling the get_mfg_params command,
        using service B0, module 3 and extracting the SN.
        """
        result = False

        req = self.create_command_get_mfg_params()

        ser.flushOutput()
        ser.flushInput()
        ser.write(req.encode())
        logger.debug("get_mfg_params request sent: {}".format(req))

        sleep(0.4)  # Allow the BMS some time to send a full response

        response = self.read_response(ser)

        if response:
            # Payload starts at offset 13(packet header) + 12 (command_info)
            payload = response[(13 + 12) : len(response) - 5]
            if len(payload) >= 30:
                serial_byte_array = bytearray.fromhex(payload[0:30])
                self.serial_number = serial_byte_array.decode()
                logger.info("get_serial: {}".format(self.serial_number))

                result = True
            else:
                logger.error("get_serial response length error!")
        else:
            logger.debug("get_serial response error!")

        return result

    def get_cap_params(self, ser):
        """
        Read capacity information from device by calling the get_cap_params command,
        using service B0, module 4 and extracting the (historic) capacity information.
        """
        result = False

        req = self.create_command_get_cap_params()

        ser.flushOutput()
        ser.flushInput()
        ser.write(req.encode())
        logger.debug("get_cap_params request sent: {}".format(req))

        sleep(0.4)  # Allow the BMS some time to send a full response

        response = self.read_response(ser)

        if response:
            # Payload starts at offset 13(packet header) + 12 (command_info)
            payload = response[(13 + 12) : len(response) - 5]
            if len(payload) >= 36:  # 9*4 bytes in full request.
                self.capacity_remaining = int(int(payload[0:4], base=16) / 100)
                self.capacity = int(int(payload[4:8], base=16) / 100)
                # design_capacity = int(payload[8:12], base=16) / 100 #Not used, for future use.
                # total_charge_capacity = int(payload[12:20], base=16) / 100 #Not used, for future use.
                # total_discharge_capacity
                self.history.total_ah_drawn = int(payload[20:28], base=16)
                self.history.charged_energy = int(int(payload[28:32], base=16) / 10)
                self.history.discharged_energy = int(int(payload[32:36], base=16) / 10)

                result = True
            else:
                logger.error("get_cap_params response length error!")
        else:
            logger.error("get_cap_params response error!")

        return result

    def get_realtime_data(self, ser):
        """
        Read realtime data from device by calling the get_realtime_data command,
        using service 42 and extracting the majority of the available data,
        such as SOC, voltages, current, temperatures and alarms/warnings/statusinformation.
        """
        result = False

        req = self.create_command_get_realtime_data()

        ser.flushOutput()
        ser.flushInput()
        ser.write(req.encode())
        logger.debug("get_realtime_data request sent: {}".format(req))

        sleep(0.5)  # Allow the BMS some time to send a full response

        response = self.read_response(ser)

        if response:
            payload = response[13 : len(response) - 5]
            if len(payload) >= 118:
                self.soc = int(payload[2:6], base=16) / 100
                self.voltage = int(payload[6:10], base=16) / 100
                self.current = unpack(">h", bytes.fromhex(payload[106:110]))[0] / 100
                temperature_mos = unpack(">h", bytes.fromhex(payload[84:88]))[0] / 10
                self.to_temperature(0, temperature_mos)
                temperature_1 = unpack(">h", bytes.fromhex(payload[90:94]))[0] / 10
                self.to_temperature(1, temperature_1)
                temperature_2 = unpack(">h", bytes.fromhex(payload[94:98]))[0] / 10
                self.to_temperature(2, temperature_2)
                temperature_3 = unpack(">h", bytes.fromhex(payload[98:102]))[0] / 10
                self.to_temperature(3, temperature_3)
                temperature_4 = unpack(">h", bytes.fromhex(payload[102:106]))[0] / 10
                self.to_temperature(4, temperature_4)
                self.capacity = int(payload[120:124], base=16) / 100
                self.capacity_remaining = int(payload[124:128], base=16) / 100
                self.history.charge_cycles = int(payload[128:132], base=16)
                fetstatus = int(payload[148:152], base=16)

                voltagestatus = int(payload[132:136], base=16)
                currentstatus = int(payload[136:140], base=16)
                temperaturestatus = int(payload[140:144], base=16)
                warningstatus = int(payload[144:148], base=16)

                # check bit 2 for TOT_OVV_PROT and bit 0 for cell_OVV_PROT
                if voltagestatus & (1 << 2) or voltagestatus & (1 << 0):
                    self.protection.high_voltage = 2
                # check bit 6 for TOT_OVV_alarm and 4 for cell_OVV_alarm
                elif voltagestatus & (1 << 6) or voltagestatus & (1 << 4):
                    self.protection.high_voltage = 1
                else:
                    self.protection.high_voltage = 0
                # NOTE: high_voltage_cell not implemented.
                # Now incorporated in voltage_high alarm.
                # Split if high_voltage_cell ever implemented.

                # check bit 3 for TOT_UNDV_PROT
                if voltagestatus & (1 << 3):
                    self.protection.low_voltage = 2
                # check bit 7 for TOT_UNDV_alarm
                elif voltagestatus & (1 << 7):
                    self.protection.low_voltage = 1
                else:
                    self.protection.low_voltage = 0

                # check bit 1 for cell_UNDV_PROT
                if voltagestatus & (1 << 1):
                    self.protection.low_cell_voltage = 2
                # check bit 5 for cell_UNDV_alarm
                elif voltagestatus & (1 << 5):
                    self.protection.low_cell_voltage = 1
                else:
                    self.protection.low_cell_voltage = 0

                # check bit 7 for low_BAT_alarm from warningstatus
                if warningstatus & (1 << 7):
                    self.protection.low_soc = 2
                else:
                    self.protection.low_soc = 0

                # check bit 2 for CHG_OC_PROT
                if currentstatus & (1 << 2):
                    self.protection.high_charge_current = 2
                # check bit 6 for CHG_C_alarm
                elif currentstatus & (1 << 6):
                    self.protection.high_charge_current = 1
                else:
                    self.protection.high_charge_current = 0

                # check bit 4 for DISCH_OC_1_PROT, bit 5 for DISCH_OC_2_PROT and bit 3 for Short_circuit_PROT
                if currentstatus & (1 << 4) or currentstatus & (1 << 5) or currentstatus & (1 << 3):
                    self.protection.high_discharge_current = 2
                # check bit 7 for DISCH_C_alarm
                elif currentstatus & (1 << 7):
                    self.protection.high_discharge_current = 1
                else:
                    self.protection.high_discharge_current = 0

                # check bit 14 for V_DIF_PROT
                if voltagestatus & (1 << 14):
                    self.protection.cell_imbalance = 2
                # check bit 8 for V_DIF_ALARM
                elif voltagestatus & (1 << 8):
                    self.protection.cell_imbalance = 1
                else:
                    self.protection.cell_imbalance = 0

                # if something else is in warning, report internal failure. warningstatus
                # contains all sorts of internal components, such as CHG_FET, NTC_fail,
                # cell_fail, chg_mos_fail, disch_mos_fail, etc.
                # Ignore V_DIF_alarm and low_BAT_alarm flags, since we're allready checking for those.
                if (warningstatus & 0b01111110) > 0:
                    self.protection.internal_failure = 2
                else:
                    self.protection.internal_failure = 0

                # check bit 0 for CHG_H_TEMP_PROT
                if temperaturestatus & (1 << 0):
                    self.protection.high_charge_temperature = 2
                # check bit 8 for CHG_H_TEMP_alarm
                elif temperaturestatus & (1 << 8):
                    self.protection.high_charge_temperature = 1
                else:
                    self.protection.high_charge_temperature = 0

                # check bit 1 for CHG_L_TEMP_PROT
                if temperaturestatus & (1 << 1):
                    self.protection.low_charge_temperature = 2
                # check bit 9 for CHG_L_TEMP_alarm
                elif temperaturestatus & (1 << 9):
                    self.protection.low_charge_temperature = 1
                else:
                    self.protection.low_charge_temperature = 0

                # check bit 0 for CHG_H_TEMP_PROT and bit 2 for DISCH_H_TEMP_PROT
                if temperaturestatus & (1 << 0) or temperaturestatus & (1 << 2):
                    self.protection.high_temperature = 2
                # check bit 8 for CHG_H_TEMP_alarm and bit 10 for DISCH_H_TEMP_alarm
                elif temperaturestatus & (1 << 8) or temperaturestatus & (1 << 10):
                    self.protection.high_temperature = 1
                else:
                    self.protection.high_temperature = 0

                # check bit 1 for CHG_L_TEMP_PROT and bit 3 for DISCH_L_TEMP_PROT
                if temperaturestatus & (1 << 1) or temperaturestatus & (1 << 3):
                    self.protection.low_temperature = 2
                # check bit 9 for CHG_L_TEMP_alarm and bit 11 for DISCH_L_TEMP_alarm
                elif temperaturestatus & (1 << 9) or temperaturestatus & (1 << 11):
                    self.protection.low_temperature = 1
                else:
                    self.protection.low_temperature = 0

                # check bit 6 for MOS_H_TEMP_PROT and 4 for ENV_H_TEMP_PROT
                if temperaturestatus & (1 << 6) or temperaturestatus & (1 << 4):
                    self.protection.high_internal_temperature = 2
                # check bit 14 for MOS_H_TEMP_alarm and 12 for ENV_H_TEMP_alarm
                elif temperaturestatus & (1 << 14) or temperaturestatus & (1 << 12):
                    self.protection.high_internal_temperature = 1
                else:
                    self.protection.high_internal_temperature = 0

                # check bit 13 for blown_fuse from voltagestatus
                if voltagestatus & (1 << 13):
                    self.protection.fuse_blown = 2
                else:
                    self.protection.fuse_blown = 0

                if fetstatus & (1 << 0):
                    self.charge_fet = True
                else:
                    self.charge_fet = False
                    self.max_battery_charge_current = 0

                if fetstatus & (1 << 1):
                    self.discharge_fet = True
                else:
                    self.discharge_fet = False
                    self.max_battery_discharge_current = 0

                for i in range(1, 17):
                    cell_voltage = int(payload[(i - 1) * 4 + 12 : i * 4 + 12], base=16) / 1000
                    self.cells[i - 1].voltage = cell_voltage

                result = True
            else:
                logger.error("get_realtime_data response length error!")
        else:
            logger.error("get_realtime_data response error!")

        return result

    def get_manufacturer_info(self, ser):
        """
        Read manufacturer info from device by calling the get_manufacturer_info command,
        using service 51 and extracting hardware-type, product information and sw-versions.
        """
        result = False

        req = self.create_command_get_manufacturer_info()

        ser.flushOutput()
        ser.flushInput()
        ser.write(req.encode())
        logger.debug("get_manufacturer_info request sent: {}".format(req))

        sleep(0.4)  # Allow the BMS some time to send a full response

        response = self.read_response(ser)

        if response:
            payload = response[13 : len(response) - 5]
            if len(payload) >= (3 * 20) + 10:
                hardware_type_byte_array = bytearray.fromhex(payload[0:20])
                hardware_type = hardware_type_byte_array.decode().replace("\0", "").strip()

                product_code_byte_array = bytearray.fromhex(payload[20:40])
                product_code = product_code_byte_array.decode().replace("\0", "").strip()

                project_code_byte_array = bytearray.fromhex(payload[40:60])
                project_code = project_code_byte_array.decode().replace("\0", "").strip()

                software_version_array = findall("..", payload[60:66])
                seperator = "."
                software_version = seperator.join(software_version_array)
                self.hardware_version = product_code + " "
                self.hardware_version += project_code + " "
                self.hardware_version += hardware_type + " "
                self.hardware_version += software_version + " "
                logger.info("set hardware_version: {}".format(self.hardware_version))

                result = True
            else:
                logger.error("get_manufacturer_info response length error!")
        else:
            logger.error("get_manufacturer_info response error!")

        return result

    def get_cells_params(self, ser):
        """
        Read cell-count and system params from device by calling the get_cells_params command,
        using service 47 and extracting cellcount, charge limit and potentially more limitparams.
        """
        result = False

        req = self.create_command_get_cells_params()

        ser.flushOutput()
        ser.flushInput()
        ser.write(req.encode())
        logger.debug("get_cells_params request sent: {}".format(req))

        sleep(0.4)  # Allow the BMS some time to send a full response

        response = self.read_response(ser)

        if response:
            payload = response[13 : len(response) - 5]
            if len(payload) >= 129:
                # cell_v_upper_limit = int(payload[2:6], base=16) / 1000
                # cell_V_lower_limit = int(payload[6:10], base=16) / 1000
                # upper_TEMP_limit = int(payload[10:14], base=16)
                # lower_TEMP_limit = int(payload[14:18], base=16)
                # upper_limit_of_CHG_C = int(payload[18:22], base=16) / 100
                # TOT_V_upper_limit = int(payload[22:26], base=16) / 1000
                # TOT_V_lower_limit = int(payload[26:30], base=16) / 1000
                num_of_cells = int(payload[30:34], base=16)
                CHG_C_limit = int(int(payload[34:38], base=16) / 100)
                # design_capacity_none = int(payload[38:42], base=16) / 100
                # historical_data_storage_interval = int(payload[42:46], base=16)
                # balanced_mode = int(payload[46:50], base=16)
                # product_barcode_byte_array = bytearray.fromhex(payload[50:90])
                # product_barcode = product_barcode_byte_array.decode()
                # BMS_barcode_byte_array = bytearray.fromhex(payload[90:130])
                # BMS_barcode = BMS_barcode_byte_array.decode()

                self.cell_count = num_of_cells
                if self.charge_fet is True:
                    self.max_battery_charge_current = CHG_C_limit
                else:
                    self.max_battery_charge_current = 0
                if self.discharge_fet is True:
                    self.max_battery_discharge_current = CHG_C_limit
                else:
                    self.max_battery_discharge_current = 0

                result = True
            else:
                logger.error("get_cells_params response length error!")
        else:
            logger.error("get_cells_params response error!")

        return result

    def read_response(self, ser):
        """
        After sending the command to the device, this service processes
        the receive buffer and performs basic parsing and validation of received data.
        """
        buff = ""

        while ser.inWaiting() > 0:
            try:
                chr = ser.read()
                buff += chr.decode()
                if chr == b"\r":
                    break
            except Exception as e:
                logger.error("Exception during inWaiting(): {}".format(e))
                pass

        try:
            CID2 = buff[7:9]
            if self.CID2_decode(CID2) == -1:
                logger.debug("CID2_Decode error!")
                logger.debug("Buffer contents: {}".format(buff))
                return False
        except Exception as e:
            logger.error("read_response Data invalid!: {}".format(e))
            logger.error("Received data: {}".format(buff))
            return False

        logger.debug("Received data: {}".format(buff))

        try:
            LENID = int(buff[9:13], base=16)
            length = LENID & 0x0FFF
            if self.length_checksum(length) == LENID:
                logger.debug("Data length ok.")
            else:
                logger.error("Data length error.")
                return False
        except Exception as e:
            logger.error("Exception during data length check: {}".format(e))
            logger.error("Received data: {}".format(buff))
            return False

        try:
            chksum = int(buff[len(buff) - 5 :], base=16)
            calculated_chksum = self.calculate_checksum(buff[1 : len(buff) - 5])
            if calculated_chksum == chksum:
                logger.debug("Checksum ok.")
            else:
                logger.error("Checksum error. Calculated: {}, Received: {}".format(calculated_chksum, chksum))
                return False

        except Exception as e:
            logger.error("Exception during checksum calculation: {}".format(e))
            return False

        logger.debug("read_response Data valid!")
        return buff

    def create_command_get_cells_params(self):
        """
        Generates command that utilizes Service 47 of the BMS.
        Example command (mark the \r at the end):
        ~22014A47E00201FD23␍
        """
        return self.create_command(self.address, b"\x4A", b"\x47", self.address.hex().upper())

    def create_command_get_mfg_params(self):
        """
        Generates command that utilizes Service B0, module 3 of the BMS.
        Example command (mark the \r at the end):
        ~22014AB0600A010103FF00FB6C␍
        """
        commandinfo = ""
        commandinfo += self.address.hex().upper()  # commandgroup
        commandinfo += "01"  # operation
        # module (01 = OCV_Param, 02, HW_PROT, 03=MFG_Params, 04=CAP_params)
        commandinfo += "03"
        commandinfo += "FF"  # functionid
        commandinfo += "00"  # functionLEN
        return self.create_command(self.address, b"\x4A", b"\xB0", commandinfo)

    def create_command_get_cap_params(self):
        """
        Generates command that utilizes Service B0, module 4 of the BMS.
        Example command (mark the \r at the end):
        ~22014AB0600A010104FF00FB6B␍
        """
        commandinfo = ""
        commandinfo += self.address.hex().upper()  # commandgroup
        commandinfo += "01"  # operation
        # module (01 = OCV_Param, 02, HW_PROT, 03=MFG_Params, 04=CAP_params)
        commandinfo += "04"
        commandinfo += "FF"  # functionid
        commandinfo += "00"  # functionLEN
        return self.create_command(self.address, b"\x4A", b"\xB0", commandinfo)

    def create_command_get_realtime_data(self):
        """
        Generates command that utilizes Service 42 of the BMS.
        Example command (mark the \r at the end):
        ~22014A42E00201FD28␍
        """
        return self.create_command(self.address, b"\x4A", b"\x42", self.address.hex().upper())

    def create_command_get_manufacturer_info(self):
        """
        Generates command that utilizes Service 51 of the BMS.
        Example command (mark the \r at the end):
        ~22014A510000FDA0␍
        """
        return self.create_command(self.address, b"\x4A", b"\x51")

    def create_command(self, addr, cid1, cid2, info=""):
        command = ""
        command += "~"  # B1=SOI
        command += "22"  # B2=Version
        command += addr.hex().upper()  # B3=ADDR
        command += cid1.hex().upper()  # B4=CID1
        command += cid2.hex().upper()  # B5=CID2

        if len(info) > 0:
            length = len(info)
            length = self.length_checksum(length)
            command += format(length, "x").upper()
            command += info
        else:
            command += "0000"  # Length = 0, LenID=0, Lchecksum=0
        checksum = self.calculate_checksum(command[1 : len(command)])

        command += format(checksum, "x").upper()
        command += "\r"  # Last Byte=EOI, \r

        # logger.info("Command: {}".format(command))
        return command

    def calculate_checksum(self, str):
        checksum = 0
        for value in str:
            checksum = checksum + ord(value)
        checksum = checksum ^ 0xFFFF
        return checksum + 1

    # creates length + checksum from length val in two byte integer
    def length_checksum(self, value):
        value = value & 0x0FFF
        n1 = value & 0xF
        n2 = (value >> 4) & 0xF
        n3 = (value >> 8) & 0xF
        chksum = ((n1 + n2 + n3) & 0xF) ^ 0xF
        chksum = chksum + 1
        return value + (chksum << 12)

    def CID2_decode(self, CID2):
        if CID2 == "00":
            logger.debug("CID2 response ok.")
            return 0
        elif CID2 == "01":
            logger.error("VER error.")
        elif CID2 == "02":
            logger.error("CHKSUM error.")
        elif CID2 == "03":
            logger.error("LCHKSUM error.")
        elif CID2 == "04":
            logger.error("CID2 invalid.")
        elif CID2 == "05":
            logger.error("Command format error.")
        elif CID2 == "06":
            logger.error("INFO data invalid.")
        elif CID2 == "90":
            logger.error("ADR error.")
        elif CID2 == "91":
            logger.error("Battery communication error.")
        return -1
