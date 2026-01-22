# -*- coding: utf-8 -*-
# Standard library imports
import bisect
import configparser
import logging
import sys
from pathlib import Path
from struct import Struct, unpack_from
from time import sleep
from typing import List, Any, Callable, Optional, Union

# Third-party imports
import serial
import time

# CONSTANTS
DRIVER_VERSION: str = "2.1.202601010dev"
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
try:
    config.read([default_config_file_path, custom_config_file_path])

    # Ensure the [DEFAULT] section exists and is uppercase
    if "DEFAULT" not in config:
        logger.error(f'The custom config file "{custom_config_file_path}" is missing the [DEFAULT] section.')
        logger.error("Make sure the first line of the file is exactly (case-sensitive): [DEFAULT]")
        sleep(60)
        sys.exit(1)

except configparser.MissingSectionHeaderError as error_message:
    logger.error(f'Error reading "{custom_config_file_path}"')
    logger.error("Make sure the first line is exactly: [DEFAULT]")
    logger.error(f"{error_message}\n")
    sleep(60)
    sys.exit(1)

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

# Check if there are any options in the custom config file that are not in the default config file
default_config = configparser.ConfigParser()
custom_config = configparser.ConfigParser()
# Ensure that option names are treated as case-sensitive
default_config.optionxform = str
custom_config.optionxform = str
# Read the default and custom config files
default_config.read(default_config_file_path)
custom_config.read(custom_config_file_path)

for section in custom_config.sections() + ["DEFAULT"]:
    if section not in default_config.sections() + ["DEFAULT"]:
        errors_in_config.append(f'Section "{section}" in config.ini is not valid.')
    else:
        for option in custom_config[section]:
            if option not in default_config[section]:
                errors_in_config.append(f'Option "{option}" in config.ini is not valid.')

# Free up memory
del default_config, custom_config, section

# Check if option variable was set and if yes, free it
if "option" in locals():
    del option


# --------- Helper Functions ---------
def get_bool_from_config(group: str, option: str) -> bool:
    """
    Get a boolean value from the config file.

    :param group: Group in the config file
    :param option: Option in the config file
    :return: Boolean value
    """
    return config[group].get(option, "False").lower() == "true"


def get_float_from_config(group: str, option: str, default_value: float = 0) -> float:
    """
    Get a float value from the config file.

    :param group: Group in the config file
    :param option: Option in the config file
    :return: Float value
    """
    value = config[group].get(option, default_value)
    if value == "":
        return default_value
    try:
        return float(value)
    except ValueError:
        errors_in_config.append(f"Invalid value '{value}' for option '{option}' in group '{group}'.")
        return default_value


def get_int_from_config(group: str, option: str, default_value: int = 0) -> int:
    """
    Get an integer value from the config file.

    :param group: Group in the config file
    :param option: Option in the config file
    :return: Integer value
    """
    value = config[group].get(option, default_value)
    if value == "":
        return default_value
    try:
        return int(value)
    except ValueError:
        errors_in_config.append(f"Invalid value '{value}' for option '{option}' in group '{group}'.")
        return default_value


def get_list_from_config(group: str, option: str, mapper: Callable[[Any], Any] = lambda v: v) -> List[Any]:
    """
    Get a string with comma-separated values from the config file and return a list of values.

    :param group: Group in the config file
    :param option: Option in the config file
    :param mapper: Function to map the values to the correct type
    :return: List of values
    """
    try:
        raw_list = config[group].get(option).split(",")
        return [mapper(item.strip()) for item in raw_list if item.strip()]
    except KeyError:
        logger.error(f"Missing config option '{option}' in group '{group}'")
        errors_in_config.append(f"Missing config option '{option}' in group '{group}'")
        return []
    except ValueError:
        errors_in_config.append(f"Invalid value '{mapper}' for option '{option}' in group '{group}'.")
        return []


