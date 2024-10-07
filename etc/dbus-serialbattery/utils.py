# -*- coding: utf-8 -*-
# Standard library imports
import bisect
import configparser
import logging
import sys
from pathlib import Path
from struct import unpack_from
from time import sleep
from typing import List, Any, Callable, Union

# Third-party imports
import serial


# CONSTANTS
DRIVER_VERSION: str = "1.5.20241007eg-lifepower"
"""
current version of the driver
"""

ZERO_CHAR: str = chr(48)
"""
number zero (`0`)
"""

DEGREE_SIGN: str = "\N{DEGREE SIGN}"
"""
degree sign (`°`)
"""


# LOGGING
logging.basicConfig()
logger = logging.getLogger("SerialBattery")

PATH_CONFIG_DEFAULT: str = "config.default.ini"
PATH_CONFIG_USER: str = "config.ini"

config = configparser.ConfigParser()
path = Path(__file__).parents[0]
default_config_file_path = path.joinpath(PATH_CONFIG_DEFAULT).absolute().__str__()
custom_config_file_path = path.joinpath(PATH_CONFIG_USER).absolute().__str__()
config.read([default_config_file_path, custom_config_file_path])

# get logging level from config file
if config["DEFAULT"]["LOGGING"].upper() == "ERROR":
    logger.setLevel(logging.ERROR)
elif config["DEFAULT"]["LOGGING"].upper() == "WARNING":
    logger.setLevel(logging.WARNING)
elif config["DEFAULT"]["LOGGING"].upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)


# list to store config errors
# this is needed else the errors are not instantly visible
errors_in_config = []


# FUNCTIONS needed for config parsing
def _get_list_from_config(
    group: str, option: str, mapper: Callable[[Any], Any] = lambda v: v
) -> List[Any]:
    """
    Get a string with comma separated values from the config file and return a list of values

    :param group: Group in the config file
    :param option: Option in the config file
    :param mapper: Function to map the values to the correct type
    :return: List of values
    """
    rawList = config[group][option].split(",")
    return list(
        map(
            mapper,
            [item.strip() for item in rawList if item != "" and item is not None],
        )
    )


# SAVE CONFIG VALUES to constants
# --------- Battery Current limits ---------
MAX_BATTERY_CHARGE_CURRENT: float = float(
    config["DEFAULT"]["MAX_BATTERY_CHARGE_CURRENT"]
)
"""
Defines the maximum charge current that the battery can accept.
"""
MAX_BATTERY_DISCHARGE_CURRENT: float = float(
    config["DEFAULT"]["MAX_BATTERY_DISCHARGE_CURRENT"]
)
"""
Defines the maximum discharge current that the battery can deliver.
"""

# --------- Cell Voltages ---------
MIN_CELL_VOLTAGE: float = float(config["DEFAULT"]["MIN_CELL_VOLTAGE"])
"""
Defines the minimum cell voltage that the battery can have.
Used for:
- Limit CVL range
- SoC calculation (if enabled)
"""
MAX_CELL_VOLTAGE: float = float(config["DEFAULT"]["MAX_CELL_VOLTAGE"])
"""
Defines the maximum cell voltage that the battery can have.
Used for:
- Limit CVL range
- SoC calculation (if enabled)
"""

FLOAT_CELL_VOLTAGE: float = float(config["DEFAULT"]["FLOAT_CELL_VOLTAGE"])
"""
Defines the cell voltage that the battery should have when it is fully charged.
"""

# make some checks for most common missconfigurations
if FLOAT_CELL_VOLTAGE > MAX_CELL_VOLTAGE:
    errors_in_config.append(
        f"**CONFIG ISSUE**: FLOAT_CELL_VOLTAGE ({FLOAT_CELL_VOLTAGE} V) is greater than MAX_CELL_VOLTAGE ({MAX_CELL_VOLTAGE} V). "
        + "To ensure that the driver still works correctly, FLOAT_CELL_VOLTAGE was set to MAX_CELL_VOLTAGE. Please check the configuration."
    )
    FLOAT_CELL_VOLTAGE = MAX_CELL_VOLTAGE

# make some checks for most common missconfigurations
if FLOAT_CELL_VOLTAGE < MIN_CELL_VOLTAGE:
    errors_in_config.append(
        "**CONFIG ISSUE**: FLOAT_CELL_VOLTAGE ({FLOAT_CELL_VOLTAGE} V) is less than MIN_CELL_VOLTAGE ({MIN_CELL_VOLTAGE} V). "
        + "To ensure that the driver still works correctly, FLOAT_CELL_VOLTAGE was set to MIN_CELL_VOLTAGE. Please check the configuration."
    )
    FLOAT_CELL_VOLTAGE = MIN_CELL_VOLTAGE

