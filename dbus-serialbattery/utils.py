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
DRIVER_VERSION: str = "2.0.20241217dev"
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
default_config_file_path = str(path.joinpath(PATH_CONFIG_DEFAULT).absolute())
custom_config_file_path = str(path.joinpath(PATH_CONFIG_USER).absolute())
config.read([default_config_file_path, custom_config_file_path])

# Map config logging levels to logging module levels
LOGGING_LEVELS = {
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}

# Set logging level from config file
logger.setLevel(LOGGING_LEVELS.get(config["DEFAULT"].get("LOGGING").upper()))

# List to store config errors
# This is needed else the errors are not instantly visible
errors_in_config = []


# --------- Helper Functions ---------
def get_bool_from_config(group: str, option: str) -> bool:
    """
    Get a boolean value from the config file.

    :param group: Group in the config file
    :param option: Option in the config file
    :return: Boolean value
    """
    return config[group].get(option, "False").lower() == "true"


def get_float_from_config(group: str, option: str) -> float:
    """
    Get a float value from the config file.

    :param group: Group in the config file
    :param option: Option in the config file
    :return: Float value
    """
    return float(config[group][option])


def get_int_from_config(group: str, option: str) -> int:
    """
    Get an integer value from the config file.

    :param group: Group in the config file
    :param option: Option in the config file
    :return: Integer value
    """
    return int(config[group][option])


def get_list_from_config(group: str, option: str, mapper: Callable[[Any], Any] = lambda v: v) -> List[Any]:
    """
    Get a string with comma-separated values from the config file and return a list of values.

    :param group: Group in the config file
    :param option: Option in the config file
    :param mapper: Function to map the values to the correct type
    :return: List of values
    """
    try:
        raw_list = config[group][option].split(",")
        return [mapper(item.strip()) for item in raw_list if item.strip()]
    except KeyError:
        logger.error(f"Missing config option '{option}' in group '{group}'")
        errors_in_config.append(f"Missing config option '{option}' in group '{group}'")
        return []


def check_config_issue(condition: bool, message: str):
    """
    Check a condition and append a message to the errors_in_config list if the condition is True.

    :param condition: The condition to check
    :param message: The message to append if the condition is True
    """
    if condition:
        errors_in_config.append(f"**CONFIG ISSUE**: {message}")


# SAVE CONFIG VALUES to constants
# --------- Battery Current Limits ---------
MAX_BATTERY_CHARGE_CURRENT: float = get_float_from_config("DEFAULT", "MAX_BATTERY_CHARGE_CURRENT")
"""
Defines the maximum charge current that the battery can accept.
"""
MAX_BATTERY_DISCHARGE_CURRENT: float = get_float_from_config("DEFAULT", "MAX_BATTERY_DISCHARGE_CURRENT")
"""
Defines the maximum discharge current that the battery can deliver.
"""

# --------- Cell Voltages ---------
MIN_CELL_VOLTAGE: float = get_float_from_config("DEFAULT", "MIN_CELL_VOLTAGE")
"""
Defines the minimum cell voltage that the battery can have.
Used for:
- Limit CVL range
- SoC calculation (if enabled)
"""
MAX_CELL_VOLTAGE: float = get_float_from_config("DEFAULT", "MAX_CELL_VOLTAGE")
"""
Defines the maximum cell voltage that the battery can have.
Used for:
- Limit CVL range
- SoC calculation (if enabled)
"""
FLOAT_CELL_VOLTAGE: float = get_float_from_config("DEFAULT", "FLOAT_CELL_VOLTAGE")
"""
Defines the cell voltage that the battery should have when it is fully charged.
"""