def check_config_issue(condition: bool, message: str):
    """
    Check a condition and append a message to the errors_in_config list if the condition is True.

    :param condition: The condition to check
    :param message: The message to append if the condition is True
    """
    if condition:
        errors_in_config.append(f"{message}")


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
SOC_RESET_CELL_VOLTAGE: float = get_float_from_config("DEFAULT", "SOC_RESET_CELL_VOLTAGE")
SOC_RESET_AFTER_DAYS: Union[int, bool] = get_int_from_config("DEFAULT", "SOC_RESET_AFTER_DAYS") if config["DEFAULT"]["SOC_RESET_AFTER_DAYS"] != "" else False

# make some checks for most common misconfigurations
if SOC_RESET_AFTER_DAYS and SOC_RESET_CELL_VOLTAGE < MAX_CELL_VOLTAGE:
    check_config_issue(
        True,
        f"SOC_RESET_CELL_VOLTAGE ({SOC_RESET_CELL_VOLTAGE} V) is less than MAX_CELL_VOLTAGE ({MAX_CELL_VOLTAGE} V). "
        "To ensure that the driver still works correctly, SOC_RESET_CELL_VOLTAGE was set to MAX_CELL_VOLTAGE. Please check the configuration.",
    )
    SOC_RESET_CELL_VOLTAGE = MAX_CELL_VOLTAGE


# --------- SoC Calculation ---------
SOC_CALCULATION: bool = get_bool_from_config("DEFAULT", "SOC_CALCULATION")

# --------- Current correction --------
CURRENT_REPORTED_BY_BMS: list = get_list_from_config("DEFAULT", "CURRENT_REPORTED_BY_BMS", float)
CURRENT_MEASURED_BY_USER: list = get_list_from_config("DEFAULT", "CURRENT_MEASURED_BY_USER", float)

# check if lists are different
# this allows to calculate linear relationship between the two lists only if needed
CURRENT_CORRECTION: bool = CURRENT_REPORTED_BY_BMS != CURRENT_MEASURED_BY_USER


# --------- Bluetooth BMS ---------
BLUETOOTH_USE_POLLING = get_bool_from_config("DEFAULT", "BLUETOOTH_USE_POLLING")
BLUETOOTH_FORCE_RESET_BLE_STACK = get_bool_from_config("DEFAULT", "BLUETOOTH_FORCE_RESET_BLE_STACK")

# --------- Daisy Chain Configuration (Multiple BMS on one cable) ---------
BATTERY_ADDRESSES: list = get_list_from_config("DEFAULT", "BATTERY_ADDRESSES", str)

# --------- BMS Disconnect Behavior ---------
BLOCK_ON_DISCONNECT: bool = get_bool_from_config("DEFAULT", "BLOCK_ON_DISCONNECT")
BLOCK_ON_DISCONNECT_TIMEOUT_MINUTES: int = get_int_from_config("DEFAULT", "BLOCK_ON_DISCONNECT_TIMEOUT_MINUTES")
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


# --------- BMS Cable Alarm ---------
BMS_CABLE_ALARM: bool = get_bool_from_config("DEFAULT", "BMS_CABLE_ALARM")


# --------- External Sensor for Current and/or SoC ---------
EXTERNAL_SENSOR_DBUS_DEVICE: Union[str, None] = config["DEFAULT"]["EXTERNAL_SENSOR_DBUS_DEVICE"] or None
EXTERNAL_SENSOR_DBUS_PATH_CURRENT: Union[str, None] = config["DEFAULT"]["EXTERNAL_SENSOR_DBUS_PATH_CURRENT"] or None
EXTERNAL_SENSOR_DBUS_PATH_SOC: Union[str, None] = config["DEFAULT"]["EXTERNAL_SENSOR_DBUS_PATH_SOC"] or None


# Common configuration checks
check_config_issue(
    SOC_CALCULATION and EXTERNAL_SENSOR_DBUS_PATH_SOC is not None,
    "SOC_CALCULATION and EXTERNAL_SENSOR_DBUS_PATH_SOC are both enabled. This will lead to a conflict. Please disable one of them in the configuration.",
)


