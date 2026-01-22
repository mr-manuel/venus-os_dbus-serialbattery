# -*- coding: utf-8 -*-

# NOTES
# RS-485 support for UP series JBD BMS.
#
# Tested on JBD UP16S015 with firmware 10.2.1 and 12.1.7.
# Protocol reference: https://gist.github.com/PhracturedBlue/7ef619594eaa4c27f4ff068b461865b8
# UP series might be the only series that supports this protocol.
# In theory, this protocol might also work over Bluetooth. For that, code in lltjbd_ble.py might need to be reused with lltjbd_up16s.py, but currently this is
# not implemented.

from battery import Battery, Cell, Protection
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum, IntFlag
from struct import pack, Struct, error as StructError
from typing import ClassVar, Dict, Optional, Type, TypeVar
from utils import logger, read_serialport_data, AUTO_RESET_SOC, UP16S_REQUIRE_DIRECT_CONNECTION
import serial
import time
import termios

# Modbus function codes
FUNC_INDIVIDUAL_PACK_STATUS = 0x45
FUNC_READ = 0x78
FUNC_WRITE = 0x79

# Maximum cell and temperature sensor counts supported by UP16S series BMS
MAX_CELL_COUNT = 16
MAX_TEMPERATURES_COUNT = 4

# Number of retries before declaring a certain command on a certain battery address unavailable
MAX_AVAILABILITY_RETRIES = 5
# Maximum number of times to retry setting SOC
MAX_SET_SOC_RETRIES = 3
# Use the aggregated values from the master only if the values were updated more recently than this:
MASTER_AGGREGATED_VALUE_TIMEOUT_SECONDS = 60 * 5
# It usually takes 0.3-0.6s to receive a response, so 1.5 second timeout should be enough
SERIAL_TIMEOUT_SECONDS = 1.5
# Delay when serial communication interference from another process is detected
INTERFERENCE_DELAY_SECONDS = 1
# How much time to wait for interference to end
MAX_INTERFERENCE_RETRY_SECONDS = 60
# How often to request the total Ah drawn value
TOTAL_AH_DRAWN_REQUEST_INTERVAL_SECONDS = 30

BIG_ENDIAN_SHORT_INT_STRUCT = Struct(">H")
CRC_STRUCT = Struct("<H")

JBD_WRITE_PAYLOAD_PREFIX = bytes([0x11, 0x4A, 0x42, 0x44])


@dataclass
class CommandAvailability:
    """Not all commands are available on certain ports and battery addresses. It depends on the user's specific combination of BMS firmware and BMS ports
    used. This class stores availability status of a particular command on a particular port and battery address"""

    class Status(Enum):
        UNKNOWN = 1  # Will retry until MAX_AVAILABILITY_RETRIES
        AVAILABLE = 2  # The response was received at least once. The command is declared as available and no further availability determination is performed
        UNAVAILABLE = 3  # The response was never received after MAX_AVAILABILITY_RETRIES. The command is declared as unavailable and will not be sent anymore

    status: Status = Status.UNKNOWN
    retries: int = 0


CommandT = TypeVar("CommandT", bound="Command")