# make some checks for most common misconfigurations
if FLOAT_CELL_VOLTAGE > MAX_CELL_VOLTAGE:
    check_config_issue(
        True,
        f"FLOAT_CELL_VOLTAGE ({FLOAT_CELL_VOLTAGE} V) is greater than MAX_CELL_VOLTAGE ({MAX_CELL_VOLTAGE} V). "
        + "To ensure that the driver still works correctly, FLOAT_CELL_VOLTAGE was set to MAX_CELL_VOLTAGE. Please check the configuration.",
    )
    FLOAT_CELL_VOLTAGE = MAX_CELL_VOLTAGE
elif FLOAT_CELL_VOLTAGE < MIN_CELL_VOLTAGE:
    check_config_issue(
        True,
        "FLOAT_CELL_VOLTAGE ({FLOAT_CELL_VOLTAGE} V) is less than MIN_CELL_VOLTAGE ({MIN_CELL_VOLTAGE} V). "
        + "To ensure that the driver still works correctly, FLOAT_CELL_VOLTAGE was set to MIN_CELL_VOLTAGE. Please check the configuration.",
    )
    FLOAT_CELL_VOLTAGE = MIN_CELL_VOLTAGE


# --------- SoC Reset Voltage (must match BMS settings) ---------
SOC_RESET_VOLTAGE: float = get_float_from_config("DEFAULT", "SOC_RESET_VOLTAGE")
SOC_RESET_AFTER_DAYS: Union[int, bool] = get_int_from_config("DEFAULT", "SOC_RESET_AFTER_DAYS") if config["DEFAULT"]["SOC_RESET_AFTER_DAYS"] != "" else False

# make some checks for most common misconfigurations
if SOC_RESET_AFTER_DAYS and SOC_RESET_VOLTAGE < MAX_CELL_VOLTAGE:
    check_config_issue(
        True,
        f"SOC_RESET_VOLTAGE ({SOC_RESET_VOLTAGE} V) is less than MAX_CELL_VOLTAGE ({MAX_CELL_VOLTAGE} V). "
        "To ensure that the driver still works correctly, SOC_RESET_VOLTAGE was set to MAX_CELL_VOLTAGE. Please check the configuration.",
    )
    SOC_RESET_VOLTAGE = MAX_CELL_VOLTAGE


# --------- SoC Calculation ---------
SOC_CALCULATION: bool = get_bool_from_config("DEFAULT", "SOC_CALCULATION")

# --------- Current correction --------
CURRENT_REPORTED_BY_BMS: list = get_list_from_config("DEFAULT", "CURRENT_REPORTED_BY_BMS", float)
CURRENT_MEASURED_BY_USER: list = get_list_from_config("DEFAULT", "CURRENT_MEASURED_BY_USER", float)

# check if lists are different
# this allows to calculate linear relationship between the two lists only if needed
CURRENT_CORRECTION: bool = CURRENT_REPORTED_BY_BMS != CURRENT_MEASURED_BY_USER


# --------- Daisy Chain Configuration (Multiple BMS on one cable) ---------
BATTERY_ADDRESSES: list = get_list_from_config("DEFAULT", "BATTERY_ADDRESSES", str)

# --------- BMS Disconnect Behavior ---------
BLOCK_ON_DISCONNECT: bool = get_bool_from_config("DEFAULT", "BLOCK_ON_DISCONNECT")
BLOCK_ON_DISCONNECT_TIMEOUT_MINUTES: float = get_float_from_config("DEFAULT", "BLOCK_ON_DISCONNECT_TIMEOUT_MINUTES")
BLOCK_ON_DISCONNECT_VOLTAGE_MIN: float = get_float_from_config("DEFAULT", "BLOCK_ON_DISCONNECT_VOLTAGE_MIN")
BLOCK_ON_DISCONNECT_VOLTAGE_MAX: float = get_float_from_config("DEFAULT", "BLOCK_ON_DISCONNECT_VOLTAGE_MAX")