SOC_RESET_VOLTAGE: float = float(config["DEFAULT"]["SOC_RESET_VOLTAGE"])
SOC_RESET_AFTER_DAYS: int = (
    int(config["DEFAULT"]["SOC_RESET_AFTER_DAYS"])
    if config["DEFAULT"]["SOC_RESET_AFTER_DAYS"] != ""
    else False
)

# make some checks for most common missconfigurations
if SOC_RESET_AFTER_DAYS and SOC_RESET_VOLTAGE < MAX_CELL_VOLTAGE:
    errors_in_config.append(
        "**CONFIG ISSUE**: SOC_RESET_VOLTAGE ({SOC_RESET_VOLTAGE} V) is less than MAX_CELL_VOLTAGE ({MAX_CELL_VOLTAGE} V). "
        + "To ensure that the driver still works correctly, SOC_RESET_VOLTAGE was set to MAX_CELL_VOLTAGE. Please check the configuration."
    )
    SOC_RESET_VOLTAGE = MAX_CELL_VOLTAGE

# --------- Modbus (multiple BMS on one serial adapter) ---------
MODBUS_ADDRESSES: list = _get_list_from_config(
    "DEFAULT", "MODBUS_ADDRESSES", lambda v: str(v)
)

# --------- BMS disconnect behaviour ---------
BLOCK_ON_DISCONNECT: bool = "True" == config["DEFAULT"]["BLOCK_ON_DISCONNECT"]
BLOCK_ON_DISCONNECT_TIMEOUT_MINUTES: float = float(
    config["DEFAULT"]["BLOCK_ON_DISCONNECT_TIMEOUT_MINUTES"]
)
BLOCK_ON_DISCONNECT_VOLTAGE_MIN: float = float(
    config["DEFAULT"]["BLOCK_ON_DISCONNECT_VOLTAGE_MIN"]
)
BLOCK_ON_DISCONNECT_VOLTAGE_MAX: float = float(
    config["DEFAULT"]["BLOCK_ON_DISCONNECT_VOLTAGE_MAX"]
)

# make some checks for most common missconfigurations
if not BLOCK_ON_DISCONNECT:
    if BLOCK_ON_DISCONNECT_VOLTAGE_MIN < MIN_CELL_VOLTAGE:
        errors_in_config.append(
            f"**CONFIG ISSUE**: BLOCK_ON_DISCONNECT_VOLTAGE_MIN ({BLOCK_ON_DISCONNECT_VOLTAGE_MIN} V) is less than MIN_CELL_VOLTAGE ({MIN_CELL_VOLTAGE} V). "
            + "To ensure that the driver still works correctly, BLOCK_ON_DISCONNECT_VOLTAGE_MIN was set to MIN_CELL_VOLTAGE. Please check the configuration."
        )
        BLOCK_ON_DISCONNECT_VOLTAGE_MIN = MIN_CELL_VOLTAGE

    if BLOCK_ON_DISCONNECT_VOLTAGE_MAX > MAX_CELL_VOLTAGE:
        errors_in_config.append(
            f"**CONFIG ISSUE**: BLOCK_ON_DISCONNECT_VOLTAGE_MAX ({BLOCK_ON_DISCONNECT_VOLTAGE_MAX} V) is greater than MAX_CELL_VOLTAGE ({MAX_CELL_VOLTAGE} V). "
            + "To ensure that the driver still works correctly, BLOCK_ON_DISCONNECT_VOLTAGE_MAX was set to MAX_CELL_VOLTAGE. Please check the configuration."
        )
        BLOCK_ON_DISCONNECT_VOLTAGE_MAX = MAX_CELL_VOLTAGE

    if BLOCK_ON_DISCONNECT_VOLTAGE_MIN >= BLOCK_ON_DISCONNECT_VOLTAGE_MAX:
        errors_in_config.append(
            f"**CONFIG ISSUE**: BLOCK_ON_DISCONNECT_VOLTAGE_MIN ({BLOCK_ON_DISCONNECT_VOLTAGE_MIN} V) "
            + f"is greater or equal to BLOCK_ON_DISCONNECT_VOLTAGE_MAX ({BLOCK_ON_DISCONNECT_VOLTAGE_MAX} V). "
            + "For safety reasons BLOCK_ON_DISCONNECT was set to True. Please check the configuration."
        )
        BLOCK_ON_DISCONNECT = True