# --------- Charge mode ---------
CHARGE_MODE: int = get_int_from_config("DEFAULT", "CHARGE_MODE")
CVL_RECALCULATION_EVERY: int = get_int_from_config("DEFAULT", "CVL_RECALCULATION_EVERY")
CVL_RECALCULATION_ON_MAX_PERCENTAGE_CHANGE: int = get_int_from_config("DEFAULT", "CVL_RECALCULATION_ON_MAX_PERCENTAGE_CHANGE")


# --------- Charge Voltage Limitation (affecting CVL) ---------
CVCM_ENABLE: bool = get_bool_from_config("DEFAULT", "CVCM_ENABLE")
"""
Charge voltage control management

Limits max charging voltage (CVL). Switch from max to float voltage and back.
"""
SWITCH_TO_FLOAT_WAIT_FOR_SEC: int = get_int_from_config("DEFAULT", "SWITCH_TO_FLOAT_WAIT_FOR_SEC", 0)
SWITCH_TO_FLOAT_CELL_VOLTAGE_DIFF: float = get_float_from_config("DEFAULT", "SWITCH_TO_FLOAT_CELL_VOLTAGE_DIFF", 10)
SWITCH_TO_FLOAT_CELL_VOLTAGE_DEVIATION: float = get_float_from_config("DEFAULT", "SWITCH_TO_FLOAT_CELL_VOLTAGE_DEVIATION", 0)

SWITCH_TO_BULK_SOC_THRESHOLD: int = get_int_from_config("DEFAULT", "SWITCH_TO_BULK_SOC_THRESHOLD", 0)
SWITCH_TO_BULK_CELL_VOLTAGE_DIFF: float = get_float_from_config("DEFAULT", "SWITCH_TO_BULK_CELL_VOLTAGE_DIFF", 10)


# Common configuration checks
if SWITCH_TO_BULK_SOC_THRESHOLD <= 0 and SWITCH_TO_BULK_CELL_VOLTAGE_DIFF >= 0.101:
    logger.warning(
        "Your current configuration very likely prevents the switch from FLOAT to BULK."
        f"SWITCH_TO_BULK_SOC_THRESHOLD is set to {SWITCH_TO_BULK_SOC_THRESHOLD} and "
        f"SWITCH_TO_BULK_CELL_VOLTAGE_DIFF is set to {SWITCH_TO_BULK_CELL_VOLTAGE_DIFF}."
    )
    logger.warning("Please check the configuration and adjust the values accordingly.")


# --------- Cell Voltage Limitation (affecting CVL) ---------
CVL_CONTROLLER_MODE: int = get_int_from_config("DEFAULT", "CVL_CONTROLLER_MODE")
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
    SOC_RESET_AFTER_DAYS and CELL_VOLTAGES_WHILE_CHARGING[0] < SOC_RESET_CELL_VOLTAGE and MAX_CHARGE_CURRENT_CV[0] == 0,
    f"Maximum value of CELL_VOLTAGES_WHILE_CHARGING ({CELL_VOLTAGES_WHILE_CHARGING[0]} V) is lower than SOC_RESET_CELL_VOLTAGE ({SOC_RESET_CELL_VOLTAGE} V). "
    "SOC_RESET_CELL_VOLTAGE will never be reached this way and battery will not change to float. Please check the configuration.",
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

# --------- MOSFET Temperature Current Limitation (affecting CCL/DCL) ---------
CCCM_T_MOSFET_ENABLE: bool = get_bool_from_config("DEFAULT", "CCCM_T_MOSFET_ENABLE")
"""
Charge current control management referring to MOSFET temperature
"""
DCCM_T_MOSFET_ENABLE: bool = get_bool_from_config("DEFAULT", "DCCM_T_MOSFET_ENABLE")
"""
Discharge current control management referring to MOSFET temperature
"""
MOSFET_TEMPERATURES_WHILE_CHARGING: List[float] = get_list_from_config("DEFAULT", "MOSFET_TEMPERATURES_WHILE_CHARGING", float)
MAX_CHARGE_CURRENT_T_MOSFET: List[float] = get_list_from_config(
    "DEFAULT", "MAX_CHARGE_CURRENT_T_MOSFET_FRACTION", lambda v: MAX_BATTERY_CHARGE_CURRENT * float(v)
)