# make some checks for most common misconfigurations
if not BLOCK_ON_DISCONNECT:
    if BLOCK_ON_DISCONNECT_VOLTAGE_MIN < MIN_CELL_VOLTAGE:
        check_config_issue(
            True,
            f"BLOCK_ON_DISCONNECT_VOLTAGE_MIN ({BLOCK_ON_DISCONNECT_VOLTAGE_MIN} V) is less than MIN_CELL_VOLTAGE ({MIN_CELL_VOLTAGE} V). "
            "To ensure that the driver still works correctly, BLOCK_ON_DISCONNECT_VOLTAGE_MIN was set to MIN_CELL_VOLTAGE. Please check the configuration.",
        )
        BLOCK_ON_DISCONNECT_VOLTAGE_MIN = MIN_CELL_VOLTAGE

    if BLOCK_ON_DISCONNECT_VOLTAGE_MAX > MAX_CELL_VOLTAGE:
        check_config_issue(
            True,
            f"BLOCK_ON_DISCONNECT_VOLTAGE_MAX ({BLOCK_ON_DISCONNECT_VOLTAGE_MAX} V) is greater than MAX_CELL_VOLTAGE ({MAX_CELL_VOLTAGE} V). "
            "To ensure that the driver still works correctly, BLOCK_ON_DISCONNECT_VOLTAGE_MAX was set to MAX_CELL_VOLTAGE. Please check the configuration.",
        )
        BLOCK_ON_DISCONNECT_VOLTAGE_MAX = MAX_CELL_VOLTAGE

    if BLOCK_ON_DISCONNECT_VOLTAGE_MIN >= BLOCK_ON_DISCONNECT_VOLTAGE_MAX:
        check_config_issue(
            True,
            f"BLOCK_ON_DISCONNECT_VOLTAGE_MIN ({BLOCK_ON_DISCONNECT_VOLTAGE_MIN} V) "
            f"is greater or equal to BLOCK_ON_DISCONNECT_VOLTAGE_MAX ({BLOCK_ON_DISCONNECT_VOLTAGE_MAX} V). "
            "For safety reasons BLOCK_ON_DISCONNECT was set to True. Please check the configuration.",
        )
        BLOCK_ON_DISCONNECT = True


# --------- Charge mode ---------
LINEAR_LIMITATION_ENABLE: bool = get_bool_from_config("DEFAULT", "LINEAR_LIMITATION_ENABLE")
LINEAR_RECALCULATION_EVERY: int = get_int_from_config("DEFAULT", "LINEAR_RECALCULATION_EVERY")
LINEAR_RECALCULATION_ON_PERC_CHANGE: int = get_int_from_config("DEFAULT", "LINEAR_RECALCULATION_ON_PERC_CHANGE")


# --------- External Sensor for Current and/or SoC ---------
EXTERNAL_SENSOR_DBUS_DEVICE: Union[str, None] = config["DEFAULT"]["EXTERNAL_SENSOR_DBUS_DEVICE"] or None
EXTERNAL_SENSOR_DBUS_PATH_CURRENT: Union[str, None] = config["DEFAULT"]["EXTERNAL_SENSOR_DBUS_PATH_CURRENT"] or None
EXTERNAL_SENSOR_DBUS_PATH_SOC: Union[str, None] = config["DEFAULT"]["EXTERNAL_SENSOR_DBUS_PATH_SOC"] or None


# Common configuration checks
check_config_issue(
    SOC_CALCULATION and EXTERNAL_SENSOR_DBUS_PATH_SOC is not None,
    "SOC_CALCULATION and EXTERNAL_SENSOR_DBUS_PATH_SOC are both enabled. This will lead to a conflict. Please disable one of them in the configuration.",
)


