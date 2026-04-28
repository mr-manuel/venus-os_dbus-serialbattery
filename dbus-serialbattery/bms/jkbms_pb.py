# -*- coding: utf-8 -*-

# Notes
# Added by https://github.com/KoljaWindeler

from battery import Battery, Cell
from utils import BATTERY_ADDRESSES, SOC_CALCULATION, logger
from struct import unpack_from
import serial
import sys
import time


class Jkbms_pb(Battery):
    def __init__(self, port, baud, address):
        super(Jkbms_pb, self).__init__(port, baud, address)
        self.type = self.BATTERYTYPE
        self.unique_identifier_tmp = ""
        self.cell_count = 0
        self.address = address
        self.command_status = b"\x10\x16\x20\x00\x01\x02\x00\x00"
        self.command_settings = b"\x10\x16\x1e\x00\x01\x02\x00\x00"
        self.command_about = b"\x10\x16\x1c\x00\x01\x02\x00\x00"
        self.history.exclude_values_to_calculate = ["charge_cycles"]
        self.use_async_refresh = True
        # self.has_settings = True
        # self.callbacks_available = ["callback_heating_turn_off"]

    BATTERYTYPE = "JKBMS PB Model"
    LENGTH_CHECK = 0  # ignored
    LENGTH_POS = 2  # ignored
    LENGTH_SIZE = "H"  # ignored

    _shared_ser = None  # shared serial port, kept open across calls

    # Minimum gap between consecutive commands on the RS485 bus (seconds).
    # 50ms: stale bytes from CH341 USB FIFO latency.
    # 75ms: zero errors on 4-battery system.
    # 100ms: safe margin. BMS bus master uses ~180ms.
    COMMAND_GAP = 0.12

    _last_command_time = 0.0
    _timing_logged = False

    @property
    def addr_str(self):
        return "0x" + self.address.hex()

    def _get_ser(self):
        """Return the shared serial port, opening it if needed."""
        if Jkbms_pb._shared_ser is None or not Jkbms_pb._shared_ser.is_open:
            Jkbms_pb._shared_ser = serial.Serial(self.port, baudrate=self.baud_rate, timeout=0.1)
        return Jkbms_pb._shared_ser

    def _read_with_retry(self, ser, command, timeout=0.5):
        """Send command and read response, retry once on failure."""
        result = self._read_response(ser, command, timeout)
        if not result:
            logger.warning(f"[{self.addr_str}] retry: {command[1:5].hex()}")
            result = self._read_response(ser, command, timeout)
        return result

    def test_connection(self):
        """
        call a function that will connect to the battery, send a command and retrieve the result.
        The result or call should be unique to this BMS. Battery name or version, etc.
        Return True if success, False for failure
        """
        result = False
        t0 = time.monotonic()
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

        addr_str = self.addr_str
        dt_ms = (time.monotonic() - t0) * 1000
        logger.info(f"[{addr_str}] test_connection: {'OK' if result else 'FAILED'} in {dt_ms:.0f}ms")
        return result

    def get_settings(self):
        # After successful connection get_settings() will be called to set up the battery
        # Set the current limits, populate cell count, etc
        # Return True if success, False for failure
        addr_str = self.addr_str
        try:
            ser = self._get_ser()
        except serial.SerialException as e:
            logger.error(f"[{addr_str}] serial error: {e}")
            return False

        status_data = self._read_with_retry(ser, self.command_settings, timeout=1.0)
        if not status_data:
            logger.warning(f"get_settings: command_settings failed for addr {addr_str}")
            return False

        VolSmartSleep = unpack_from("<i", status_data, 6)[0] / 1000
        VolCellUV = unpack_from("<i", status_data, 10)[0] / 1000
        VolCellUVPR = unpack_from("<i", status_data, 14)[0] / 1000
        VolCellOV = unpack_from("<i", status_data, 18)[0] / 1000
        VolCellOVPR = unpack_from("<i", status_data, 22)[0] / 1000
        VolBalanTrig = unpack_from("<i", status_data, 26)[0] / 1000
        VolSOC_full = unpack_from("<i", status_data, 30)[0] / 1000
        VolSOC_empty = unpack_from("<i", status_data, 34)[0] / 1000
        VolRCV = unpack_from("<i", status_data, 38)[0] / 1000  # Voltage Cell Request Charge Voltage (RCV)
        VolRFV = unpack_from("<i", status_data, 42)[0] / 1000  # Voltage Cell Request Float Voltage (RFV)
        VolSysPwrOff = unpack_from("<i", status_data, 46)[0] / 1000
        CurBatCOC = unpack_from("<i", status_data, 50)[0] / 1000
        TIMBatCOCPDly = unpack_from("<i", status_data, 54)[0]
        TIMBatCOCPRDly = unpack_from("<i", status_data, 58)[0]
        CurBatDcOC = unpack_from("<i", status_data, 62)[0] / 1000
        TIMBatDcOCPDly = unpack_from("<i", status_data, 66)[0]
        TIMBatDcOCPRDly = unpack_from("<i", status_data, 70)[0]
        TIMBatSCPRDly = unpack_from("<i", status_data, 74)[0]
        CurBalanMax = unpack_from("<i", status_data, 78)[0] / 1000
        TMPBatCOT = unpack_from("<I", status_data, 82)[0] / 10
        TMPBatCOTPR = unpack_from("<I", status_data, 86)[0] / 10
        TMPBatDcOT = unpack_from("<I", status_data, 90)[0] / 10
        TMPBatDcOTPR = unpack_from("<I", status_data, 94)[0] / 10
        TMPBatCUT = unpack_from("<I", status_data, 98)[0] / 10
        TMPBatCUTPR = unpack_from("<I", status_data, 102)[0] / 10
        TMPMosOT = unpack_from("<I", status_data, 106)[0] / 10
        TMPMosOTPR = unpack_from("<I", status_data, 110)[0] / 10
        CellCount = unpack_from("<i", status_data, 114)[0]
        BatChargeEN = unpack_from("<i", status_data, 118)[0]
        BatDisChargeEN = unpack_from("<i", status_data, 122)[0]
        BalanEN = unpack_from("<i", status_data, 126)[0]
        CapBatCell = unpack_from("<i", status_data, 130)[0] / 1000
        SCPDelay = unpack_from("<i", status_data, 134)[0]
        StartBalVol = unpack_from("<i", status_data, 138)[0] / 1000  # Start Balance Voltage
        DevAddr = unpack_from("<i", status_data, 270)[0]  # Device Addr
        TIMPDischarge = unpack_from("<i", status_data, 274)[0]
        TMPStartHeating = unpack_from("<b", status_data, 284)[0]
        TMPStopHeating = unpack_from("<b", status_data, 285)[0]

        CtrlBitMask = unpack_from("<H", status_data, 282)[0]  # Controls
        # Bit0: Heating enabled
        HeatEN = 0x01 & CtrlBitMask
        # Bit1: Disable Temp.-Sensor
        DisTempSens = 0x01 & (CtrlBitMask >> 1)
        # Bit2: GPS Heartbeat
        GPSHeartbeat = 0x01 & (CtrlBitMask >> 2)
        # Bit3: Port Switch 1:RS485 0: CAN
        PortSwitch = 0x01 & (CtrlBitMask >> 3)
        # Bit4: LCD Always ON
        LCDAlwaysOn = 0x1 & (CtrlBitMask >> 4)
        # Bit5: Special Charger
        SpecialCharger = 0x1 & (CtrlBitMask >> 5)
        # Bit6: Smart Sleep
        SmartSleep = 0x1 & (CtrlBitMask >> 6)

        TIMSmartSleep = unpack_from("<b", status_data, 286)[0]  # uint 8
        # TMPBatOTA/TMPBatOTAR are the same as TMPStartHeating/TMPStopHeating (offset 284/285)

        # balancer enabled
        self.balance_fet = True if BalanEN != 0 else False

        # heating enabled
        self.heater_fet = True if HeatEN != 0 else False

        # count of all cells in pack
        self.cell_count = CellCount

        # total Capaity in Ah
        self.capacity = CapBatCell

        # Continued discharge current
        self.max_battery_discharge_current = CurBatDcOC

        # Continued charge current
        self.max_battery_charge_current = CurBatCOC

        logger.debug("VolSmartSleep: " + str(VolSmartSleep))
        logger.debug("VolCellUV: " + str(VolCellUV))
        logger.debug("VolCellUVPR: " + str(VolCellUVPR))
        logger.debug("VolCellOV: " + str(VolCellOV))
        logger.debug("VolCellOVPR: " + str(VolCellOVPR))
        logger.debug("VolBalanTrig: " + str(VolBalanTrig))
        logger.debug("VolSOC_full: " + str(VolSOC_full))
        logger.debug("VolSOC_empty: " + str(VolSOC_empty))
        logger.debug("VolRCV: " + str(VolRCV))
        logger.debug("VolRFV: " + str(VolRFV))
        logger.debug("VolSysPwrOff: " + str(VolSysPwrOff))
        logger.debug("CurBatCOC: " + str(CurBatCOC))
        logger.debug("TIMBatCOCPDly: " + str(TIMBatCOCPDly))
        logger.debug("TIMBatCOCPRDly: " + str(TIMBatCOCPRDly))
        logger.debug("CurBatDcOC: " + str(CurBatDcOC))
        logger.debug("TIMBatDcOCPDly: " + str(TIMBatDcOCPDly))
        logger.debug("TIMBatDcOCPRDly: " + str(TIMBatDcOCPRDly))
        logger.debug("TIMBatSCPRDly: " + str(TIMBatSCPRDly))
        logger.debug("CurBalanMax: " + str(CurBalanMax))
        logger.debug("TMPBatCOT: " + str(TMPBatCOT))
        logger.debug("TMPBatCOTPR: " + str(TMPBatCOTPR))
        logger.debug("TMPBatDcOT: " + str(TMPBatDcOT))
        logger.debug("TMPBatDcOTPR: " + str(TMPBatDcOTPR))
        logger.debug("TMPBatCUT: " + str(TMPBatCUT))
        logger.debug("TMPBatCUTPR: " + str(TMPBatCUTPR))
        logger.debug("TMPMosOT: " + str(TMPMosOT))
        logger.debug("TMPMosOTPR: " + str(TMPMosOTPR))
        logger.debug("CellCount: " + str(CellCount))
        logger.debug("BatChargeEN: " + str(BatChargeEN))
        logger.debug("BatDisChargeEN: " + str(BatDisChargeEN))
        logger.debug("BalanEN: " + str(BalanEN))
        logger.debug("CapBatCell: " + str(CapBatCell))
        logger.debug("SCPDelay: " + str(SCPDelay))
        logger.debug("StartBalVol: " + str(StartBalVol))
        logger.debug("DevAddr: " + str(DevAddr))
        logger.debug("TIMPDischarge: " + str(TIMPDischarge))
        logger.debug("CtrlBitMask: " + str(CtrlBitMask))
        logger.debug("HeatEN: " + str(HeatEN))
        logger.debug("DisTempSens: " + str(DisTempSens))
        logger.debug("GPSHeartbeat: " + str(GPSHeartbeat))
        logger.debug("PortSwitch: " + str(PortSwitch))
        logger.debug("LCDAlwaysOn: " + str(LCDAlwaysOn))
        logger.debug("SpecialCharger: " + str(SpecialCharger))
        logger.debug("SmartSleep: " + str(SmartSleep))
        logger.debug("TMPBatOTA: " + str(TMPStartHeating))
        logger.debug("TMPBatOTAR: " + str(TMPStopHeating))
        logger.debug("TIMSmartSleep: " + str(TIMSmartSleep))
        logger.debug("TMPStartHeating: " + str(TMPStartHeating))
        logger.debug("TMPStopHeating: " + str(TMPStopHeating))

        status_data = self._read_with_retry(ser, self.command_about, timeout=1.0)
        # vendor_version start  0: 16 chars
        # hw_version     start 16:  8 chars
        # sw_version     start 24:  8 chars
        # oddruntim      start 32:  1 UINT32
        # pwr_on_time    start 36:  1 UINT32

        if not status_data:
            # fw >= v15.36 may not respond to command_about in every window;
            # fall back to safe defaults so get_settings() can still succeed
            if not self.version:
                self.version = ""
                self.hardware_version = ""
                self.heater_temperature_start = TMPBatCUT
                self.heater_temperature_stop = TMPBatCUTPR
            logger.debug("command_about: no response, keeping previous version info")
        else:
            vendor_id = status_data[6:21].decode("utf-8").split("\x00", 1)[0]  # 16 chars
            hw_version = status_data[22:29].decode("utf-8").split("\x00", 1)[0]  # 8 chars
            sw_version = status_data[30:37].decode("utf-8").split("\x00", 1)[0]  # 8 chars
            bms_version = hw_version + " / " + sw_version

            # if we have an older hardware older as 19A (starting with 19A the FW supports the heating temperature setting)
            # we use the old behavior by using the Bat Charge Under Temperature and Reset value
            if hw_version > "15A":
                self.heater_temperature_start = TMPStartHeating
                self.heater_temperature_stop = TMPStopHeating
            else:
                self.heater_temperature_start = TMPBatCUT
                self.heater_temperature_stop = TMPBatCUTPR

            logger.debug("TMPStartHeating: " + str(self.heater_temperature_start))
            logger.debug("TMPStopHeating: " + str(self.heater_temperature_stop))

            ODDRunTime = unpack_from("<I", status_data, 38)[0]  # 1 unit32 # runtime of the system in seconds
            PWROnTimes = unpack_from("<I", status_data, 42)[0]  # 1 unit32 # how many startups the system has done
            serial_nr = status_data[46:61].decode("utf-8").split("\x00", 1)[0]  # serialnumber 16 chars max
            usrData = status_data[102:117].decode("utf-8").split("\x00", 1)[0]  # usrData 16 chars max
            pin = status_data[118:133].decode("utf-8").split("\x00", 1)[0]  # pin 16 chars max
            usrData2 = status_data[134:149].decode("utf-8").split("\x00", 1)[0]  # usrData 2 16 chars max
            ble_id = serial_nr + "-" + str(DevAddr)

            self.unique_identifier_tmp = serial_nr
            self.version = sw_version
            self.hardware_version = bms_version

            logger.debug("Serial Nr: " + str(serial_nr))
            logger.debug("Ble Id: " + str(ble_id))
            logger.debug("Vendor ID: " + str(vendor_id))
            logger.debug("HW Version: " + str(hw_version))
            logger.debug("SW Version: " + str(sw_version))
            logger.debug("BMS Version: " + str(bms_version))
            logger.debug("User data: " + str(usrData))
            logger.debug("User data 2: " + str(usrData2))
            logger.debug("pin: " + str(pin))
            logger.debug("PWROnTimes: " + str(PWROnTimes))
            logger.debug(
                "ODDRunTime: "
                + str(ODDRunTime)
                + "s; "
                + str(ODDRunTime / 60)
                + "m; "
                + str(ODDRunTime / 60 / 60)
                + "h; "
                + str(ODDRunTime / 60 / 60 / 24)
                + "d"
            )

        # init the cell array
        for _ in range(self.cell_count):
            self.cells.append(Cell(False))

        if not Jkbms_pb._timing_logged:
            Jkbms_pb._timing_logged = True
            n = max(len(BATTERY_ADDRESSES), 1)
            per_bat_ms = (self.COMMAND_GAP + 0.04) * 1000  # gap + ~40ms protocol
            logger.info(
                f"JKBMS PB timing: gap={self.COMMAND_GAP * 1000:.0f}ms" f" — estimated poll: {n}x {per_bat_ms:.0f}ms = {n * per_bat_ms:.0f}ms for {n} batteries"
            )

        return True

    def refresh_data(self):
        addr_str = self.addr_str
        t0 = time.monotonic()
        try:
            ser = self._get_ser()
            status_data = self._read_with_retry(ser, self.command_status)
        except serial.SerialException as e:
            logger.error(f"[{addr_str}] serial error: {e}")
            return False

        if not status_data:
            logger.warning(f"[{addr_str}] refresh_data: no response")
            return False

        result = self.read_status_data(status_data)
        dt_ms = (time.monotonic() - t0) * 1000
        logger.debug(f"[{addr_str}] refresh_data: {dt_ms:.0f}ms")
        return result

    def read_status_data(self, status_data):
        # cell voltages
        for c in range(self.cell_count):
            if (unpack_from("<H", status_data, c * 2 + 6)[0] / 1000) != 0:
                self.cells[c].voltage = unpack_from("<H", status_data, c * 2 + 6)[0] / 1000

        # MOSFET temperature
        temperature_mos = unpack_from("<h", status_data, 144)[0] / 10
        self.to_temperature(0, temperature_mos if temperature_mos < 99 else (100 - temperature_mos))

        # Temperature sensors
        temperature_1 = unpack_from("<h", status_data, 162)[0] / 10
        temperature_2 = unpack_from("<h", status_data, 164)[0] / 10
        temperature_3 = unpack_from("<h", status_data, 256)[0] / 10
        temperature_4 = unpack_from("<h", status_data, 258)[0] / 10

        if unpack_from("<B", status_data, 214)[0] & 0x02:
            self.to_temperature(1, temperature_1 if temperature_1 < 99 else (100 - temperature_1))
        if unpack_from("<B", status_data, 214)[0] & 0x04:
            self.to_temperature(2, temperature_2 if temperature_2 < 99 else (100 - temperature_2))
        if unpack_from("<B", status_data, 214)[0] & 0x10:
            self.to_temperature(3, temperature_3 if temperature_3 < 99 else (100 - temperature_3))
        if unpack_from("<B", status_data, 214)[0] & 0x20:
            self.to_temperature(4, temperature_4 if temperature_4 < 99 else (100 - temperature_4))

        # Battery voltage
        self.voltage = unpack_from("<I", status_data, 150)[0] / 1000

        # Battery ampere
        self.current = unpack_from("<i", status_data, 158)[0] / 1000

        # SOC
        self.soc = unpack_from("<B", status_data, 173)[0]

        # SOH
        self.soh = unpack_from("<B", status_data, 190)[0]
        # precharge = unpack_from("<B", status_data, 191)[0]

        # cycles
        self.history.charge_cycles = unpack_from("<i", status_data, 182)[0]

        # capacity
        self.capacity_remain = unpack_from("<i", status_data, 174)[0] / 1000

        # fuses
        self.to_protection_bits(unpack_from("<I", status_data, 166)[0])

        # bits
        bal = unpack_from("<B", status_data, 172)[0]
        charge = unpack_from("<B", status_data, 198)[0]
        discharge = unpack_from("<B", status_data, 199)[0]
        heat = unpack_from("<B", status_data, 215)[0]

        logger.debug("bal: " + str(bal) + " charge: " + str(charge) + " discharge: " + str(discharge) + " heat: " + str(heat))

        self.charge_fet = 1 if charge != 0 else 0
        self.discharge_fet = 1 if discharge != 0 else 0
        self.balancing = 1 if bal != 0 else 0
        self.heating = 1 if heat != 0 else 0

        # HeatCurrent is provided in mA, convert to A
        self.heater_current = int(unpack_from("<H", status_data, 236)[0]) / 1000
        self.heater_power = 0.0 if self.heating != 1 else float(self.heater_current * self.voltage)

        # show wich cells are balancing
        if self.get_min_cell() is not None and self.get_max_cell() is not None:
            for c in range(self.cell_count):
                if self.balancing and (self.get_min_cell() == c or self.get_max_cell() == c):
                    self.cells[c].balance = True
                else:
                    self.cells[c].balance = False

        return True

    def unique_identifier(self) -> str:
        """
        Used to identify a BMS when multiple BMS are connected
        """
        return self.unique_identifier_tmp

    def get_balancing(self):
        return 1 if self.balancing else 0

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

    def to_protection_bits(self, byte_data):
        """
        Bit 0x00000001: Wire resistance alarm: 1 warning only, 0 nomal -> OK
        Bit 0x00000002: MOS overtemperature alarm: 1 alarm, 0 nomal -> OK
        Bit 0x00000004: Cell quantity alarm: 1 alarm, 0 nomal -> OK
        Bit 0x00000008: Current sensor error alarm: 1 alarm, 0 nomal -> OK
        Bit 0x00000010: Cell OVP alarm: 1 alarm, 0 nomal -> OK
        Bit 0x00000020: Bat OVP alarm: 1 alarm, 0 nomal -> OK
        Bit 0x00000040: Charge Over current alarm: 1 alarm, 0 nomal -> OK
        Bit 0x00000080: Charge SCP alarm: 1 alarm, 0 nomal -> OK
        Bit 0x00000100: Charge OTP: 1 alarm, 0 nomal -> OK
        Bit 0x00000200: Charge UTP: 1 alarm, 0 nomal -> OK
        Bit 0x00000400: CPU Aux Communication: 1 alarm, 0 nomal -> OK
        Bit 0x00000800: Cell UVP: 1 alarm, 0 nomal -> OK
        Bit 0x00001000: Batt UVP: 1 alarm, 0 nomal
        Bit 0x00002000: Discharge Over current: 1 alarm, 0 nomal
        Bit 0x00004000: Discharge SCP: 1 alarm, 0 nomal
        Bit 0x00008000: Discharge OTP: 1 alarm, 0 nomal
        Bit 0x00010000: Charge MOS: 1 alarm, 0 nomal
        Bit 0x00020000: Discharge MOS: 1 alarm, 0 nomal
        Bit 0x00040000: GPS disconnected: 1 alarm, 0 nomal
        Bit 0x00080000: Modify PWD in time: 1 alarm, 0 nomal
        Bit 0x00100000: Discharg on Faied: 1 alarm, 0 nomal
        Bit 0x00200000: Battery over Temp: 1 alarm, 0 nomal
        """

        # low capacity alarm
        if not SOC_CALCULATION:
            self.protection.low_soc = 2 if (byte_data & 0x00001000) else 0
        # MOSFET temperature alarm
        self.protection.high_internal_temperature = 2 if (byte_data & 0x00000002) else 0
        # charge over voltage alarm
        self.protection.high_voltage = 2 if (byte_data & 0x00000020) else 0
        # discharge under voltage alarm
        self.protection.low_voltage = 2 if (byte_data & 0x00000800) else 0
        # charge overcurrent alarm
        self.protection.high_charge_current = 2 if (byte_data & 0x00000040) else 0
        # discharge over current alarm
        self.protection.high_discharge_current = 2 if (byte_data & 0x00002000) else 0
        # core differential pressure alarm OR unit overvoltage alarm
        self.protection.cell_imbalance = 0
        # cell overvoltage alarm
        self.protection.high_cell_voltage = 2 if (byte_data & 0x00000010) else 0
        # cell undervoltage alarm
        self.protection.low_cell_voltage = 2 if (byte_data & 0x00001000) else 0
        # battery overtemperature alarm OR overtemperature alarm in the battery box
        self.protection.high_charge_temperature = 2 if (byte_data & 0x00000100) else 0
        self.protection.low_charge_temperature = 2 if (byte_data & 0x00000200) else 0
        # check if low/high temp alarm arise during discharging
        self.protection.high_temperature = 2 if (byte_data & 0x00008000) else 0
        self.protection.low_temperature = 0

    # Expected frame types per command
    EXPECTED_FTYPE = {
        b"\x10\x16\x20\x00\x01\x02\x00\x00": 0x0002,  # status
        b"\x10\x16\x1e\x00\x01\x02\x00\x00": 0x0001,  # settings
        b"\x10\x16\x1c\x00\x01\x02\x00\x00": 0x0003,  # about
    }

    def _send_command(self, ser, command):
        """Enforce bus gap, drain stale bytes, send FC16 command, wait for TX complete."""
        addr_str = self.addr_str

        elapsed = time.monotonic() - Jkbms_pb._last_command_time
        if elapsed < self.COMMAND_GAP:
            time.sleep(self.COMMAND_GAP - elapsed)

        stale = ser.in_waiting
        if stale:
            stale_bytes = ser.read(stale)
            logger.warning(f"[{addr_str}] PRE-SEND stale={stale}: {stale_bytes.hex()}")
        ser.reset_input_buffer()

        modbus_msg = self.address + command + self.modbusCrc(self.address + command)
        ser.write(modbus_msg)
        ser.flush()
        Jkbms_pb._last_command_time = time.monotonic()

    def _receive_data(self, ser, timeout=0.5):
        """Read bytes from serial port until complete response or timeout.

        Returns raw bytearray (may include TX echo prefix).
        Minimum complete = 0x55AA header + 308 bytes (payload + ACK, no padding).
        Some adapters add 0x00 padding (310 bytes total after header).
        """
        PAYLOAD_SIZE = 300
        ACK_SIZE = 8
        MIN_AFTER_HEADER = PAYLOAD_SIZE + ACK_SIZE  # 308

        data = bytearray()
        start = time.monotonic()
        deadline = start + timeout
        while time.monotonic() < deadline:
            n = ser.in_waiting
            if n > 0:
                data.extend(ser.read(n))
                hdr = data.find(b"\x55\xaa")
                if hdr >= 0 and len(data) >= hdr + MIN_AFTER_HEADER:
                    # Got enough; settle briefly for trailing padding bytes
                    time.sleep(0.005)
                    n = ser.in_waiting
                    if n > 0:
                        data.extend(ser.read(n))
                    break
            else:
                if not data:
                    time.sleep(0.01)
                else:
                    time.sleep(0.005)

        return data

    def _validate_response(self, data, command):
        """Validate a raw response and extract the 300-byte payload.

        Checks: 0x55AA header, 0xEB90 marker, frame type, sum8 checksum,
        padding bytes, FC16 ACK (address + register + CRC), total byte count.

        Returns payload (bytes) or False on any validation failure.
        """
        PAYLOAD_SIZE = 300
        ACK_SIZE = 8
        addr_str = self.addr_str

        if not data:
            logger.warning(f"[{addr_str}] no response")
            return False

        hdr = data.find(b"\x55\xaa")
        if hdr < 0:
            logger.warning(f"[{addr_str}] no 0x55AA in {len(data)} bytes: {data[:40].hex()}")
            return False

        if len(data) < hdr + PAYLOAD_SIZE:
            logger.warning(f"[{addr_str}] truncated: {len(data) - hdr}/{PAYLOAD_SIZE} bytes after 0x55AA")
            return False

        payload = bytes(data[hdr : hdr + PAYLOAD_SIZE])

        if payload[2:4] != b"\xeb\x90":
            logger.warning(f"[{addr_str}] bad frame marker: {payload[2:4].hex()} (expected eb90)")
            return False

        ftype = payload[4] | payload[5] << 8
        expected = self.EXPECTED_FTYPE.get(command)
        if expected is not None and ftype != expected:
            logger.warning(f"[{addr_str}] wrong frame type: 0x{ftype:04X} (expected 0x{expected:04X})")
            return False

        if not self._verify_checksum(payload):
            logger.warning(f"[{addr_str}] checksum fail: computed={sum(payload[:299]) & 0xFF} stored={payload[299]}")
            return False

        # Scan for FC16 ACK after payload: look for [address][0x10] pattern
        tail = data[hdr + PAYLOAD_SIZE :]
        ack_marker = self.address + b"\x10"
        ack_pos = tail.find(ack_marker)
        if ack_pos >= 0 and len(tail) >= ack_pos + ACK_SIZE:
            ack = bytes(tail[ack_pos : ack_pos + ACK_SIZE])
            if not self._verify_ack(ack, command):
                logger.warning(f"[{addr_str}] ACK validation failed: {ack.hex()}")
        elif ack_pos >= 0:
            logger.warning(f"[{addr_str}] ACK truncated: {len(tail) - ack_pos}/{ACK_SIZE} bytes")
        else:
            logger.warning(f"[{addr_str}] no ACK found in {len(tail)} trailing bytes")

        return payload

    def _read_response(self, ser, command, timeout=0.5):
        """Send FC16 command and return validated 300-byte payload, or False."""
        self._send_command(ser, command)
        data = self._receive_data(ser, timeout)
        return self._validate_response(data, command)

    @staticmethod
    def _verify_checksum(data):
        """Verify sum8 checksum at byte 299 of a 300-byte 0x55AA response."""
        if len(data) != 300:
            return False
        return sum(data[:299]) & 0xFF == data[299]

    def _verify_ack(self, ack, command):
        """Verify an 8-byte FC16 write-ACK matches our address and command register."""
        if len(ack) != 8:
            return False
        if ack[0:1] != self.address:
            return False
        if ack[1] != 0x10:
            return False
        if ack[2:6] != command[1:5]:
            return False
        expected_crc = self.modbusCrc(ack[:6])
        if ack[6:8] != expected_crc:
            return False
        return True

    def modbusCrc(self, msg: str):
        """
        copied from https://stackoverflow.com/a/75328573
        to calculate the needed checksum
        """
        crc = 0xFFFF
        for n in range(len(msg)):
            crc ^= msg[n]
            for i in range(8):
                if crc & 1:
                    crc >>= 1
                    crc ^= 0xA001
                else:
                    crc >>= 1
        return crc.to_bytes(2, "little")

    def callback_heating_turn_off(self, path: str, value: int) -> bool:
        return False