# --------- Charge mode ---------
LINEAR_LIMITATION_ENABLE: bool = "True" == config["DEFAULT"]["LINEAR_LIMITATION_ENABLE"]
LINEAR_RECALCULATION_EVERY: int = int(config["DEFAULT"]["LINEAR_RECALCULATION_EVERY"])
LINEAR_RECALCULATION_ON_PERC_CHANGE: int = int(
    config["DEFAULT"]["LINEAR_RECALCULATION_ON_PERC_CHANGE"]
)

# --------- External current sensor ---------
EXTERNAL_CURRENT_SENSOR_DBUS_DEVICE: str = (
    config["DEFAULT"]["EXTERNAL_CURRENT_SENSOR_DBUS_DEVICE"]
    if config["DEFAULT"]["EXTERNAL_CURRENT_SENSOR_DBUS_DEVICE"] != ""
    else None
)
EXTERNAL_CURRENT_SENSOR_DBUS_PATH: str = (
    config["DEFAULT"]["EXTERNAL_CURRENT_SENSOR_DBUS_PATH"]
    if config["DEFAULT"]["EXTERNAL_CURRENT_SENSOR_DBUS_PATH"] != ""
    else None
)

# --------- Charge Voltage limitation (affecting CVL) ---------
CVCM_ENABLE: bool = "True" == config["DEFAULT"]["CVCM_ENABLE"]
"""
Charge voltage control management

Limits max charging voltage (CVL). Switch from max to float voltage and back.
"""

CELL_VOLTAGE_DIFF_KEEP_MAX_VOLTAGE_UNTIL: float = float(
    config["DEFAULT"]["CELL_VOLTAGE_DIFF_KEEP_MAX_VOLTAGE_UNTIL"]
)
CELL_VOLTAGE_DIFF_KEEP_MAX_VOLTAGE_TIME_RESTART: float = float(
    config["DEFAULT"]["CELL_VOLTAGE_DIFF_KEEP_MAX_VOLTAGE_TIME_RESTART"]
)
CELL_VOLTAGE_DIFF_TO_RESET_VOLTAGE_LIMIT: float = float(
    config["DEFAULT"]["CELL_VOLTAGE_DIFF_TO_RESET_VOLTAGE_LIMIT"]
)

MAX_VOLTAGE_TIME_SEC: int = int(config["DEFAULT"]["MAX_VOLTAGE_TIME_SEC"])
SOC_LEVEL_TO_RESET_VOLTAGE_LIMIT: int = int(
    config["DEFAULT"]["SOC_LEVEL_TO_RESET_VOLTAGE_LIMIT"]
)

CCCM_CV_ENABLE: bool = "True" == config["DEFAULT"]["CCCM_CV_ENABLE"]
"""
Charge current control management referring to cell-voltage
"""

DCCM_CV_ENABLE: bool = "True" == config["DEFAULT"]["DCCM_CV_ENABLE"]
"""
Discharge current control management referring to cell-voltage
"""

CELL_VOLTAGES_WHILE_CHARGING: list = _get_list_from_config(
    "DEFAULT", "CELL_VOLTAGES_WHILE_CHARGING", lambda v: float(v)
)
MAX_CHARGE_CURRENT_CV: list = _get_list_from_config(
    "DEFAULT",
    "MAX_CHARGE_CURRENT_CV_FRACTION",
    lambda v: MAX_BATTERY_CHARGE_CURRENT * float(v),
)
# make some checks for most common missconfigurations
if CELL_VOLTAGES_WHILE_CHARGING[0] < MAX_CELL_VOLTAGE and MAX_CHARGE_CURRENT_CV[0] == 0:
    errors_in_config.append(
        f"**CONFIG ISSUE**: Maximum value of CELL_VOLTAGES_WHILE_CHARGING ({CELL_VOLTAGES_WHILE_CHARGING[0]} V) "
        + f"is lower than MAX_CELL_VOLTAGE ({MAX_CELL_VOLTAGE} V). MAX_CELL_VOLTAGE will never be reached this way "
        + "and battery will not change to float. Please check the configuration."
    )