# --------- Charge Voltage Limitation (affecting CVL) ---------
CVCM_ENABLE: bool = get_bool_from_config("DEFAULT", "CVCM_ENABLE")
"""
Charge voltage control management

Limits max charging voltage (CVL). Switch from max to float voltage and back.
"""
CELL_VOLTAGE_DIFF_KEEP_MAX_VOLTAGE_UNTIL: float = get_float_from_config("DEFAULT", "CELL_VOLTAGE_DIFF_KEEP_MAX_VOLTAGE_UNTIL")
CELL_VOLTAGE_DIFF_KEEP_MAX_VOLTAGE_TIME_RESTART: float = get_float_from_config("DEFAULT", "CELL_VOLTAGE_DIFF_KEEP_MAX_VOLTAGE_TIME_RESTART")
CELL_VOLTAGE_DIFF_TO_RESET_VOLTAGE_LIMIT: float = get_float_from_config("DEFAULT", "CELL_VOLTAGE_DIFF_TO_RESET_VOLTAGE_LIMIT")
MAX_VOLTAGE_TIME_SEC: int = get_int_from_config("DEFAULT", "MAX_VOLTAGE_TIME_SEC")
SOC_LEVEL_TO_RESET_VOLTAGE_LIMIT: int = get_int_from_config("DEFAULT", "SOC_LEVEL_TO_RESET_VOLTAGE_LIMIT")


# --------- Cell Voltage Limitation (affecting CVL) ---------
CVL_ICONTROLLER_MODE: bool = get_bool_from_config("DEFAULT", "CVL_ICONTROLLER_MODE")
CVL_ICONTROLLER_FACTOR: float = get_float_from_config("DEFAULT", "CVL_ICONTROLLER_FACTOR")


# --------- Cell Voltage Current Limitation (affecting CCL/DCL) ---------
CCCM_CV_ENABLE: bool = get_bool_from_config("DEFAULT", "CCCM_CV_ENABLE")
"""
Charge current control management referring to cell-voltage
"""
DCCM_CV_ENABLE: bool = get_bool_from_config("DEFAULT", "DCCM_CV_ENABLE")
"""
Discharge current control management referring to cell-voltage
"""
CELL_VOLTAGES_WHILE_CHARGING: List[float] = get_list_from_config("DEFAULT", "CELL_VOLTAGES_WHILE_CHARGING", float)
MAX_CHARGE_CURRENT_CV: List[float] = get_list_from_config("DEFAULT", "MAX_CHARGE_CURRENT_CV_FRACTION", lambda v: MAX_BATTERY_CHARGE_CURRENT * float(v))


# Common configuration checks
check_config_issue(
    CELL_VOLTAGES_WHILE_CHARGING[0] < MAX_CELL_VOLTAGE and MAX_CHARGE_CURRENT_CV[0] == 0,
    f"Maximum value of CELL_VOLTAGES_WHILE_CHARGING ({CELL_VOLTAGES_WHILE_CHARGING[0]} V) is lower than MAX_CELL_VOLTAGE ({MAX_CELL_VOLTAGE} V). "
    "MAX_CELL_VOLTAGE will never be reached this way and battery will not change to float. Please check the configuration.",
)

check_config_issue(
    SOC_RESET_AFTER_DAYS and CELL_VOLTAGES_WHILE_CHARGING[0] < SOC_RESET_VOLTAGE and MAX_CHARGE_CURRENT_CV[0] == 0,
    f"Maximum value of CELL_VOLTAGES_WHILE_CHARGING ({CELL_VOLTAGES_WHILE_CHARGING[0]} V) is lower than SOC_RESET_VOLTAGE ({SOC_RESET_VOLTAGE} V). "
    "SOC_RESET_VOLTAGE will never be reached this way and battery will not change to float. Please check the configuration.",
)

check_config_issue(
    MAX_BATTERY_CHARGE_CURRENT not in MAX_CHARGE_CURRENT_CV,
    f"In MAX_CHARGE_CURRENT_CV_FRACTION ({', '.join(map(str, get_list_from_config('DEFAULT', 'MAX_CHARGE_CURRENT_CV_FRACTION', float)))}) "
    "there is no value set to 1. This means that the battery will never use the maximum charge current. Please check the configuration.",
)