check_config_issue(
    MAX_BATTERY_CHARGE_CURRENT not in MAX_CHARGE_CURRENT_T_MOSFET,
    f"In MAX_CHARGE_CURRENT_T_MOSFET_FRACTION ({', '.join(map(str, get_list_from_config('DEFAULT', 'MAX_CHARGE_CURRENT_T_MOSFET_FRACTION', float)))}) "
    "there is no value set to 1. This means that the battery will never use the maximum charge current. Please check the configuration.",
)

MOSFET_TEMPERATURES_WHILE_DISCHARGING: List[float] = get_list_from_config("DEFAULT", "MOSFET_TEMPERATURES_WHILE_DISCHARGING", float)
MAX_DISCHARGE_CURRENT_T_MOSFET: List[float] = get_list_from_config(
    "DEFAULT", "MAX_DISCHARGE_CURRENT_T_MOSFET_FRACTION", lambda v: MAX_BATTERY_DISCHARGE_CURRENT * float(v)
)

check_config_issue(
    MAX_BATTERY_DISCHARGE_CURRENT not in MAX_DISCHARGE_CURRENT_T_MOSFET,
    f"In MAX_DISCHARGE_CURRENT_T_MOSFET_FRACTION ({', '.join(map(str, get_list_from_config('DEFAULT', 'MAX_DISCHARGE_CURRENT_T_MOSFET_FRACTION', float)))}) "
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
PUBLISH_BATTERY_DATA_AS_JSON: bool = get_bool_from_config("DEFAULT", "PUBLISH_BATTERY_DATA_AS_JSON")
BATTERY_CELL_DATA_FORMAT: int = get_int_from_config("DEFAULT", "BATTERY_CELL_DATA_FORMAT")
MIDPOINT_ENABLE: bool = get_bool_from_config("DEFAULT", "MIDPOINT_ENABLE")
TEMPERATURE_SOURCE_BATTERY: List[int] = get_list_from_config("DEFAULT", "TEMPERATURE_SOURCE_BATTERY", int)
TEMPERATURE_1_NAME: str = config["DEFAULT"]["TEMPERATURE_1_NAME"]
TEMPERATURE_2_NAME: str = config["DEFAULT"]["TEMPERATURE_2_NAME"]
TEMPERATURE_3_NAME: str = config["DEFAULT"]["TEMPERATURE_3_NAME"]
TEMPERATURE_4_NAME: str = config["DEFAULT"]["TEMPERATURE_4_NAME"]
TEMPERATURE_NAMES: dict = {
    1: config["DEFAULT"]["TEMPERATURE_1_NAME"],
    2: config["DEFAULT"]["TEMPERATURE_2_NAME"],
    3: config["DEFAULT"]["TEMPERATURE_3_NAME"],
    4: config["DEFAULT"]["TEMPERATURE_4_NAME"],
}
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

# -- LltJbd_Up16s settings
UP16S_REQUIRE_DIRECT_CONNECTION: bool = get_bool_from_config("DEFAULT", "UP16S_REQUIRE_DIRECT_CONNECTION")

# -- Daly settings
INVERT_CURRENT_MEASUREMENT: int = get_int_from_config("DEFAULT", "INVERT_CURRENT_MEASUREMENT")

# -- ESC GreenMeter and Lipro device settings
GREENMETER_ADDRESS: int = get_int_from_config("DEFAULT", "GREENMETER_ADDRESS")
LIPRO_START_ADDRESS: int = get_int_from_config("DEFAULT", "LIPRO_START_ADDRESS")
LIPRO_END_ADDRESS: int = get_int_from_config("DEFAULT", "LIPRO_END_ADDRESS")
LIPRO_CELL_COUNT: int = get_int_from_config("DEFAULT", "LIPRO_CELL_COUNT")

# -- UBMS settings
UBMS_CAN_MODULE_SERIES: int = get_int_from_config("DEFAULT", "UBMS_CAN_MODULE_SERIES")
UBMS_CAN_MODULE_PARALLEL: int = get_int_from_config("DEFAULT", "UBMS_CAN_MODULE_PARALLEL")


# --- MQTT battery instance settings
MQTT_TOPIC: list = get_list_from_config("DEFAULT", "MQTT_TOPIC", str)
MQTT_BROKER_ADDRESS: str = config["DEFAULT"]["MQTT_BROKER_ADDRESS"]
MQTT_BROKER_PORT: int = get_int_from_config("DEFAULT", "MQTT_BROKER_PORT")
MQTT_TLS_ENABLED: bool = get_bool_from_config("DEFAULT", "MQTT_TLS_ENABLED")
MQTT_TLS_PATH_TO_CA: str = config["DEFAULT"]["MQTT_TLS_PATH_TO_CA"]
MQTT_TLS_INSECURE: bool = get_bool_from_config("DEFAULT", "MQTT_TLS_INSECURE")
MQTT_USERNAME: str = config["DEFAULT"]["MQTT_USERNAME"]
MQTT_PASSWORD: str = config["DEFAULT"]["MQTT_PASSWORD"]


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


def kelvin_to_celsius(temperature: float) -> float:
    """
    Convert Kelvin to Celsius.

    :param temperature: Temperature in Kelvin
    :return: Temperature in Celsius
    """
    return temperature - 273.15


def bytearray_to_string(data: bytearray) -> str:
    """
    Convert a bytearray to a string.

    :param data: Data to convert
    :return: Converted string
    """
    return "".join(f"\\x{byte:02x}" for byte in data)


def get_connection_error_message(battery_online: bool, suffix: str = None) -> None:
    """
    This method is used to check if the connection to the BMS is successful.
    It returns True if the connection is successful, otherwise False.
    It also handles the error logging if the connection is lost.

    :parambattery_online: Boolean indicating if the battery is online
    :param suffix: Optional suffix to add to the error message
    :return: True if the connection is successful, otherwise False
    """
    if battery_online is None:
        logger.info("  |- No battery recognized")
        return

    if battery_online:
        logger.error(">>> No response from battery. Connection lost or battery not recognized. Check cabeling!" + (" " + suffix if suffix else ""))
        return


def generate_unique_identifier(port: str, address) -> str:
    """
    Generate a unique identifier for the battery based on the port and address.

    :param port: Serial port
    :param address: Battery address
    :return: Unique identifier
    """
    return str(port).replace("/dev/", "") + "__" + (bytearray_to_string(address).replace("\\", "0") if address is not None else "0x01")


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
    request: bytearray,
    timeout_seconds: float,
    extra_length: int,
    payload_length_pos: int,
    payload_length_size: str = "B",
    length_fixed: Optional[int] = None,
) -> Optional[bytearray]:
    """
    Serial port read helper that fixes some shortcomings of read_serialport_data_deprecated() and is more reliable.

    :param ser: Serial port
    :param request: Data to send
    :param timeout_seconds: Maximum time to wait for data
    :param extra_length: Length of everything else that's not counted in the payload length value contained at payload_length_pos. For example it's
      most likely the checksum and the header including the payload length field itself.
    :param payload_length_pos: Position of the payload length field in the packet
    :param payload_length_size: Size of the payload length field, e.g. "B", "H", "I", "L"
    :param length_fixed: Total fixed length of the data to read. If set, all other length arguments are ignored. If not set, length will be read from the data
    :return: Data read from the serial port or None on error
    """

    try:
        ser.reset_input_buffer()
        ser.write(request)

        length_struct = Struct(">" + payload_length_size)
        if length_fixed is None:
            bytes_needed = payload_length_pos + length_struct.size
            payload_length = None
        else:
            bytes_needed = length_fixed
            payload_length = length_fixed

        data = bytearray()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            chunk = ser.read(max(1, ser.in_waiting))
            if chunk:
                data.extend(chunk)

            # Parse length once we have enough bytes
            if payload_length is None and len(data) >= bytes_needed:
                payload_length = length_struct.unpack_from(data, payload_length_pos)[0]
                # Update bytes needed for the complete message
                bytes_needed = payload_length + extra_length

            # Check if we have the complete message
            if payload_length is not None and len(data) >= bytes_needed:
                return data

            # Sleep to prevent busy-waiting
            sleep(0.01)

        # Timeout occurred
        return None

    except Exception:
        logger.exception("read_serialport_data exception")
        return None