# make some checks for most common missconfigurations
if (
    SOC_RESET_AFTER_DAYS is not False
    and CELL_VOLTAGES_WHILE_CHARGING[0] < SOC_RESET_VOLTAGE
    and MAX_CHARGE_CURRENT_CV[0] == 0
):
    errors_in_config.append(
        f"**CONFIG ISSUE**: Maximum value of CELL_VOLTAGES_WHILE_CHARGING ({CELL_VOLTAGES_WHILE_CHARGING[0]} V) "
        + f"is lower than SOC_RESET_VOLTAGE ({SOC_RESET_VOLTAGE} V). SOC_RESET_VOLTAGE will never be reached this way "
        + "and battery will not change to float. Please check the configuration."
    )
# make some checks for most common missconfigurations
if MAX_BATTERY_CHARGE_CURRENT not in MAX_CHARGE_CURRENT_CV:
    errors_in_config.append(
        f"**CONFIG ISSUE**: In MAX_CHARGE_CURRENT_CV_FRACTION ({', '.join(map(str, _get_list_from_config('DEFAULT', 'MAX_CHARGE_CURRENT_CV_FRACTION', lambda v: float(v))))}) "
        + "there is no value set to 1. This means that the battery will never use the maximum charge current. Please check the configuration."
    )

CELL_VOLTAGES_WHILE_DISCHARGING: list = _get_list_from_config(
    "DEFAULT", "CELL_VOLTAGES_WHILE_DISCHARGING", lambda v: float(v)
)
MAX_DISCHARGE_CURRENT_CV: list = _get_list_from_config(
    "DEFAULT",
    "MAX_DISCHARGE_CURRENT_CV_FRACTION",
    lambda v: MAX_BATTERY_DISCHARGE_CURRENT * float(v),
)
# make some checks for most common missconfigurations
if (
    CELL_VOLTAGES_WHILE_DISCHARGING[0] > MIN_CELL_VOLTAGE
    and MAX_DISCHARGE_CURRENT_CV[0] == 0
):
    errors_in_config.append(
        f"**CONFIG ISSUE**: Minimum value of CELL_VOLTAGES_WHILE_DISCHARGING ({CELL_VOLTAGES_WHILE_DISCHARGING[0]} V) "
        + f"is higher than MIN_CELL_VOLTAGE ({MIN_CELL_VOLTAGE} V). MIN_CELL_VOLTAGE will never be reached this way. "
        + "Please check the configuration."
    )
# make some checks for most common missconfigurations
if MAX_BATTERY_DISCHARGE_CURRENT not in MAX_DISCHARGE_CURRENT_CV:
    errors_in_config.append(
        f"**CONFIG ISSUE**: In MAX_DISCHARGE_CURRENT_CV_FRACTION ({', '.join(map(str, _get_list_from_config('DEFAULT', 'MAX_DISCHARGE_CURRENT_CV_FRACTION', lambda v: float(v))))}) "
        + "there is no value set to 1. This means that the battery will never use the maximum discharge current. Please check the configuration."
    )

# --------- Cell Voltage limitation (affecting CVL) ---------

CVL_ICONTROLLER_MODE: bool = "True" == config["DEFAULT"]["CVL_ICONTROLLER_MODE"]
CVL_ICONTROLLER_FACTOR: float = float(config["DEFAULT"]["CVL_ICONTROLLER_FACTOR"])

# --------- Temperature limitation (affecting CCL/DCL) ---------
CCCM_T_ENABLE: bool = "True" == config["DEFAULT"]["CCCM_T_ENABLE"]
"""
Charge current control management referring to temperature
"""

DCCM_T_ENABLE: bool = "True" == config["DEFAULT"]["DCCM_T_ENABLE"]
"""
Discharge current control management referring to temperature
"""

TEMPERATURES_WHILE_CHARGING: list = _get_list_from_config(
    "DEFAULT", "TEMPERATURES_WHILE_CHARGING", lambda v: float(v)
)
MAX_CHARGE_CURRENT_T: list = _get_list_from_config(
    "DEFAULT",
    "MAX_CHARGE_CURRENT_T_FRACTION",
    lambda v: MAX_BATTERY_CHARGE_CURRENT * float(v),
)
# make some checks for most common missconfigurations
if MAX_BATTERY_CHARGE_CURRENT not in MAX_CHARGE_CURRENT_T:
    errors_in_config.append(
        f"**CONFIG ISSUE**: In MAX_CHARGE_CURRENT_T_FRACTION ({', '.join(map(str, _get_list_from_config('DEFAULT', 'MAX_CHARGE_CURRENT_T_FRACTION', lambda v: float(v))))}) "
        + "there is no value set to 1. This means that the battery will never use the maximum discharge current. Please check the configuration."
    )