CELL_VOLTAGES_WHILE_DISCHARGING: List[float] = get_list_from_config("DEFAULT", "CELL_VOLTAGES_WHILE_DISCHARGING", float)
MAX_DISCHARGE_CURRENT_CV: List[float] = get_list_from_config("DEFAULT", "MAX_DISCHARGE_CURRENT_CV_FRACTION", lambda v: MAX_BATTERY_DISCHARGE_CURRENT * float(v))

check_config_issue(
    CELL_VOLTAGES_WHILE_DISCHARGING[0] > MIN_CELL_VOLTAGE and MAX_DISCHARGE_CURRENT_CV[0] == 0,
    f"Minimum value of CELL_VOLTAGES_WHILE_DISCHARGING ({CELL_VOLTAGES_WHILE_DISCHARGING[0]} V) is higher than MIN_CELL_VOLTAGE ({MIN_CELL_VOLTAGE} V). "
    "MIN_CELL_VOLTAGE will never be reached this way. Please check the configuration.",
)

check_config_issue(
    MAX_BATTERY_DISCHARGE_CURRENT not in MAX_DISCHARGE_CURRENT_CV,
    f"In MAX_DISCHARGE_CURRENT_CV_FRACTION ({', '.join(map(str, get_list_from_config('DEFAULT', 'MAX_DISCHARGE_CURRENT_CV_FRACTION', float)))}) "
    "there is no value set to 1. This means that the battery will never use the maximum discharge current. Please check the configuration.",
)

# --------- Temperature Limitation (affecting CCL/DCL) ---------
CCCM_T_ENABLE: bool = get_bool_from_config("DEFAULT", "CCCM_T_ENABLE")
"""
Charge current control management referring to temperature
"""
DCCM_T_ENABLE: bool = get_bool_from_config("DEFAULT", "DCCM_T_ENABLE")
"""
Discharge current control management referring to temperature
"""
TEMPERATURES_WHILE_CHARGING: List[float] = get_list_from_config("DEFAULT", "TEMPERATURES_WHILE_CHARGING", float)
MAX_CHARGE_CURRENT_T: List[float] = get_list_from_config("DEFAULT", "MAX_CHARGE_CURRENT_T_FRACTION", lambda v: MAX_BATTERY_CHARGE_CURRENT * float(v))

check_config_issue(
    MAX_BATTERY_CHARGE_CURRENT not in MAX_CHARGE_CURRENT_T,
    f"In MAX_CHARGE_CURRENT_T_FRACTION ({', '.join(map(str, get_list_from_config('DEFAULT', 'MAX_CHARGE_CURRENT_T_FRACTION', float)))}) "
    "there is no value set to 1. This means that the battery will never use the maximum charge current. Please check the configuration.",
)

TEMPERATURES_WHILE_DISCHARGING: List[float] = get_list_from_config("DEFAULT", "TEMPERATURES_WHILE_DISCHARGING", float)
MAX_DISCHARGE_CURRENT_T: List[float] = get_list_from_config("DEFAULT", "MAX_DISCHARGE_CURRENT_T_FRACTION", lambda v: MAX_BATTERY_DISCHARGE_CURRENT * float(v))

check_config_issue(
    MAX_BATTERY_DISCHARGE_CURRENT not in MAX_DISCHARGE_CURRENT_T,
    f"In MAX_DISCHARGE_CURRENT_T_FRACTION ({', '.join(map(str, get_list_from_config('DEFAULT', 'MAX_DISCHARGE_CURRENT_T_FRACTION', float)))}) "
    "there is no value set to 1. This means that the battery will never use the maximum discharge current. Please check the configuration.",
)

# --------- SoC Limitation (affecting CCL/DCL) ---------
CCCM_SOC_ENABLE: bool = get_bool_from_config("DEFAULT", "CCCM_SOC_ENABLE")
"""
Charge current control management referring to SoC
"""
DCCM_SOC_ENABLE: bool = get_bool_from_config("DEFAULT", "DCCM_SOC_ENABLE")
"""
Discharge current control management referring to SoC
"""
SOC_WHILE_CHARGING: List[float] = get_list_from_config("DEFAULT", "SOC_WHILE_CHARGING", float)
MAX_CHARGE_CURRENT_SOC: List[float] = get_list_from_config("DEFAULT", "MAX_CHARGE_CURRENT_SOC_FRACTION", lambda v: MAX_BATTERY_CHARGE_CURRENT * float(v))