def read_serialport_data_deprecated(
    ser: serial.Serial,
    command: bytearray,
    length_pos: int,
    length_check: int,
    length_fixed: Union[int, None] = None,
    length_size: str = "B",
    battery_online: bool = True,
) -> bytearray:
    """
    Read data from a serial port. Deprecated, use read_serialport_data() instead.

    :param ser: Serial port
    :param command: Command to send
    :param length_pos: Position of the length byte
    :param length_check: Length of the checksum
    :param length_fixed: Fixed length of the data, if not set it will be read from the data
    :param length_size: Size of the length byte, can be "B", "H", "I" or "L"
    :param battery_online: Boolean indicating if the battery is online
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
                get_connection_error_message(battery_online)
                return False

        # logger.info('serial data toread ' + str(toread))
        res = ser.read(toread)
        if length_fixed is not None:
            length = length_fixed
        else:
            if len(res) < (length_pos + length_byte_size):
                get_connection_error_message(battery_online, "[len:" + str(len(res)) + "]")
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
                get_connection_error_message(battery_online, "[len:" + str(len(data)) + "/" + str(length + length_check) + "]")
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
    battery_online: bool = True,
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
    :param battery_online: Boolean indicating if the battery is online
    :return: Data read from the serial port
    """
    ser = None  # Initialize ser to None
    try:
        with serial.Serial(port, baudrate=baud, timeout=0.1) as ser:
            return read_serialport_data_deprecated(ser, command, length_pos, length_check, length_fixed, length_size, battery_online)

    except serial.SerialException as e:
        logger.error(e)
        if ser is not None:
            # close the serial port if it was opened
            ser.close()
            logger.error("Serial port closed")
        else:
            logger.error("Serial port could not be opened")

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