TEMPERATURES_WHILE_DISCHARGING: list = _get_list_from_config(
    "DEFAULT", "TEMPERATURES_WHILE_DISCHARGING", lambda v: float(v)
)
MAX_DISCHARGE_CURRENT_T: list = _get_list_from_config(
    "DEFAULT",
    "MAX_DISCHARGE_CURRENT_T_FRACTION",
    lambda v: MAX_BATTERY_DISCHARGE_CURRENT * float(v),
)
# make some checks for most common missconfigurations
if MAX_BATTERY_DISCHARGE_CURRENT not in MAX_DISCHARGE_CURRENT_T:
    errors_in_config.append(
        f"**CONFIG ISSUE**: In MAX_DISCHARGE_CURRENT_T_FRACTION ({', '.join(map(str, _get_list_from_config('DEFAULT', 'MAX_DISCHARGE_CURRENT_T_FRACTION', lambda v: float(v))))}) "
        + "there is no value set to 1. This means that the battery will never use the maximum discharge current. Please check the configuration."
    )

# --------- SOC limitation (affecting CCL/DCL) ---------
CCCM_SOC_ENABLE: bool = "True" == config["DEFAULT"]["CCCM_SOC_ENABLE"]
"""
Charge current control management referring to SoC
"""

DCCM_SOC_ENABLE: bool = "True" == config["DEFAULT"]["DCCM_SOC_ENABLE"]
"""
Discharge current control management referring to SoC
"""

SOC_WHILE_CHARGING: list = _get_list_from_config(
    "DEFAULT", "SOC_WHILE_CHARGING", lambda v: float(v)
)
MAX_CHARGE_CURRENT_SOC: list = _get_list_from_config(
    "DEFAULT",
    "MAX_CHARGE_CURRENT_SOC_FRACTION",
    lambda v: MAX_BATTERY_CHARGE_CURRENT * float(v),
)
# make some checks for most common missconfigurations
if MAX_BATTERY_CHARGE_CURRENT not in MAX_CHARGE_CURRENT_SOC:
    errors_in_config.append(
        f"**CONFIG ISSUE**: In MAX_CHARGE_CURRENT_SOC_FRACTION ({', '.join(map(str, _get_list_from_config('DEFAULT', 'MAX_CHARGE_CURRENT_SOC_FRACTION', lambda v: float(v))))}) "
        + "there is no value set to 1. This means that the battery will never use the maximum charge current. Please check the configuration."
    )

SOC_WHILE_DISCHARGING: list = _get_list_from_config(
    "DEFAULT", "SOC_WHILE_DISCHARGING", lambda v: float(v)
)
MAX_DISCHARGE_CURRENT_SOC: list = _get_list_from_config(
    "DEFAULT",
    "MAX_DISCHARGE_CURRENT_SOC_FRACTION",
    lambda v: MAX_BATTERY_DISCHARGE_CURRENT * float(v),
)
# make some checks for most common missconfigurations
if MAX_BATTERY_DISCHARGE_CURRENT not in MAX_DISCHARGE_CURRENT_SOC:
    errors_in_config.append(
        f"**CONFIG ISSUE**: In MAX_DISCHARGE_CURRENT_SOC_FRACTION ({', '.join(map(str, _get_list_from_config('DEFAULT', 'MAX_DISCHARGE_CURRENT_SOC_FRACTION', lambda v: float(v))))}) "
        + "there is no value set to 1. This means that the battery will never use the maximum discharge current. Please check the configuration."
    )

# --------- Time-To-Go ---------
TIME_TO_GO_ENABLE: bool = "True" == config["DEFAULT"]["TIME_TO_GO_ENABLE"]

# --------- Time-To-Soc ---------
TIME_TO_SOC_POINTS: list = _get_list_from_config(
    "DEFAULT", "TIME_TO_SOC_POINTS", lambda v: int(v)
)
TIME_TO_SOC_VALUE_TYPE: int = int(config["DEFAULT"]["TIME_TO_SOC_VALUE_TYPE"])
TIME_TO_SOC_RECALCULATE_EVERY: int = (
    int(config["DEFAULT"]["TIME_TO_SOC_RECALCULATE_EVERY"])
    if int(config["DEFAULT"]["TIME_TO_SOC_RECALCULATE_EVERY"]) > 5
    else 5
)
TIME_TO_SOC_INC_FROM: bool = "True" == config["DEFAULT"]["TIME_TO_SOC_INC_FROM"]

