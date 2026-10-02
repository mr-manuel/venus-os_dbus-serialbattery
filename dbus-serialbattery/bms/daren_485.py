# -*- coding: utf-8 -*-

# NOTES
# Added by https://github.com/cpttinkering/venus-os_dbus-serialbattery-daren485
# Adds support for various chinese BMS, based on the 'Daren' BMS,
# e.g. DR-JC03, DR48100JC-03-V2, using the DR-1363 protocol.
# See https://github.com/cpttinkering/daren-485 for protocol research information

# avoid importing wildcards, remove unused imports
from battery import Battery, Cell
from utils import SOC_CALCULATION, open_serial_port, get_connection_error_message, logger, capture_raw_data
from time import monotonic, sleep
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
        self.balanced_mode = None
        self._last_balance_mask = None
        self._last_balance_status = None
        self._balance_fet_off_since = None
        self._cell_balance_off_since = {}
        self.history.exclude_values_to_calculate = ["charge_cycles", "total_ah_drawn", "charged_energy", "discharged_energy"]

    BATTERYTYPE = "Daren485"
    BALANCE_OFF_DELAY_SECONDS = 10

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

                        # Read balancing configuration once at startup. This is optional
                        # and must not prevent the driver from starting if Service 0x80 is unsupported.
                        self.get_balance_params(ser)
                    else:
                        logger.error("Error opening serialport!")
                else:
                    logger.error("Error getting serialport!")

        except OSError:
            logger.warning("Couldn't open serial port")

        if not result:  # TROUBLESHOOTING for no reply errors
            logger.debug(f"get_settings: result: {result}." + " If you don't see this warning very often, you can ignore it.")
            get_connection_error_message(self.online)

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
        capture_raw_data(ser.port, "tx", req)
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
        capture_raw_data(ser.port, "tx", req)
        logger.debug("get_cap_params request sent: {}".format(req))

        sleep(0.4)  # Allow the BMS some time to send a full response

        response = self.read_response(ser)

        if response:
            # Payload starts at offset 13(packet header) + 12 (command_info)
            payload = response[(13 + 12) : len(response) - 5]
            if len(payload) >= 36:  # 9*4 bytes in full request.
                self.capacity_remain = int(int(payload[0:4], base=16) / 100)
                self.capacity = int(int(payload[4:8], base=16) / 100)
                # design_capacity = int(payload[8:12], base=16) / 100 #Not used, for future use.
                # total_charge_capacity = int(payload[12:20], base=16) / 100 #Not used, for future use.
                # total_discharge_capacity
                self.history.total_ah_drawn = int(payload[20:28], base=16)
                self.history.charged_energy = int(int(payload[28:32], base=16) / 100)
                self.history.discharged_energy = int(int(payload[32:36], base=16) / 100)

                result = True
            else:
                logger.error("get_cap_params response length error!")
        else:
            logger.error("get_cap_params response error!")

        return result

    def get_realtime_data(self, ser):
        """
        Read realtime data from device by calling the get_realtime_data command,
        using service 42 and extracting runtime data.

        The DATAI structure is variable: the offsets after the cell voltages depend
        on the reported cell count, and the offsets after the temperatures depend on
        the reported temperature sensor count. Parse sequentially instead of assuming
        a fixed 16S / 4-temperature layout.
        """
        result = False

        req = self.create_command_get_realtime_data()

        ser.flushOutput()
        ser.flushInput()
        ser.write(req.encode())
        capture_raw_data(ser.port, "tx", req)
        logger.debug("get_realtime_data request sent: {}".format(req))

        sleep(0.5)  # Allow the BMS some time to send a full response

        response = self.read_response(ser)

        if not response:
            logger.error("get_realtime_data response error!")
            return False

        payload = response[13 : len(response) - 5]
        pos = 0

        def take(chars, field_name):
            nonlocal pos
            if pos + chars > len(payload):
                raise ValueError(
                    "get_realtime_data response too short while reading {}: "
                    "need {} chars at offset {}, payload has {}".format(field_name, chars, pos, len(payload))
                )
            value = payload[pos : pos + chars]
            pos += chars
            return value

        def read_u8(field_name):
            return int(take(2, field_name), base=16)

        def read_u16(field_name):
            return int(take(4, field_name), base=16)

        def read_i16(field_name):
            return unpack(">h", bytes.fromhex(take(4, field_name)))[0]

        try:
            # DATAFLAG
            read_u8("dataflag")

            self.soc = read_u16("soc") / 100
            self.voltage = read_u16("pack_voltage") / 100

            realtime_cell_count = read_u8("cell_count")
            if realtime_cell_count <= 0 or realtime_cell_count > 32:
                raise ValueError("invalid cell count {}".format(realtime_cell_count))

            # get_cells_params() normally initializes cell_count and self.cells before
            # Service 0x42 is read. Do not resize an already published cell array at
            # runtime, since D-Bus cell paths are created from that initial array.
            if self.cell_count is None:
                self.cell_count = realtime_cell_count

            if realtime_cell_count != self.cell_count:
                raise ValueError("Service 42 cell count ({}) differs from configured cell count ({})".format(realtime_cell_count, self.cell_count))

            if len(self.cells) == 0:
                for _ in range(self.cell_count):
                    self.cells.append(Cell(False))
            elif len(self.cells) != self.cell_count:
                raise ValueError("cell array length ({}) differs from configured cell count ({})".format(len(self.cells), self.cell_count))

            for i in range(realtime_cell_count):
                self.cells[i].voltage = read_u16("cell_voltage_{}".format(i + 1)) / 1000

            # These two values are part of the frame but dbus-serialbattery does not
            # currently expose dedicated fields for them.
            temperature_ambient = read_i16("ambient_temperature") / 10
            temperature_pack = read_i16("pack_temperature") / 10
            temperature_mos = read_i16("mos_temperature") / 10
            self.to_temperature(0, temperature_mos)

            temperature_count = read_u8("temperature_count")
            if temperature_count > 32:
                raise ValueError("invalid temperature sensor count {}".format(temperature_count))

            for i in range(temperature_count):
                temperature = read_i16("temperature_{}".format(i + 1)) / 10
                # Battery exposes four generic battery temperature slots. Consume any
                # additional sensors to keep the payload aligned, but publish only 1..4.
                if i < 4:
                    self.to_temperature(i + 1, temperature)

            self.current = read_i16("pack_current") / 100

            # Pack internal resistance is currently not exposed by Battery, but it
            # must be consumed to keep all following fields aligned.
            pack_internal_resistance = read_u16("pack_internal_resistance") / 10

            # SOH is a raw 16-bit percentage value. The manufacturer's application
            # does NOT divide this field by 10 or 100.
            self.soh = read_u16("soh")

            # user_custom is currently not used, but is part of DATAI.
            user_custom = read_u8("user_custom")

            self.capacity = read_u16("full_capacity") / 100
            self.capacity_remain = read_u16("remaining_capacity") / 100
            self.history.charge_cycles = read_u16("charge_cycles")

            voltagestatus = read_u16("voltage_status")
            currentstatus = read_u16("current_status")
            temperaturestatus = read_u16("temperature_status")
            warningstatus = read_u16("warning_status")
            fetstatus = read_u16("fet_status")

            # Per-cell protection/alarm masks (LOW 16 bits). These values are not
            # currently mapped to dbus-serialbattery properties, but are consumed so
            # the following balance masks are read at the correct position.
            read_u16("cell_overvoltage_protection_low")
            read_u16("cell_undervoltage_protection_low")
            read_u16("cell_overvoltage_alarm_low")
            read_u16("cell_undervoltage_alarm_low")

            # Manufacturer Service 42 returns two 16-bit balance masks.
            # LOW covers cells 1..16, HIGH covers cells 17..32. Bit 0 maps to the
            # first cell in each group.
            balance_low = read_u16("cell_balance_low")
            balance_high = read_u16("cell_balance_high")
            balance_mask = balance_low | (balance_high << 16)

            # Service 0x42 reports short balancing pulses. Assert balancing immediately,
            # but keep the global and per-cell states active until the raw bit has
            # remained clear continuously for BALANCE_OFF_DELAY_SECONDS.
            self._update_balancing_status(balance_mask)
            self._log_balance_status(balance_mask)

            logger.debug(
                "Daren realtime: cells={}, temp_sensors={}, ambient={}C, pack={}C, "
                "MOS={}C, internal_resistance={}, user_custom={}, balance=0x{:08X}".format(
                    self.cell_count,
                    temperature_count,
                    temperature_ambient,
                    temperature_pack,
                    temperature_mos,
                    pack_internal_resistance,
                    user_custom,
                    balance_mask,
                )
            )

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
            if not SOC_CALCULATION:
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

            result = True

        except (ValueError, TypeError) as e:
            logger.error("get_realtime_data response parsing error: {}".format(e))
            logger.debug("get_realtime_data payload: {}".format(payload))
            result = False

        return result

    def _update_balancing_status(self, balance_mask):
        """
        Debounce the OFF state of the pulsed Service 0x42 balancing bits.

        A reported active bit is applied immediately. Once the raw bit clears, the
        corresponding cell and aggregate balance states remain active until the bit
        has stayed clear continuously for BALANCE_OFF_DELAY_SECONDS.
        """
        now = monotonic()

        for i in range(self.cell_count):
            raw_active = bool(balance_mask & (1 << i))

            if raw_active:
                self.cells[i].balance = True
                self._cell_balance_off_since.pop(i, None)
            elif self.cells[i].balance:
                off_since = self._cell_balance_off_since.get(i)
                if off_since is None:
                    self._cell_balance_off_since[i] = now
                elif now - off_since >= self.BALANCE_OFF_DELAY_SECONDS:
                    self.cells[i].balance = False
                    self._cell_balance_off_since.pop(i, None)
            else:
                self._cell_balance_off_since.pop(i, None)

        if balance_mask != 0:
            self.balance_fet = True
            self._balance_fet_off_since = None
        elif self.balance_fet:
            if self._balance_fet_off_since is None:
                self._balance_fet_off_since = now
            elif now - self._balance_fet_off_since >= self.BALANCE_OFF_DELAY_SECONDS:
                self.balance_fet = False
                self._balance_fet_off_since = None
        else:
            if self.balance_fet is None:
                self.balance_fet = False
            self._balance_fet_off_since = None

    def _log_balance_status(self, balance_mask=None):
        """Log balancing state on first observation and whenever mode or mask changes."""
        if balance_mask is not None:
            self._last_balance_mask = balance_mask

        if self._last_balance_mask is None:
            return

        status = (self.balanced_mode, self._last_balance_mask)
        if status == self._last_balance_status:
            return

        active_cells = [str(i + 1) for i in range(self.cell_count) if self._last_balance_mask & (1 << i)]
        active_cells_text = ",".join(active_cells) if active_cells else "none"
        mode_text = str(self.balanced_mode) if self.balanced_mode is not None else "unknown"

        logger.debug(
            "BALANCE STATUS: mode={} | mask=0x{:08X} | active cells: {}".format(
                mode_text,
                self._last_balance_mask,
                active_cells_text,
            )
        )
        self._last_balance_status = status

    def get_balance_params(self, ser):
        """
        Read balancing configuration once at startup using Service 0x80.

        The manufacturer parser stores these four values as 16-bit fields:
        balance high temperature, balance low temperature (signed),
        balance starting voltage and balance starting voltage difference.
        """
        req = self.create_command_get_balance_params()

        ser.flushOutput()
        ser.flushInput()
        ser.write(req.encode())
        capture_raw_data(ser.port, "tx", req)
        logger.debug("get_balance_params request sent: {}".format(req))

        # Service 0x80 returns a comparatively long response. At 9600 baud it needs
        # roughly half a second on the wire, so leave some margin before reading.
        sleep(0.8)

        response = self.read_response(ser)

        if not response:
            logger.warning("get_balance_params response error; Service 0x80 may not be supported")
            return False

        payload = response[13 : len(response) - 5]

        # In the manufacturer Service 0x80 parser these are fields 99..102
        # (zero-based indices 98..101), each encoded as two bytes / four hex chars.
        if len(payload) < 408:
            logger.warning("get_balance_params response too short: {} chars, expected at least 408".format(len(payload)))
            logger.debug("get_balance_params payload: {}".format(payload))
            return False

        try:
            balance_high_temp = int(payload[392:396], base=16)
            balance_low_temp = unpack(">h", bytes.fromhex(payload[396:400]))[0]
            balance_start_voltage_raw = int(payload[400:404], base=16)
            balance_start_diff_raw = int(payload[404:408], base=16)
        except (ValueError, TypeError) as e:
            logger.warning("get_balance_params response parsing error: {}".format(e))
            logger.debug("get_balance_params payload: {}".format(payload))
            return False

        # Voltage values are reported by these BMS in mV; temperature values are °C.
        logger.info(
            "> BALANCE PARAMS: High temp: {} C | Low temp: {} C | "
            "Start voltage: {:.3f} V | Start difference: {} mV".format(
                balance_high_temp,
                balance_low_temp,
                balance_start_voltage_raw / 1000,
                balance_start_diff_raw,
            )
        )
        return True

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
        capture_raw_data(ser.port, "tx", req)
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
        capture_raw_data(ser.port, "tx", req)
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
                balanced_mode = int(payload[46:50], base=16)
                # product_barcode_byte_array = bytearray.fromhex(payload[50:90])
                # product_barcode = product_barcode_byte_array.decode()
                # BMS_barcode_byte_array = bytearray.fromhex(payload[90:130])
                # BMS_barcode = BMS_barcode_byte_array.decode()

                self.cell_count = num_of_cells
                # Service 0x47 balanced_mode is retained as a raw/configuration mode.
                # Hardware testing proved that value 0 does not mean balancing disabled:
                # Service 0x42 can report active cell balancing while balanced_mode is 0.
                self.balanced_mode = balanced_mode
                self._log_balance_status()
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

        capture_raw_data(ser.port, "rx", buff)

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

    def create_command_get_balance_params(self):
        """
        Generates the read-only Service 0x80 request used by the manufacturer application.
        """
        return self.create_command(self.address, b"\x4a", b"\x80", self.address.hex().upper())

    def create_command_get_cells_params(self):
        """
        Generates command that utilizes Service 47 of the BMS.
        Example command (mark the \r at the end):
        ~22014A47E00201FD23␍
        """
        return self.create_command(self.address, b"\x4a", b"\x47", "01")

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
        return self.create_command(self.address, b"\x4a", b"\xb0", commandinfo)

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
        return self.create_command(self.address, b"\x4a", b"\xb0", commandinfo)

    def create_command_get_realtime_data(self):
        """
        Generates command that utilizes Service 42 of the BMS.
        Example command (mark the \r at the end):
        ~22014A42E00201FD28␍
        """
        return self.create_command(self.address, b"\x4a", b"\x42", "01")

    def create_command_get_manufacturer_info(self):
        """
        Generates command that utilizes Service 51 of the BMS.
        Example command (mark the \r at the end):
        ~22014A510000FDA0␍
        """
        return self.create_command(self.address, b"\x4a", b"\x51")

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