check_config_issue(
    MAX_BATTERY_CHARGE_CURRENT not in MAX_CHARGE_CURRENT_SOC,
    f"In MAX_CHARGE_CURRENT_SOC_FRACTION ({', '.join(map(str, get_list_from_config('DEFAULT', 'MAX_CHARGE_CURRENT_SOC_FRACTION', float)))}) "
    "there is no value set to 1. This means that the battery will never use the maximum charge current. Please check the configuration.",
)

SOC_WHILE_DISCHARGING: List[float] = get_list_from_config("DEFAULT", "SOC_WHILE_DISCHARGING", float)
MAX_DISCHARGE_CURRENT_SOC: List[float] = get_list_from_config(
    "DEFAULT", "MAX_DISCHARGE_CURRENT_SOC_FRACTION", lambda v: MAX_BATTERY_DISCHARGE_CURRENT * float(v)
)

check_config_issue(
    MAX_BATTERY_DISCHARGE_CURRENT not in MAX_DISCHARGE_CURRENT_SOC,
    f"In MAX_DISCHARGE_CURRENT_SOC_FRACTION ({', '.join(map(str, get_list_from_config('DEFAULT', 'MAX_DISCHARGE_CURRENT_SOC_FRACTION', float)))}) "
    "there is no value set to 1. This means that the battery will never use the maximum discharge current. Please check the configuration.",
)


# --------- CCL/DCL Recovery Threshold ---------
CHARGE_CURRENT_RECOVERY_THRESHOLD_PERCENT: float = get_float_from_config("DEFAULT", "CHARGE_CURRENT_RECOVERY_THRESHOLD_PERCENT")
"""
Defines the percentage of the maximum charge current that the battery has to reach to recover from a limitation.
"""
DISCHARGE_CURRENT_RECOVERY_THRESHOLD_PERCENT: float = get_float_from_config("DEFAULT", "DISCHARGE_CURRENT_RECOVERY_THRESHOLD_PERCENT")
"""
Defines the percentage of the maximum discharge current that the battery has to reach to recover from a limitation.
"""


# --------- Time-To-Go ---------
TIME_TO_GO_ENABLE: bool = get_bool_from_config("DEFAULT", "TIME_TO_GO_ENABLE")

# --------- Time-To-Soc ---------
TIME_TO_SOC_POINTS: List[int] = get_list_from_config("DEFAULT", "TIME_TO_SOC_POINTS", int)
TIME_TO_SOC_VALUE_TYPE: int = get_int_from_config("DEFAULT", "TIME_TO_SOC_VALUE_TYPE")
TIME_TO_SOC_RECALCULATE_EVERY: int = max(get_int_from_config("DEFAULT", "TIME_TO_SOC_RECALCULATE_EVERY"), 5)
TIME_TO_SOC_INC_FROM: bool = get_bool_from_config("DEFAULT", "TIME_TO_SOC_INC_FROM")

# --------- History ---------
HISTORY_ENABLE: bool = get_bool_from_config("DEFAULT", "HISTORY_ENABLE")