# --------- SOC calculation ---------
SOC_CALCULATION: bool = "True" == config["DEFAULT"]["SOC_CALCULATION"]
SOC_RESET_CURRENT: float = float(config["DEFAULT"]["SOC_RESET_CURRENT"])
SOC_RESET_TIME: int = int(config["DEFAULT"]["SOC_RESET_TIME"])
SOC_CALC_CURRENT_REPORTED_BY_BMS: list = _get_list_from_config(
    "DEFAULT", "SOC_CALC_CURRENT_REPORTED_BY_BMS", lambda v: float(v)
)
SOC_CALC_CURRENT_MEASURED_BY_USER: list = _get_list_from_config(
    "DEFAULT", "SOC_CALC_CURRENT_MEASURED_BY_USER", lambda v: float(v)
)
# check if lists are different
# this allows to calculate linear relationship between the two lists only if needed
if SOC_CALC_CURRENT_REPORTED_BY_BMS == SOC_CALC_CURRENT_MEASURED_BY_USER:
    SOC_CALC_CURRENT: bool = False
else:
    SOC_CALC_CURRENT: bool = True

# --------- Additional settings ---------
BMS_TYPE: list = _get_list_from_config("DEFAULT", "BMS_TYPE", lambda v: str(v))

EXCLUDED_DEVICES: list = _get_list_from_config(
    "DEFAULT", "EXCLUDED_DEVICES", lambda v: str(v)
)

POLL_INTERVAL: float = (
    float(config["DEFAULT"]["POLL_INTERVAL"]) * 1000
    if config["DEFAULT"]["POLL_INTERVAL"] != ""
    else None
)
"""
Poll interval in milliseconds
"""

# Auto reset SoC
AUTO_RESET_SOC: bool = "True" == config["DEFAULT"]["AUTO_RESET_SOC"]

# Publish the config settings to the dbus path "/Info/Config/"
PUBLISH_CONFIG_VALUES: bool = "True" == config["DEFAULT"]["PUBLISH_CONFIG_VALUES"]

BATTERY_CELL_DATA_FORMAT: int = int(config["DEFAULT"]["BATTERY_CELL_DATA_FORMAT"])

MIDPOINT_ENABLE: bool = "True" == config["DEFAULT"]["MIDPOINT_ENABLE"]

TEMP_BATTERY: int = int(config["DEFAULT"]["TEMP_BATTERY"])

TEMP_1_NAME: str = config["DEFAULT"]["TEMP_1_NAME"]
TEMP_2_NAME: str = config["DEFAULT"]["TEMP_2_NAME"]
TEMP_3_NAME: str = config["DEFAULT"]["TEMP_3_NAME"]
TEMP_4_NAME: str = config["DEFAULT"]["TEMP_4_NAME"]

TELEMETRY: bool = "True" == config["DEFAULT"]["TELEMETRY"]

GUI_PARAMETERS_SHOW_ADDITIONAL_INFO: bool = (
    "True" == config["DEFAULT"]["GUI_PARAMETERS_SHOW_ADDITIONAL_INFO"]
)
# --------- BMS specific settings ---------

# -- Unique ID settings
USE_PORT_AS_UNIQUE_ID: bool = "True" == config["DEFAULT"]["USE_PORT_AS_UNIQUE_ID"]

# -- LltJbd settings
SOC_LOW_WARNING: float = float(config["DEFAULT"]["SOC_LOW_WARNING"])
SOC_LOW_ALARM: float = float(config["DEFAULT"]["SOC_LOW_ALARM"])

# -- Daly settings
BATTERY_CAPACITY: float = float(config["DEFAULT"]["BATTERY_CAPACITY"])
INVERT_CURRENT_MEASUREMENT: int = int(config["DEFAULT"]["INVERT_CURRENT_MEASUREMENT"])

# -- JK BMS settings
JKBMS_CAN_CELL_COUNT: int = int(config["DEFAULT"]["JKBMS_CAN_CELL_COUNT"])