class Command:
    MODBUS_FUNC: ClassVar[int]
    MODBUS_START_ADDR: ClassVar[int]
    MODBUS_ADDR_LEN: ClassVar[int]
    DEFAULT_AVAILABILITY_STATUS: CommandAvailability.Status

    def __init_subclass__(cls, default_availability_status=CommandAvailability.Status.UNKNOWN, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.DEFAULT_AVAILABILITY_STATUS = default_availability_status

    @classmethod
    def from_bytes(cls, data: bytes):
        return cls(*cls.STRUCT.unpack_from(data))


@dataclass
class FrameHeader:
    STRUCT: ClassVar[Struct] = Struct(">BBHHH")

    battery_address: int
    function_code: int
    start_addr: int
    end_addr: int
    payload_len: int


@dataclass
class IndividualPackStatus(Command):
    """Used by the master to poll slaves about their status. Can be queried only for the battery directly connected to the used port, even on Bluetooth/Wifi
    UART port. This code uses this command to get individual (non-aggregated) CCL/DCL from the master, because it appears this is the only way to get it."""

    MODBUS_FUNC = FUNC_INDIVIDUAL_PACK_STATUS
    MODBUS_START_ADDR = 0x0000
    MODBUS_ADDR_LEN = 0x54

    STRUCT = Struct(">96sHH")

    unused: bytes  # Skip most of the fields, since we take them from PackStatus instead.
    charge_current_limit: int
    discharge_current_limit: int


@dataclass
class PackStatus(Command, default_availability_status=CommandAvailability.Status.AVAILABLE):
    """Status of a battery pack. Treat this command as always available, since this data is strictly required, so we need to continue trying to request it
    even after max retries are reached. Unlike other commands, BMS responds to this command for any valid battery address, on any port that supports modbus
    protocol."""

    MODBUS_FUNC = FUNC_READ
    MODBUS_START_ADDR = 0x1000
    MODBUS_ADDR_LEN = 0xA0

    PREFIX_STRUCT = Struct(">HHIHHHHHHHHIIHHHHHHHHHHHHHHHHH")  # All fields before "cell_count"
    SUFFIX_STRUCT = Struct(">HHH30s")  # All fields after "temperatures"

    pack_voltage: int
    unknown1: int
    current: int
    soc: int  # Returned in 0.01% units, but master knows only whole percent values for slaves.
    remaining_capacity: int
    full_capacity: int
    rated_capacity: int
    mosfet_temp: int
    ambient_temp: int
    operation_status: int
    soh: int
    fault_flags: int
    alarm_flags: int
    mosfet_flags: int
    connection_state_flags: int
    charge_cycles: int
    max_v_cell_num: int
    max_cell_voltage: int
    min_v_cell_num: int
    min_cell_voltage: int
    avg_cell_voltage: int
    max_t_sensor_num: int
    max_cell_temp: int
    min_t_sensor_num: int
    min_cell_temp: int
    avg_cell_temp: int
    maximum_charge_voltage: int
    charge_current_limit: int
    minimum_discharge_voltage: int
    discharge_current_limit: int
    cell_count: int
    cell_voltages: tuple[int, ...]
    temperatures_count: int
    temperatures: tuple[int, ...]
    unknown2: int
    cell_balancing_flags: int  # Bitmask of which cells are balancing, cell 1 at least significant bit.
    firmware_version: int  # Not available when master forwards from slaves
    pack_serial_number: bytes
    # Skip the rest of the fields, since we don't need them.

    @classmethod
    def from_bytes(cls, data: bytes):
        offset = 0

        prefix_data = cls.PREFIX_STRUCT.unpack_from(data, offset)
        offset += cls.PREFIX_STRUCT.size

        cell_count = BIG_ENDIAN_SHORT_INT_STRUCT.unpack_from(data, offset)[0]
        offset += BIG_ENDIAN_SHORT_INT_STRUCT.size

        cell_voltages = list(Struct(f">{cell_count}H").unpack_from(data, offset))
        # Further offsets depend on cell count in this command response.
        offset += BIG_ENDIAN_SHORT_INT_STRUCT.size * cell_count

        temperatures_count = BIG_ENDIAN_SHORT_INT_STRUCT.unpack_from(data, offset)[0]
        offset += BIG_ENDIAN_SHORT_INT_STRUCT.size

        temperatures = list(Struct(f">{temperatures_count}H").unpack_from(data, offset))
        offset += BIG_ENDIAN_SHORT_INT_STRUCT.size * temperatures_count

        suffix_data = cls.SUFFIX_STRUCT.unpack_from(data, offset)

        return cls(*prefix_data, cell_count, tuple(cell_voltages), temperatures_count, tuple(temperatures), *suffix_data)


@dataclass
class PackParams1(Command):
    """Returns configuration parameters (part 1). On Bluetooth/Wifi UART port this data can be requested for any battery, and on other ports it can be
    requested only for the battery directly connected to that port."""

    MODBUS_FUNC = FUNC_READ
    # We only need the BMS model and serial number from this request, so the start address could be changed accordingly, but it's not clear whether that
    # would be supported by all firmware versions. So we use the more common start address and length to ensure compatibility.
    MODBUS_START_ADDR = 0x1C00
    MODBUS_ADDR_LEN = 0xA0

    STRUCT: ClassVar[Struct] = Struct(">16s30sHHH30sHHH")

    unused: bytes  # Skip fields we don't need.
    bms_model_and_sn: bytes
    bms_year: int
    bms_month: int
    bms_day: int
    pack_serial_number: bytes
    pack_year: int
    pack_month: int
    pack_day: int


@dataclass
class PackParams2(Command):
    """Returns configuration parameters (part 2). On Bluetooth/Wifi UART port this data can be requested for any battery, and on other ports it can be
    requested only for the battery directly connected to that port.
    This version of the command requests only the minimum required information (versus requesting everything starting from address 0x2000). This is intentional,
    and serves as a workaround for a BMS firmware bug that occasionally causes DCL to be briefly reset to 0 across all requests when the starting address is
    0x2000. The downside is that this partial response format is only supported starting from about firmware v12 and will be ignored by older firmware."""

    STRUCT: ClassVar[Struct] = Struct(">H8sII")

    MODBUS_FUNC = FUNC_READ
    MODBUS_START_ADDR = 0x2006
    MODBUS_ADDR_LEN = STRUCT.size

    high_res_soc: int  # In difference to SOC from PackStatus, this field always contains an actual high-res non-rounded SOC
    unused: bytes
    total_charge: int
    total_discharge: int


@dataclass
class ProductInformation(Command):
    """Returns product information. On Bluetooth/Wifi UART port this data can be requested for any battery, and on other ports it can be requested only for
    the battery directly connected to that port."""

    MODBUS_FUNC = FUNC_READ
    MODBUS_START_ADDR = 0x2810
    MODBUS_ADDR_LEN = 0x2C

    STRUCT: ClassVar[Struct] = Struct(">HHHHHH16s16s")

    maybe_model_id: int
    maybe_hardware_revision: int
    firmware_major_version: int
    firmware_minor_version: int
    firmware_patch_version: int
    unknown1: int
    model: bytes
    project_code: bytes


@dataclass
class SetSoc(Command):
    """Sets SOC on the BMS. On Bluetooth/Wifi UART port this command can be sent for any battery, and on other ports it can be
    sent only for the battery directly connected to that port."""

    MODBUS_FUNC = FUNC_WRITE
    MODBUS_START_ADDR = 0x2006
    MODBUS_ADDR_LEN = BIG_ENDIAN_SHORT_INT_STRUCT.size

    # Response struct with no fields - the BMS returns zero-length payload
    STRUCT: ClassVar[Struct] = Struct("")

    @classmethod
    def construct_request_payload(cls, high_res_soc: int):
        return JBD_WRITE_PAYLOAD_PREFIX + BIG_ENDIAN_SHORT_INT_STRUCT.pack(high_res_soc)


@dataclass
class SharedData:
    """Data shared across all battery instances on the same port. Sharing across different ports won't work this way because that data is in another
    dbus-serialbattery process. This is fine, the aggregated CCL and CVL will still practically work as intended as long as they're applied to some battery
    instances, and command_availability_by_address must have separate instances on different ports either way."""

    master_aggregated_charge_current_limit_amps: Optional[float] = None
    master_aggregated_discharge_current_limit_amps: Optional[float] = None
    master_aggregated_last_update_timestamp: int = 0

    # Structure: [address_int][Command.__name__] -> CommandAvailability
    command_availability_by_address: Dict[int, Dict[str, CommandAvailability]] = field(default_factory=dict)

    def get_command_availability(self, address_int: int, command_class) -> CommandAvailability:
        """Returns an object that stores whether this particular command is available for this particular port and battery address. This is used to avoid
        sending optional requests that are not understood or are ignored on a particular combination of BMS firmware and port, so that we don't add unnecessary
        delays by waiting for responses to those ignored requests."""
        if address_int not in self.command_availability_by_address:
            self.command_availability_by_address[address_int] = {}
        command_availability_map = self.command_availability_by_address[address_int]
        if command_class.__name__ not in command_availability_map:
            command_availability_map[command_class.__name__] = CommandAvailability(command_class.DEFAULT_AVAILABILITY_STATUS)
        return command_availability_map[command_class.__name__]


shared_data = SharedData()


class LltJbd_Up16s(Battery):
    def __init__(self, port, baud, address):
        super(LltJbd_Up16s, self).__init__(port, baud, address)
        self.type = self.BATTERYTYPE
        self.history.exclude_values_to_calculate = ["charge_cycles"]
        self.address_int = int.from_bytes(address, "big")
        self.bms_model_and_serial_number = None
        self.pack_serial_number = None
        self.rated_capacity = None
        self.soc_to_set = None

    BATTERYTYPE = "JBD UP16S"

    RESPONSE_PAYLOAD_LEN_OFFS = 6  # Offset of the data length field in the response

    class MosfetFlags(IntFlag):
        DISCHARGE_ENABLED = 1
        CHARGE_ENABLED = 2

    def callback_soc_reset_to(self, path, value):
        if value is None or value < 0 or value > 100:
            return False
        if shared_data.get_command_availability(self.address_int, SetSoc).status == CommandAvailability.Status.UNAVAILABLE:
            return False

        self.soc_to_set = value
        return True

    def trigger_soc_reset(self) -> bool:
        if not AUTO_RESET_SOC:
            return False
        return self.callback_soc_reset_to(None, 100)

    def unique_identifier(self) -> str:
        if self.bms_model_and_serial_number:
            return self.bms_model_and_serial_number
        # Make sure to use the rated capacity, not the full capacity. Rated capacity doesn't get recalculated by the BMS.
        return f"{self.pack_serial_number}_{self.rated_capacity}"

    def test_connection(self):
        """Read data to see whether the BMS can be recognized."""
        # On a failure that's not related to serial connection interference, return False right away without retrying. dbus-serialbattery will retry on its own.
        # If direct connection is required, try requesting IndividualPackStatus first, which is only available with direct connection.
        if UP16S_REQUIRE_DIRECT_CONNECTION:
            if self.open_serial_connection_with_retry_on_interference(lambda ser: self.send_request_and_parse_response(ser, IndividualPackStatus)) is None:
                return False
        # Otherwise try reading pack status first, since this is the only command that works both with master and slaves
        if not self.open_serial_connection_with_retry_on_interference(self.read_and_populate_pack_status):
            return False
        return self.get_settings()

    def get_settings(self):
        """Get initial settings from the BMS. This method is required by battery.py"""
        # Try to get PackParams1 until MAX_AVAILABILITY_RETRIES. We need BMS serial number for the unique identifier, so this loop intentionally blocks the
        # driver startup (*after* we've determined that the battery does respond successfully to PackStatus command).
        if self.open_serial_connection_with_retry_on_interference(self.read_and_populate_pack_params_1, MAX_AVAILABILITY_RETRIES):
            # If PackParams1 wasn't successful, it's very unlikely that ProductInformation will be - skip it in that case.
            self.open_serial_connection_with_retry_on_interference(self.read_and_populate_product_information, MAX_AVAILABILITY_RETRIES)

        # Assume that if reading PackParams2 is available, writing to the same parameter address range with SetSoc would also be available.
        if shared_data.get_command_availability(self.address_int, PackParams2).status == CommandAvailability.Status.AVAILABLE:
            self.append_once(self.callbacks_available, "callback_soc_reset_to")
        # Need to also set has_settings for the callbacks to be visible in the UI.
        self.has_settings = len(self.callbacks_available) > 0

        # Always return True, since serial number is optional information that's not available for slaves on ports other than the Bluetooth/Wifi UART port.
        return True

    def refresh_data(self):
        """Refresh battery data by reading from BMS."""
        # Set SOC when requested.
        if self.soc_to_set is not None:
            self.open_serial_connection_with_retry_on_interference(self.set_soc, MAX_SET_SOC_RETRIES)
            self.soc_to_set = None

        # For regular updates there's no need to retry on interference, since dbus-serialbattery will retry on its own.
        with self.serial_connection() as ser:
            if not ser:
                return False
            return self.read_and_populate_pack_status(ser)

    def set_soc(self, ser) -> bool:
        raw_high_res_soc = self.to_raw_high_resolution_percentage(self.soc_to_set)
        set_soc_response = self.send_request_and_parse_response(ser, SetSoc, SetSoc.construct_request_payload(raw_high_res_soc))
        if set_soc_response is None:
            logger.error(f"Couldn't set SOC on battery {self.address_int}")
            return False
        logger.info(f"Successfully set SOC on battery {self.address_int} to {self.soc_to_set:.2f}%")
        return True

    def read_and_populate_pack_params_1(self, ser) -> bool:
        pack_params_1 = self.send_request_and_parse_response(ser, PackParams1)
        if pack_params_1 is None:
            return False
        self.bms_model_and_serial_number = self.from_raw_string(pack_params_1.bms_model_and_sn)
        self.production = (
            f"BMS {pack_params_1.bms_year}.{pack_params_1.bms_month:02d}.{pack_params_1.bms_day:02d}, "
            f"Pack {pack_params_1.pack_year}.{pack_params_1.pack_month:02d}.{pack_params_1.pack_day:02d}"
        )
        return True

    def read_and_populate_product_information(self, ser) -> bool:
        product_information = self.send_request_and_parse_response(ser, ProductInformation)
        if product_information is None:
            return False
        # Overwrite the hardware version set in read_pack_status() with the more detailed information we have now.
        self.hardware_version = (
            f"{self.from_raw_string(product_information.project_code)} {self.from_raw_string(product_information.model)}, "
            f"model {product_information.maybe_model_id}, HW rev {product_information.maybe_hardware_revision}, "
            f"FW v{product_information.firmware_major_version}.{product_information.firmware_minor_version}."
            f"{product_information.firmware_patch_version}, {self.production}"
        )
        return True

    def read_and_populate_pack_status(self, ser) -> bool:
        pack_status = self.send_request_and_parse_response(ser, PackStatus)
        if not pack_status:
            return False
        pack_params_2 = self.send_request_and_parse_response(ser, PackParams2)

        if self.is_master():
            # In difference from slaves, the master returns aggregated CCL, DCL, CVL and DVL. The code below saves CCL and DCL to the shared state, and then
            # overwrites them in pack_status returned by the master with non-aggregated values, to ensure pack_status values have the same meaning with all
            # packs. Non-aggregated CVL and DVL for the master are not available explicitly, but it appears the master returns them unchanged as the aggregated
            # values.
            shared_data.master_aggregated_charge_current_limit_amps = self.from_raw_current_to_amps(pack_status.charge_current_limit)
            shared_data.master_aggregated_discharge_current_limit_amps = self.from_raw_current_to_amps(pack_status.discharge_current_limit)
            shared_data.master_aggregated_last_update_timestamp = time.monotonic()
            individual_pack_status = self.send_request_and_parse_response(ser, IndividualPackStatus)
            if individual_pack_status:
                pack_status.charge_current_limit = individual_pack_status.charge_current_limit
                pack_status.discharge_current_limit = individual_pack_status.discharge_current_limit

        # Take the minimum of the aggregated and non-aggregated current, in case master knows something we don't and reduced the aggregated current.
        self.max_battery_charge_current = self.apply_aggregated_current_limit_from_master(
            self.from_raw_current_to_amps(pack_status.charge_current_limit),
            shared_data.master_aggregated_charge_current_limit_amps,
            shared_data.master_aggregated_last_update_timestamp,
        )
        self.max_battery_discharge_current = self.apply_aggregated_current_limit_from_master(
            self.from_raw_current_to_amps(pack_status.discharge_current_limit),
            shared_data.master_aggregated_discharge_current_limit_amps,
            shared_data.master_aggregated_last_update_timestamp,
        )
        self.min_battery_voltage = self.from_raw_dvcc_voltage_to_volts(pack_status.minimum_discharge_voltage)
        self.max_battery_voltage = self.from_raw_dvcc_voltage_to_volts(pack_status.maximum_charge_voltage)

        pack_status_soc = self.from_raw_high_resolution_percentage(pack_status.soc)
        if pack_params_2:
            self.soc = self.from_raw_high_resolution_percentage(pack_params_2.high_res_soc)
            self.append_once(self.history.exclude_values_to_calculate, "total_ah_drawn")
            # total_ah_drawn has to be negative by convention in battery.py
            self.history.total_ah_drawn = -self.from_raw_total_charge_discharge_to_ah(pack_params_2.total_discharge)
        elif shared_data.get_command_availability(self.address_int, PackParams2).status == CommandAvailability.Status.AVAILABLE:
            # If PackParams2 command is available but timed out this time, wait for it to recover. Fall back to using the potentially
            # non-high-res SOC from PackStatus only if it differs more than 1% from the last fetched value. This prevents SOC from changing
            # back and forth between high-res and non-high-res values when connection is unstable.
            if self.soc is None or abs(self.soc - pack_status_soc) > 0.999:
                self.soc = pack_status_soc
        else:
            self.soc = pack_status_soc

        self.voltage = self.from_raw_pack_voltage_to_volts(pack_status.pack_voltage)
        self.current = self.from_raw_current_with_offset_to_amps(pack_status.current)
        self.soh = pack_status.soh
        self.capacity = self.from_raw_capacity_to_ah(pack_status.full_capacity)
        self.rated_capacity = self.from_raw_capacity_to_ah(pack_status.rated_capacity)
        self.capacity_remain = self.from_raw_capacity_to_ah(pack_status.remaining_capacity)
        self.discharge_fet = bool(pack_status.mosfet_flags & self.MosfetFlags.DISCHARGE_ENABLED)
        self.charge_fet = bool(pack_status.mosfet_flags & self.MosfetFlags.CHARGE_ENABLED)
        self.pack_serial_number = self.from_raw_string(pack_status.pack_serial_number)
        self.history.charge_cycles = pack_status.charge_cycles
        self.parse_protection_and_alarms(pack_status.fault_flags, pack_status.alarm_flags)

        self.temperature_mos = self.from_raw_temperature_to_celsius(pack_status.mosfet_temp)
        for i in range(pack_status.temperatures_count):
            self.to_temperature(i + 1, self.from_raw_temperature_to_celsius(pack_status.temperatures[i]))

        self.cell_min_voltage = self.from_raw_cell_voltage_to_volts(pack_status.min_cell_voltage)
        self.cell_max_voltage = self.from_raw_cell_voltage_to_volts(pack_status.max_cell_voltage)

        if self.cell_count is None or self.cell_count == 0:
            self.cell_count = pack_status.cell_count
            self.cells = [Cell(False) for _ in range(self.cell_count)]

        for i in range(len(self.cells)):
            self.cells[i].voltage = self.from_raw_cell_voltage_to_volts(pack_status.cell_voltages[i]) if i < pack_status.cell_count else 0
            self.cells[i].balance = bool(pack_status.cell_balancing_flags & (1 << i))

        if self.hardware_version is None:
            # Master does not pass the full firmware version for slaves. Handle both formats.
            firmware_version = (
                f"{pack_status.firmware_version >> 8}.{pack_status.firmware_version & 0xff}"
                if pack_status.firmware_version >= 0x100
                else str(pack_status.firmware_version)
            )
            self.hardware_version = f"JBD UP {self.cell_count}S, FW ver {firmware_version}"

        return True

    def parse_protection_and_alarms(self, fault_flags: int, alarm_flags: int):
        cell_overvoltage_fault = fault_flags & (1 << 0)
        cell_undervoltage_fault = fault_flags & (1 << 1)
        total_overvoltage_fault = fault_flags & (1 << 2)
        total_undervoltage_fault = fault_flags & (1 << 3)
        charge_overcurrent_1_fault = fault_flags & (1 << 4)
        charge_overcurrent_2_fault = fault_flags & (1 << 5)
        discharge_overcurrent_1_fault = fault_flags & (1 << 6)
        discharge_overcurrent_2_fault = fault_flags & (1 << 7)
        charge_high_temp_fault = fault_flags & (1 << 8)
        charge_low_temp_fault = fault_flags & (1 << 9)
        discharge_high_temp_fault = fault_flags & (1 << 10)
        discharge_low_temp_fault = fault_flags & (1 << 11)
        mos_high_temp_fault = fault_flags & (1 << 12)
        ambient_high_temp_fault = fault_flags & (1 << 13)
        ambient_low_temp_fault = fault_flags & (1 << 14)
        voltage_diff_fault = fault_flags & (1 << 15)
        temp_diff_fault = alarm_flags & (1 << 16)
        soc_too_low_fault = fault_flags & (1 << 17)
        short_circuit_fault = fault_flags & (1 << 18)
        cell_offline = fault_flags & (1 << 19)
        temp_sensor_failure = fault_flags & (1 << 20)
        charge_mos_fault = fault_flags & (1 << 21)
        discharge_mos_fault = fault_flags & (1 << 22)
        current_limiting_anomaly = fault_flags & (1 << 23)
        aerosol_fault = fault_flags & (1 << 24)
        full_charge_protection_1 = alarm_flags & (1 << 25)
        abnormal_afe_communication = fault_flags & (1 << 26)
        reverse_protection = fault_flags & (1 << 27)

        cell_overvoltage_alarm = alarm_flags & (1 << 0)
        cell_undervoltage_alarm = alarm_flags & (1 << 1)
        total_overvoltage_alarm = alarm_flags & (1 << 2)
        total_undervoltage_alarm = alarm_flags & (1 << 3)
        charge_overcurrent_alarm = alarm_flags & (1 << 4)
        discharge_overcurrent_alarm = alarm_flags & (1 << 5)
        charge_high_temp_alarm = alarm_flags & (1 << 6)
        charge_low_temp_alarm = alarm_flags & (1 << 7)
        discharge_high_temp_alarm = alarm_flags & (1 << 8)
        discharge_low_temp_alarm = alarm_flags & (1 << 9)
        mos_high_temp_alarm = alarm_flags & (1 << 10)
        ambient_high_temp_alarm = fault_flags & (1 << 11)
        ambient_low_temp_alarm = fault_flags & (1 << 12)
        voltage_diff_alarm = alarm_flags & (1 << 13)
        temp_diff_alarm = alarm_flags & (1 << 14)
        soc_too_low_alarm = alarm_flags & (1 << 15)
        eep_fault_alarm = alarm_flags & (1 << 16)
        rtc_abnormal = alarm_flags & (1 << 17)
        full_charge_protection_2 = alarm_flags & (1 << 18)  # full_charge_protection_2 appears to be always in the same state as full_charge_protection_1

        self.protection.high_cell_voltage = self.from_raw_protection_value(cell_overvoltage_fault, cell_overvoltage_alarm)
        self.protection.low_cell_voltage = self.from_raw_protection_value(cell_undervoltage_fault, cell_undervoltage_alarm)
        self.protection.high_voltage = self.from_raw_protection_value(
            total_overvoltage_fault, total_overvoltage_alarm or full_charge_protection_1 or full_charge_protection_2
        )
        self.protection.low_voltage = self.from_raw_protection_value(total_undervoltage_fault, total_undervoltage_alarm)
        self.protection.high_charge_current = self.from_raw_protection_value(charge_overcurrent_1_fault or charge_overcurrent_2_fault, charge_overcurrent_alarm)
        self.protection.high_discharge_current = self.from_raw_protection_value(
            discharge_overcurrent_1_fault or discharge_overcurrent_2_fault or short_circuit_fault or reverse_protection, discharge_overcurrent_alarm
        )
        self.protection.high_charge_temperature = self.from_raw_protection_value(charge_high_temp_fault, charge_high_temp_alarm)
        self.protection.low_charge_temperature = self.from_raw_protection_value(charge_low_temp_fault, charge_low_temp_alarm)
        self.protection.high_temperature = self.from_raw_protection_value(
            discharge_high_temp_fault or ambient_high_temp_fault, discharge_high_temp_alarm or ambient_high_temp_alarm
        )
        self.protection.low_temperature = self.from_raw_protection_value(
            discharge_low_temp_fault or ambient_low_temp_fault, discharge_low_temp_alarm or ambient_low_temp_alarm
        )
        self.protection.high_internal_temperature = self.from_raw_protection_value(mos_high_temp_fault, mos_high_temp_alarm)
        # Since there's no other suitable place, show temp_diff_fault and temp_diff_alarm as cell_imbalance. This is presumably better than hiding the alarm
        # completely.
        self.protection.cell_imbalance = self.from_raw_protection_value(voltage_diff_fault or temp_diff_fault, voltage_diff_alarm or temp_diff_alarm)
        self.protection.low_soc = self.from_raw_protection_value(soc_too_low_fault, soc_too_low_alarm)
        self.protection.internal_failure = self.from_raw_protection_value(
            eep_fault_alarm
            or cell_offline
            or temp_sensor_failure
            or charge_mos_fault
            or discharge_mos_fault
            or current_limiting_anomaly
            or aerosol_fault
            or abnormal_afe_communication
            or rtc_abnormal,
            False,
        )

    @staticmethod
    def from_raw_protection_value(has_alarm: bool, has_warning: bool) -> int:
        if has_alarm:
            return Protection.ALARM
        if has_warning:
            return Protection.WARNING
        return Protection.OK

    @staticmethod
    def from_raw_temperature_to_celsius(raw_value: int) -> float:
        return (raw_value - 500) / 10

    @staticmethod
    def from_raw_current_with_offset_to_amps(raw_value: int) -> float:
        return (raw_value - 300000) / 100

    @staticmethod
    def from_raw_current_to_amps(raw_value: int) -> float:
        return raw_value / 10

    @staticmethod
    def from_raw_dvcc_voltage_to_volts(raw_value: int) -> float:
        return raw_value / 10

    @staticmethod
    def from_raw_pack_voltage_to_volts(raw_value: int) -> float:
        return raw_value / 100

    @staticmethod
    def from_raw_cell_voltage_to_volts(raw_value: int) -> float:
        return raw_value / 1000

    @staticmethod
    def from_raw_capacity_to_ah(raw_value: int) -> float:
        return raw_value / 100

    @staticmethod
    def from_raw_total_charge_discharge_to_ah(raw_value: int) -> float:
        return raw_value / 10

    @staticmethod
    def from_raw_high_resolution_percentage(raw_value: int) -> float:
        return raw_value / 100

    @staticmethod
    def to_raw_high_resolution_percentage(value: float) -> int:
        return round(value * 100)

    @staticmethod
    def from_raw_string(raw_value: bytes) -> str:
        return raw_value.rstrip(b"\x00").decode("ascii", errors="ignore")

    @staticmethod
    def append_once(array, item):
        if item not in array:
            array.append(item)

    @staticmethod
    def apply_aggregated_current_limit_from_master(slave_value: float, master_value: Optional[float], update_timestamp: float):
        return (
            slave_value
            if master_value is None or update_timestamp < time.monotonic() - MASTER_AGGREGATED_VALUE_TIMEOUT_SECONDS
            else min(slave_value, master_value)
        )

    @staticmethod
    def calc_crc16(data: bytes) -> int:
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc

    def is_master(self) -> bool:
        """Return whether this BMS considers itself a master. Master is always on address 1."""
        return self.address_int == 1

    def parse_frame(self, response: bytes, cmd: Type[CommandT]) -> Optional[bytes]:
        """Parse and validate a response. Returns the payload or None."""
        if len(response) < FrameHeader.STRUCT.size:
            logger.warning(
                f"Response is too short for header for battery {self.address_int} {cmd.__name__}: expected {FrameHeader.STRUCT.size}, got {len(response)} bytes"
            )
            return None

        try:
            header = FrameHeader(*FrameHeader.STRUCT.unpack_from(response))
        except StructError:
            logger.exception("Error unpacking response header for battery {self.address_int} {cmd.__name__}")
            return None

        if header.battery_address != self.address_int:
            logger.warning(f"Address mismatch in battery {self.address_int} {cmd.__name__}: expected {self.address_int}, got {header.battery_address}")
            return None

        if header.function_code != cmd.MODBUS_FUNC:
            logger.warning(
                f"Function code mismatch for battery {self.address_int} {cmd.__name__}: expected 0x{cmd.MODBUS_FUNC:02x}, got 0x{header.function_code:02x}"
            )
            return None

        # Extract the payload (between header and CRC)
        payload_start = FrameHeader.STRUCT.size
        payload_end = payload_start + header.payload_len
        expected_response_size = payload_end + CRC_STRUCT.size

        if len(response) < expected_response_size:
            logger.warning(f"Response incomplete for battery {self.address_int} {cmd.__name__}: expected {expected_response_size}, got {len(response)} bytes")
            return None

        payload = response[payload_start:payload_end]

        crc_received = CRC_STRUCT.unpack_from(response, payload_end)[0]
        crc_calculated = self.calc_crc16(response[:payload_end])
        if crc_received != crc_calculated:
            logger.warning(f"CRC mismatch for battery {self.address_int} {cmd.__name__}: expected 0x{crc_calculated:04X}, got 0x{crc_received:04X}")
            return None

        return payload

    def send_request_and_parse_response(self, ser, cmd: Type[CommandT], request_payload=bytes()) -> Optional[CommandT]:
        availability = shared_data.get_command_availability(self.address_int, cmd)
        if availability.status == CommandAvailability.Status.UNAVAILABLE:
            return None

        parsed_response_payload = None
        try:
            parsed_response_payload = self.send_request_and_parse_response_internal(ser, cmd, request_payload)
        except Exception:
            logger.exception("Exception in send_request_and_parse_response_internal")

        if parsed_response_payload:
            if availability.status != CommandAvailability.Status.AVAILABLE:
                # Declare this command on this battery address as available after the response is parsed successfully.
                logger.info(f"Marking {cmd.__name__} command available on battery {self.address_int}")
                availability.status = CommandAvailability.Status.AVAILABLE
        elif availability.status == CommandAvailability.Status.UNKNOWN and not self.check_for_interference(ser):
            # Increase unsuccessful command availability retry count on an unsuccessful response that's not caused by temporary serial communication
            # interference from another process.
            availability.retries += 1
            if availability.retries >= MAX_AVAILABILITY_RETRIES:
                log_message = f"Marking {cmd.__name__} command unavailable on battery {self.address_int}"
                if self.is_master():
                    logger.warning(log_message)
                else:
                    logger.info(f"{log_message}. This is often normal and depends on your cabling configuration")
                availability.status = CommandAvailability.Status.UNAVAILABLE

        return parsed_response_payload

    def send_request_and_parse_response_internal(self, ser, cmd: Type[CommandT], request_payload: bytes) -> Optional[CommandT]:
        request = pack(">BBHHH", self.address_int, cmd.MODBUS_FUNC, cmd.MODBUS_START_ADDR, cmd.MODBUS_START_ADDR + cmd.MODBUS_ADDR_LEN, len(request_payload))
        request += request_payload
        request += CRC_STRUCT.pack(self.calc_crc16(request))  # CRC is a special case that has its least significant byte first.
        # logger.info(f"{cmd.__name__} request: {request.hex(' ')}")

        response = read_serialport_data(
            ser,
            request,
            SERIAL_TIMEOUT_SECONDS,
            # Length of header up to and including the length value + CRC length:
            self.RESPONSE_PAYLOAD_LEN_OFFS + BIG_ENDIAN_SHORT_INT_STRUCT.size + CRC_STRUCT.size,
            self.RESPONSE_PAYLOAD_LEN_OFFS,
            "H",
        )

        if response is None:
            return None

        # logger.info(f"{cmd.__name__} response: {response.hex(' ')}")
        response_payload = self.parse_frame(response, cmd)
        if response_payload is None:
            return None

        try:
            parsed_response_payload = cmd.from_bytes(response_payload)
        except StructError:
            logger.exception(f"Error unpacking {cmd.__name__} for battery {self.address_int}")
            return None

        # logger.info(f"{cmd.__name__} at {self.address_int}: {parsed_response_payload}")
        return parsed_response_payload

    def check_for_interference(self, ser) -> bool:
        """Returns True if another process changed the serial port settings. Depending on user's setup, such interference can affect battery detection
        up to almost every time. This lets us detect the inteference and wait for it to stop."""
        try:
            attr = termios.tcgetattr(ser)
            return attr[4] != termios.B9600 or attr[5] != termios.B9600 or attr[2] & termios.CSIZE != termios.CS8
        except Exception:
            logger.exception("Couldn't check whether there's serial connection interference")
            return False

    def open_serial_connection_with_retry_on_interference(self, fn, max_non_interference_retries=1):
        non_interference_retries = 0
        deadline = time.monotonic() + MAX_INTERFERENCE_RETRY_SECONDS
        while time.monotonic() < deadline:
            # Reopen serial port again after inteference, to restore the communication parameters
            with self.serial_connection() as ser:
                if ser:
                    result = fn(ser)
                    if result:
                        return result
                    if self.check_for_interference(ser):
                        logger.warning("Another process is interfering with serial communication. Retrying...")
                    else:
                        non_interference_retries += 1
                else:
                    # It's not clear whether this branch is ever called, but since we already have the retry logic, we can use it for this case too.
                    logger.warning("Can't open serial connection. Retrying...")
                    non_interference_retries += 1
                if non_interference_retries >= max_non_interference_retries:
                    return result
            time.sleep(INTERFERENCE_DELAY_SECONDS)
        return False

    @contextmanager
    def serial_connection(self):
        try:
            with serial.Serial(self.port, baudrate=self.baud_rate, timeout=SERIAL_TIMEOUT_SECONDS) as ser:
                yield ser
        except Exception:
            logger.exception("Serial connection exception")
            yield None