# --------- Additional settings ---------
BMS_TYPE: List[str] = get_list_from_config("DEFAULT", "BMS_TYPE", str)
EXCLUDED_DEVICES: List[str] = get_list_from_config("DEFAULT", "EXCLUDED_DEVICES", str)
POLL_INTERVAL: Union[float, None] = float(config["DEFAULT"]["POLL_INTERVAL"]) * 1000 if config["DEFAULT"]["POLL_INTERVAL"] else None
"""
Poll interval in milliseconds
"""
PUBLISH_CONFIG_VALUES: bool = get_bool_from_config("DEFAULT", "PUBLISH_CONFIG_VALUES")
BATTERY_CELL_DATA_FORMAT: int = get_int_from_config("DEFAULT", "BATTERY_CELL_DATA_FORMAT")
MIDPOINT_ENABLE: bool = get_bool_from_config("DEFAULT", "MIDPOINT_ENABLE")
TEMP_BATTERY: int = get_int_from_config("DEFAULT", "TEMP_BATTERY")
TEMP_1_NAME: str = config["DEFAULT"]["TEMP_1_NAME"]
TEMP_2_NAME: str = config["DEFAULT"]["TEMP_2_NAME"]
TEMP_3_NAME: str = config["DEFAULT"]["TEMP_3_NAME"]
TEMP_4_NAME: str = config["DEFAULT"]["TEMP_4_NAME"]
GUI_PARAMETERS_SHOW_ADDITIONAL_INFO: bool = get_bool_from_config("DEFAULT", "GUI_PARAMETERS_SHOW_ADDITIONAL_INFO")
TELEMETRY: bool = get_bool_from_config("DEFAULT", "TELEMETRY")


# --------- Voltage drop ---------
VOLTAGE_DROP: float = get_float_from_config("DEFAULT", "VOLTAGE_DROP")

# --------- BMS specific settings ---------
USE_PORT_AS_UNIQUE_ID: bool = get_bool_from_config("DEFAULT", "USE_PORT_AS_UNIQUE_ID")
BATTERY_CAPACITY: float = get_float_from_config("DEFAULT", "BATTERY_CAPACITY")
AUTO_RESET_SOC: bool = get_bool_from_config("DEFAULT", "AUTO_RESET_SOC")
USE_BMS_DVCC_VALUES: bool = get_bool_from_config("DEFAULT", "USE_BMS_DVCC_VALUES")

# -- LltJbd settings
SOC_LOW_WARNING: float = get_float_from_config("DEFAULT", "SOC_LOW_WARNING")
SOC_LOW_ALARM: float = get_float_from_config("DEFAULT", "SOC_LOW_ALARM")

# -- Daly settings
INVERT_CURRENT_MEASUREMENT: int = get_int_from_config("DEFAULT", "INVERT_CURRENT_MEASUREMENT")

# -- ESC GreenMeter and Lipro device settings
GREENMETER_ADDRESS: int = get_int_from_config("DEFAULT", "GREENMETER_ADDRESS")
LIPRO_START_ADDRESS: int = get_int_from_config("DEFAULT", "LIPRO_START_ADDRESS")
LIPRO_END_ADDRESS: int = get_int_from_config("DEFAULT", "LIPRO_END_ADDRESS")
LIPRO_CELL_COUNT: int = get_int_from_config("DEFAULT", "LIPRO_CELL_COUNT")


# FUNCTIONS
def constrain(val: float, min_val: float, max_val: float) -> float:
    """
    Constrain a value between a minimum and maximum value.

    :param val: Value to constrain
    :param min_val: Minimum value
    :param max_val: Maximum value
    :return: Constrained value
    """
    if min_val > max_val:
        min_val, max_val = max_val, min_val
    return min(max_val, max(min_val, val))


def map_range(in_value: float, in_min: float, in_max: float, out_min: float, out_max: float) -> float:
    """
    Map a value from one range to another.

    :param in_value: Input value
    :param in_min: Minimum value of the input range
    :param in_max: Maximum value of the input range
    :param out_min: Minimum value of the output range
    :param out_max: Maximum value of the output range
    :return: Mapped value
    """
    return out_min + (((in_value - in_min) / (in_max - in_min)) * (out_max - out_min))