# -- ESC GreenMeter and Lipro device settings
GREENMETER_ADDRESS: int = int(config["DEFAULT"]["GREENMETER_ADDRESS"])
LIPRO_START_ADDRESS: int = int(config["DEFAULT"]["LIPRO_START_ADDRESS"])
LIPRO_END_ADDRESS: int = int(config["DEFAULT"]["LIPRO_END_ADDRESS"])
LIPRO_CELL_COUNT: int = int(config["DEFAULT"]["LIPRO_CELL_COUNT"])

# -- Seplos V3 settings
SEPLOS_USE_BMS_VALUES: bool = "True" == config["DEFAULT"]["SEPLOS_USE_BMS_VALUES"]

# --------- Voltage drop ---------
VOLTAGE_DROP: float = float(config["DEFAULT"]["VOLTAGE_DROP"])


# FUNCTIONS
def constrain(val: float, min_val: float, max_val: float) -> float:
    """
    Constrain a value between a minimum and maximum value

    :param val: Value to constrain
    :param min_val: Minimum value
    :param max_val: Maximum value
    :return: Constrained value
    """
    # Swap min and max if min is greater than max
    if min_val > max_val:
        min_val, max_val = max_val, min_val
    return min(max_val, max(min_val, val))


def mapRange(
    inValue: float, inMin: float, inMax: float, outMin: float, outMax: float
) -> float:
    """
    Map a value from one range to another

    :param inValue: Input value
    :param inMin: Minimum value of the input range
    :param inMax: Maximum value of the input range
    :param outMin: Minimum value of the output range
    :param outMax: Maximum value of the output range
    :return: Mapped value
    """
    return outMin + (((inValue - inMin) / (inMax - inMin)) * (outMax - outMin))


def mapRangeConstrain(
    inValue: float, inMin: float, inMax: float, outMin: float, outMax: float
) -> float:
    """
    Map a value from one range to another and constrain it between the output range

    :param inValue: Input value
    :param inMin: Minimum value of the input range
    :param inMax: Maximum value of the input range
    :param outMin: Minimum value of the output range
    :param outMax: Maximum value of the output range
    :return: Mapped and constrained value
    """
    return constrain(mapRange(inValue, inMin, inMax, outMin, outMax), outMin, outMax)


def calcLinearRelationship(inValue: float, inArray: float, outArray: float) -> float:
    """
    Calculate a linear relationship between two arrays

    :param inValue: Input value
    :param inArray: Input array
    :param outArray: Output array
    :return: Calculated value
    """
    # change compare-direction in array
    if inArray[0] > inArray[-1]:
        return calcLinearRelationship(inValue, inArray[::-1], outArray[::-1])
    else:
        # Handle out of bounds
        if inValue <= inArray[0]:
            return outArray[0]
        if inValue >= inArray[-1]:
            return outArray[-1]

        # else calculate linear current between the setpoints
        idx = bisect.bisect(inArray, inValue)
        upperIN = inArray[idx - 1]  # begin with idx 0 as max value
        upperOUT = outArray[idx - 1]
        lowerIN = inArray[idx]
        lowerOUT = outArray[idx]
        return mapRangeConstrain(inValue, lowerIN, upperIN, lowerOUT, upperOUT)


def calcStepRelationship(
    inValue: float, inArray: float, outArray: float, returnLower: float
) -> float:
    """
    Calculate a step relationship between two arrays

    :param inValue: Input value
    :param inArray: Input array
    :param outArray: Output array
    :param returnLower: Return lower value if True, else return higher value
    :return: Calculated value
    """
    # change compare-direction in array
    if inArray[0] > inArray[-1]:
        return calcStepRelationship(inValue, inArray[::-1], outArray[::-1], returnLower)

    # Handle out of bounds
    if inValue <= inArray[0]:
        return outArray[0]
    if inValue >= inArray[-1]:
        return outArray[-1]

    # else get index between the setpoints
    idx = bisect.bisect(inArray, inValue)

    return outArray[idx] if returnLower else outArray[idx - 1]


def is_bit_set(tmp: any) -> bool:
    """
    Checks if a bit is set high or low

    :param tmp: Value to check
    :return: True if bit is set, False if not
    """
    return False if tmp == ZERO_CHAR else True


def kelvin_to_celsius(temp: float) -> float:
    """
    Convert Kelvin to Celsius

    :param temp: Temperature in Kelvin
    :return: Temperature in Celsius
    """
    return temp - 273.1


def bytearray_to_string(data: bytearray) -> str:
    """
    Convert a bytearray to a string

    :param data: Data to convert
    :return: Converted string
    """
    return "".join("\\x" + format(byte, "02x") for byte in data)