def safe_number_format(value: float, fmt: str = "{:.2f}", default=None) -> str:
    """
    Format a value safely, returning a default value if the value is None.

    :param value: Value to format
    :param fmt: Format string (default: "{:.2f}")
    :param default: Default value to return if value is None
    :return: Formatted value or default value
    """
    return fmt.format(value) if value is not None else default


def validate_config_values() -> bool:
    """
    Validate the config values and log any issues.
    Has to be called in a function, otherwise the error messages are not instantly visible.

    :return: True if there are no errors else False
    """
    # Add empty line for better readability
    if len(errors_in_config) > 0:
        logger.error("")
        logger.error("*** CONFIG ISSUES DETECTED ***")

    # loop through all errors and log them
    for error in errors_in_config:
        logger.error("- " + error)

    # return True if there are no errors
    if len(errors_in_config) == 0:
        return True
    else:
        logger.error("The driver may not behave as expected due to the above issues.")
        logger.error(">>> Please check the CHANGELOG.md for option changes and the config.default.ini for all available options!")
        logger.error("")
        return False


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


def get_venus_os_version() -> str:
    """
    Get the Venus OS version.

    :return: Venus OS version, e.g. v3.60
    """
    with open("/opt/victronenergy/version", "r") as f:
        return f.readline().strip()


def get_venus_os_image_type() -> str:
    """
    Get the Venus OS image type

    :return: Venus OS image type: normal or large
    """
    with open("/etc/venus/image-type", "r") as f:
        return f.readline().strip()


def get_venus_os_device_type() -> str:
    """
    Get the Venus OS device type.

    :return: Venus OS device type, e.g. Venus GX, Cerbo GX, etc.
    """
    with open("/sys/firmware/devicetree/base/model", "r") as f:
        return f.readline().strip()


# Save the local variables to publish them wtih publish_config_variables() to the dbus
# only if PUBLISH_CONFIG_VALUES is set to True
if PUBLISH_CONFIG_VALUES:
    locals_copy = locals().copy()