def map_range_constrain(in_value: float, in_min: float, in_max: float, out_min: float, out_max: float) -> float:
    """
    Map a value from one range to another and constrain it between the output range.

    :param in_value: Input value
    :param in_min: Minimum value of the input range
    :param in_max: Maximum value of the input range
    :param out_min: Minimum value of the output range
    :param out_max: Maximum value of the output range
    :return: Mapped and constrained value
    """
    return constrain(map_range(in_value, in_min, in_max, out_min, out_max), out_min, out_max)


def calc_linear_relationship(in_value: float, in_array: List[float], out_array: List[float]) -> float:
    """
    Calculate a linear relationship between two arrays.

    :param in_value: Input value
    :param in_array: Input array
    :param out_array: Output array
    :return: Calculated value
    """
    # Change compare-direction in array
    if in_array[0] > in_array[-1]:
        return calc_linear_relationship(in_value, in_array[::-1], out_array[::-1])

    # Handle out of bounds
    if in_value <= in_array[0]:
        return out_array[0]
    if in_value >= in_array[-1]:
        return out_array[-1]

    # Calculate linear current between the setpoints
    idx = bisect.bisect(in_array, in_value)
    upper_in = in_array[idx - 1]
    upper_out = out_array[idx - 1]
    lower_in = in_array[idx]
    lower_out = out_array[idx]
    return map_range_constrain(in_value, lower_in, upper_in, lower_out, upper_out)


def calc_step_relationship(in_value: float, in_array: List[float], out_array: List[float], return_lower: bool) -> float:
    """
    Calculate a step relationship between two arrays.

    :param in_value: Input value
    :param in_array: Input array
    :param out_array: Output array
    :param return_lower: Return lower value if True, else return higher value
    :return: Calculated value
    """
    # Change compare-direction in array
    if in_array[0] > in_array[-1]:
        return calc_step_relationship(in_value, in_array[::-1], out_array[::-1], return_lower)

    # Handle out of bounds
    if in_value <= in_array[0]:
        return out_array[0]
    if in_value >= in_array[-1]:
        return out_array[-1]

    # Get index between the setpoints
    idx = bisect.bisect(in_array, in_value)
    return out_array[idx] if return_lower else out_array[idx - 1]


def is_bit_set(value: Any) -> bool:
    """
    Check if a bit is set high or low.

    :param value: Value to check
    :return: True if bit is set, False if not
    """
    return value != ZERO_CHAR


def kelvin_to_celsius(temp: float) -> float:
    """
    Convert Kelvin to Celsius.

    :param temp: Temperature in Kelvin
    :return: Temperature in Celsius
    """
    return temp - 273.15


def bytearray_to_string(data: bytearray) -> str:
    """
    Convert a bytearray to a string.

    :param data: Data to convert
    :return: Converted string
    """
    return "".join(f"\\x{byte:02x}" for byte in data)


def open_serial_port(port: str, baud: int) -> Union[serial.Serial, None]:
    """
    Open a serial port.

    :param port: Serial port
    :param baud: Baud rate
    :return: Opened serial port or None if failed
    """
    tries = 3
    while tries > 0:
        try:
            return serial.Serial(port, baudrate=baud, timeout=0.1)
        except serial.SerialException as e:
            logger.error(e)
            tries -= 1
    return None


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
                logger.error(">>> ERROR: No reply - returning [len:" + str(len(res)) + "]")
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
                logger.error(">>> ERROR: No reply - returning [len:" + str(len(data)) + "/" + str(length + length_check) + "]")
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
        logger.error(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
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
            return read_serialport_data(ser, command, length_pos, length_check, length_fixed, length_size)

    except serial.SerialException as e:
        logger.error(e)
        # close the serial port
        ser.close()
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
        if isinstance(value, float) or isinstance(value, int) or isinstance(value, str) or isinstance(value, List):
            dbusservice.add_path(f"/Info/Config/{variable}", value)


# Save the local variables to publish them wtih publish_config_variables() to the dbus
# only if PUBLISH_CONFIG_VALUES is set to True
if PUBLISH_CONFIG_VALUES:
    locals_copy = locals().copy()