def open_serial_port(port: str, baud: int) -> serial.Serial:
    """
    Open a serial port

    :param port: Serial port
    :param baud: Baud rate
    :return: Opened serial port
    """
    ser = None
    tries = 3
    while tries > 0:
        try:
            ser = serial.Serial(port, baudrate=baud, timeout=0.1)
            tries = 0
        except serial.SerialException as e:
            logger.error(e)
            tries -= 1

    return ser


def read_serialport_data(
    ser: serial.Serial,
    command: bytearray,
    length_pos: int,
    length_check: int,
    length_fixed: Union[int, None] = None,
    length_size: str = "B",
) -> bytearray:
    """
    Read data from a serial port

    :param ser: Serial port
    :param command: Command to send
    :param length_pos: Position of the length byte
    :param length_check: Length of the checksum
    :param length_fixed: Fixed length of the data, if not set it will be read from the data
    :param length_size: Size of the length byte, can be "B", "H", "I" or "L"
    :return: Data read from the serial port
    """
    try:
        ser.flushOutput()
        ser.flushInput()
        ser.write(command)

        if length_size.upper() == "B":
            length_byte_size = 1
        elif length_size.upper() == "H":
            length_byte_size = 2
        elif length_size.upper() == "I" or length_size.upper() == "L":
            length_byte_size = 4

        count = 0
        toread = ser.inWaiting()

        while toread < (length_pos + length_byte_size):
            sleep(0.005)
            toread = ser.inWaiting()
            count += 1
            if count > 50:
                logger.error(">>> ERROR: No reply - returning")
                return False

        # logger.info('serial data toread ' + str(toread))
        res = ser.read(toread)
        if length_fixed is not None:
            length = length_fixed
        else:
            if len(res) < (length_pos + length_byte_size):
                logger.error(
                    ">>> ERROR: No reply - returning [len:" + str(len(res)) + "]"
                )
                return False
            length = unpack_from(">" + length_size, res, length_pos)[0]

        # logger.info('serial data length ' + str(length))

        count = 0
        data = bytearray(res)
        while len(data) <= length + length_check:
            res = ser.read(length + length_check)
            data.extend(res)
            # logger.info('serial data length ' + str(len(data)))
            sleep(0.005)
            count += 1
            if count > 150:
                logger.error(
                    ">>> ERROR: No reply - returning [len:"
                    + str(len(data))
                    + "/"
                    + str(length + length_check)
                    + "]"
                )
                return False

        return data

    except serial.SerialException as e:
        logger.error(e)
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
        return False


def read_serial_data(
    command: any,
    port: str,
    baud: int,
    length_pos: int,
    length_check: int,
    length_fixed: Union[int, None] = None,
    length_size: str = "B",
) -> bytearray:
    """
    Read data from a serial port

    :param command: Command to send
    :param port: Serial port
    :param baud: Baud rate
    :param length_pos: Position of the length byte
    :param length_check: Length of the checksum
    :param length_fixed: Fixed length of the data, if not set it will be read from the data
    :param length_size: Size of the length byte, can be "B", "H", "I" or "L"
    :return: Data read from the serial port
    """
    try:
        with serial.Serial(port, baudrate=baud, timeout=0.1) as ser:
            return read_serialport_data(
                ser, command, length_pos, length_check, length_fixed, length_size
            )

    except serial.SerialException as e:
        logger.error(e)
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


def validate_config_values() -> bool:
    """
    Validate the config values and log any issues.
    Has to be called in a function, otherwise the error messages are not instantly visible.

    :return: True if there are no errors else False
    """
    # loop through all errors and log them
    for error in errors_in_config:
        logger.error(error)

    # return True if there are no errors
    return len(errors_in_config) == 0


def publish_config_variables(dbusservice) -> None:
    """
    Publish the config variables to the dbus path "/Info/Config/"

    :param dbusservice: DBus service
    """
    for variable, value in locals_copy.items():
        if variable.startswith("__"):
            continue
        if (
            isinstance(value, float)
            or isinstance(value, int)
            or isinstance(value, str)
            or isinstance(value, List)
        ):
            dbusservice.add_path(f"/Info/Config/{variable}", value)


# Save the local variables to publish them wtih publish_config_variables() to the dbus
# only if PUBLISH_CONFIG_VALUES is set to True
if PUBLISH_CONFIG_VALUES:
    locals_copy = locals().copy()
