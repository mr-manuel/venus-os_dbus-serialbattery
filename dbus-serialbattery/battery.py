# -*- coding: utf-8 -*-
from typing import Union, Tuple, List, Callable

from utils import logger
import utils
import logging
import math
from datetime import datetime
from time import time
from abc import ABC, abstractmethod
import sys


class Protection(object):
    """
    This class holds warning and alarm states for different types of checks.
    The alarm name in the GUI is the same as the variable name.

    They are of type integer

    2 = alarm
    1 = warning
    0 = ok, everything is fine
    """

    ALARM = 2
    WARNING = 1
    OK = 0

    def __init__(self):
        # current values
        self.high_voltage: int = None
        self.high_cell_voltage: int = None
        self.low_voltage: int = None
        self.low_cell_voltage: int = None
        self.low_soc: int = None
        self.high_charge_current: int = None
        self.high_discharge_current: int = None
        self.cell_imbalance: int = None
        self.internal_failure: int = None
        self.high_charge_temperature: int = None
        self.low_charge_temperature: int = None
        self.high_temperature: int = None
        self.low_temperature: int = None
        self.high_internal_temperature: int = None
        self.fuse_blown: int = None

        # previous values to check if the value has changed
        self.previous_high_voltage: int = None
        self.previous_high_cell_voltage: int = None
        self.previous_low_voltage: int = None
        self.previous_low_cell_voltage: int = None
        self.previous_low_soc: int = None
        self.previous_high_charge_current: int = None
        self.previous_high_discharge_current: int = None
        self.previous_cell_imbalance: int = None
        self.previous_internal_failure: int = None
        self.previous_high_charge_temperature: int = None
        self.previous_low_charge_temperature: int = None
        self.previous_high_temperature: int = None
        self.previous_low_temperature: int = None
        self.previous_high_internal_temperature: int = None
        self.previous_fuse_blown: int = None

    def set_previous(self) -> None:
        """
        Set the previous values to the current values.

        :return: None
        """
        self.previous_high_voltage = self.high_voltage
        self.previous_high_cell_voltage = self.high_cell_voltage
        self.previous_low_voltage = self.low_voltage
        self.previous_low_cell_voltage = self.low_cell_voltage
        self.previous_low_soc = self.low_soc
        self.previous_high_charge_current = self.high_charge_current
        self.previous_high_discharge_current = self.high_discharge_current
        self.previous_cell_imbalance = self.cell_imbalance
        self.previous_internal_failure = self.internal_failure
        self.previous_high_charge_temperature = self.high_charge_temperature
        self.previous_low_charge_temperature = self.low_charge_temperature
        self.previous_high_temperature = self.high_temperature
        self.previous_low_temperature = self.low_temperature
        self.previous_high_internal_temperature = self.high_internal_temperature
        self.previous_fuse_blown = self.fuse_blown


class History:
    """
    This class holds the history data of the battery.
    """

    def __init__(self):
        self.exclude_values_to_calculate: list = []
        """
        List of values to exclude from calculation, because they are fetched from the BMS.
        """

        self.clear: int = 0
        """
        Clear the history values, if set to 1. Set to 0 after clearing.

        You can set it manually via `dbus-spy --history` to:
        - 1 to clear all the history values (default)
        - 2 to clear only the capacity values
        - 3 to clear only the voltage values
        - 4 to clear only the time values
        - 5 to clear only the alarm values
        - 6 to clear only the temperature values
        - 7 to clear only the energy values
        """

        # Discharge information in Ah

        self.deepest_discharge: float = None
        """
        Deepest discharge in Ampere hours (lifetime).
        Overwritten each time the battery discharges deeper.
        **Should be negative.**
        """

        self.last_discharge: float = None
        """
        Last discharge in Ampere hours until the battery was charged again.
        **Should be negative.**
        """

        self.average_discharge: float = None
        """
        Average discharge in Ampere hours.
        Cumulative Ah drawn divided by total cycles.
        **Should be negative.**
        """

        self.total_ah_drawn: float = None
        """
        Total Ah drawn (lifetime).
        Cumulative Amp hours drawn from the battery.
        **Should be negative.**
        """

        # Charge

        self.charge_cycles: int = None
        """
        Number of charge cycles (lifetime).
        Total Amp hours drawn from the battery divided by the capacity.
        """

        self.timestamp_last_full_charge: int = None
        """
        Timestamp of full charge.
        """

        self.full_discharges: int = None
        """
        Number of full discharges (lifetime).
        Counted when state of charge reaches 0%.
        """

        # Battery voltage

        self.minimum_voltage: float = None
        """
        Minimum voltage in Volts (lifetime).
        """

        self.maximum_voltage: float = None
        """
        Maximum voltage in Volts (lifetime).
        """

        self.minimum_cell_voltage: float = None
        """
        Minimum cell voltage in Volts (lifetime).
        """

        self.maximum_cell_voltage: float = None
        """
        Maximum cell voltage in Volts (lifetime).
        """

        # Voltage alarms

        self.low_voltage_alarms: int = None
        """
        Number of low voltage alarms (lifetime).
        """

        self.high_voltage_alarms: int = None
        """
        Number of high voltage alarms (lifetime).
        """

        # Battery temperature

        self.minimum_temperature: float = None
        """
        Minimum temperature in Celsius (lifetime).
        """

        self.maximum_temperature: float = None
        """
        Maximum temperature in Celsius (lifetime).
        """

        # Energy in kWh

        self.discharged_energy: int = None
        """
        Total discharged energy in Kilowatt-hour (lifetime).
        """

        self.charged_energy: int = None
        """
        Total charged energy in Kilowatt-hour.
        """

    def reset_values(self, attributes: list = []) -> None:
        """
        Reset all calculated values that are not excluded.

        :param attributes: list of attributes to reset, if empty all attributes are reset
        :return: None
        """
        attributes = (
            [
                "deepest_discharge",
                "last_discharge",
                "average_discharge",
                "total_ah_drawn",
                "charge_cycles",
                "timestamp_last_full_charge",
                "full_discharges",
                "minimum_voltage",
                "maximum_voltage",
                "minimum_cell_voltage",
                "maximum_cell_voltage",
                "low_voltage_alarms",
                "high_voltage_alarms",
                "minimum_temperature",
                "maximum_temperature",
                "discharged_energy",
                "charged_energy",
            ]
            if not attributes
            else attributes
        )

        for attribute in attributes:
            if attribute not in self.exclude_values_to_calculate:
                setattr(self, attribute, None)


class Cell:
    """
    This class holds information about a single cell

    :param voltage: float = the voltage of the cell in Volts
    :param balance: bool = the balance status of the cell
    """

    voltage: float = None
    """
    The voltage of a specific cell in Volts
    """

    balance: bool = None
    """
    The balance status of a specific cell
    """

    def __init__(self, balance: bool = None):
        self.balance = balance


class Battery(ABC):
    """
    This Class is the abstract baseclass for all batteries. For each BMS this class needs to be extended
    and the abstract methods need to be implemented. The main program in dbus-serialbattery.py will then
    use the individual implementations as type Battery and work with it.
    """

    def __init__(self, port: str, baud: int, address: str):
        self.port: str = port
        self.baud_rate: int = baud
        self.address: str = address
        self.can_transport_interface: object = None
        self.role: str = "battery"
        self.type: str = "Generic"
        self.poll_interval: int = 1000
        self.dbus_external_objects: dict = None
        self.online: bool = True
        self.connection_info: str = "Initializing..."
        self.hardware_version: str = None
        self.cell_count: int = None
        self.start_time: int = int(time())
        """
        Timestamp of when the battery was initialized
        """
        # max battery charge/discharge current
        self.max_battery_charge_current: float = utils.MAX_BATTERY_CHARGE_CURRENT
        self.max_battery_discharge_current: float = utils.MAX_BATTERY_DISCHARGE_CURRENT
        self.has_settings: bool = False

        # this values should only be initialized once,
        # else the BMS turns off the inverter on disconnect
        self.soc_calc_capacity_remain: float = None
        self.soc_calc_capacity_remain_last_time: float = None
        self.soc_calc_reset_start_time: int = None
        self.soc_calc: float = None  # save soc_calc to preserve on restart
        self.soc: float = None
        self.charge_fet: bool = None
        self.discharge_fet: bool = None
        self.balance_fet: bool = None
        self.block_because_disconnect: bool = False
        self.control_charge_current: int = None
        self.control_discharge_current: int = None
        self.control_allow_charge: bool = None
        self.control_allow_discharge: bool = None

        self.current_avg: float = None
        self.current_avg_lst: list = []
        self.previous_current_avg: float = None
        self.current_external: float = None
        self.capacity_remain: float = None
        self.capacity: float = None
        self.production = None
        self.protection = Protection()
        self.history = History()
        self.version = None
        self.time_to_soc_update: int = 0
        self.temperature_1: float = None
        self.temperature_2: float = None
        self.temperature_3: float = None
        self.temperature_4: float = None
        self.temperature_mos: float = None
        self.cells: List[Cell] = []
        self.control_voltage: float = None
        self.soc_reset_requested: bool = False
        self.soc_reset_last_reached: int = 0  # save state to preserve on restart
        self.soc_reset_battery_voltage: int = None
        self.max_battery_voltage: float = None
        self.min_battery_voltage: float = None
        self.allow_max_voltage: bool = True  # save state to preserve on restart
        self.max_voltage_start_time: int = None  # save state to preserve on restart
        self.transition_start_time: int = None
        self.charge_mode: str = None
        self.charge_mode_debug: str = ""
        self.charge_mode_debug_float: str = ""
        self.charge_mode_debug_bulk: str = ""
        self.charge_limitation: str = None
        self.discharge_limitation: str = None
        self.linear_cvl_last_set: int = 0
        self.linear_ccl_last_set: int = 0
        self.linear_dcl_last_set: int = 0

        # Needed for history calculation
        self.full_discharge_active: bool = False
        """
        True if the battery discharged to 0%. Reset to False after reaching at least 15% again.
        """

        # Calculation of charge
        self.current_calc_last_time: int = None
        self.charge_charged: float = 0
        self.charge_discharged: float = 0
        self.charge_discharged_last: float = 0

        # Calculation of energy
        self.power_calc_last_time: int = None
        self.energy_charged: float = 0
        self.energy_discharged: float = 0

        # list of available callbacks, in order to display the buttons in the GUI
        self.available_callbacks: List[str] = []

        # display errors in the GUI
        # https://github.com/victronenergy/veutil/blob/master/inc/veutil/ve_regs_payload.h
        # https://github.com/victronenergy/veutil/blob/master/src/qt/bms_error.cpp
        self.state: int = 0
        """
        State to show in the GUI.
        Can block charge/discharge.
        """

        self.error_code: Union[int, None] = None
        """
        Error code to show in the GUI.
        Does not block charge/discharge.
        """

        self.error_code_last_reset_check: int = 0
        """
        Timestamp when it was last checked, if the error could be reset.
        """

        self.error_timestamps: list = []
        """
        List of timestamps when an error occurred.
        """

        self.custom_field: str = None
        """
        Custom field that the user can define in the BMS settings via the BMS app.
        """

        self.init_values()

    def init_values(self) -> None:
        """
        Used to initialize and reset values, if battery unexpectly disconnects.

        :return: None
        """
        self.voltage: float = None
        self.current: float = 0
        self.current_calc: float = 0
        self.current_corrected: float = 0
        self.power_calc: float = 0
        self.driver_start_time: int = int(time())

    @abstractmethod
    def test_connection(self) -> bool:
        """
        This abstract method needs to be implemented for each BMS. Each driver has to override this function
        to test, if a connection to the BMS can be made.

        :return: True if the connection was successful else False
        """
        return False

    def unique_identifier(self) -> str:
        """
        Used to identify a BMS when multiple BMS are connected and the port changes for whatever reason.

        If not provided by the BMS/driver then the hardware version and capacity is used as fallback.
        By slightly changing the capacity of each battery, this can make every battery unique.
        On +/- 5 Ah you can identify 11 different batteries.

        For some BMS it's not possible to change the capacity or other values. In this case the port has
        to be used as `unique_identifier`. Custom values for this battery like the custom name, will be
        swapped or lost, if the port changes.
        See https://github.com/Louisvdw/dbus-serialbattery/issues/1035

        :return: the unique identifier
        """
        if utils.USE_PORT_AS_UNIQUE_ID:
            return self.port + ("__" + utils.bytearray_to_string(self.address).replace("\\", "0") if self.address is not None else "")
        else:
            string = "".join(filter(str.isalnum, str(self.hardware_version))) + "_" if self.hardware_version is not None and self.hardware_version != "" else ""
            string += str(self.capacity) + "Ah"
            return string

    def connection_name(self) -> str:
        """
        Shown in the GUI under `Device -> Connection`

        :return: the connection name
        """
        return "Serial " + self.port + ("__" + utils.bytearray_to_string(self.address).replace("\\", "0") if self.address is not None else "")

    def custom_name(self) -> str:
        """
        Shown in the GUI under `Device -> Name`
        Overwritten, if the user set a custom name via GUI

        :return: the connection name
        """
        return "SerialBattery(" + self.type + ")"

    def product_name(self) -> str:
        """
        Shown in the GUI under `Device -> Product`

        :return: the connection name
        """
        return "SerialBattery(" + self.type + ")"

    def use_callback(self, callback: Callable) -> bool:
        """
        Each driver may override this function to indicate whether it is able to provide value
        updates on its own.

        :return:
            False when the battery cannot provide updates by itself, then it will be polled
            every `poll_interval` milliseconds for new values

            True if callable should be used for updates as they arrive from the battery
        """
        return False

    def set_can_transport_interface(self, can_transport_interface: object) -> None:
        """
        Set the access object for the can interface.

        :param can_transport_interface: the can_transport_interface object
        :return: None
        """
        self.can_transport_interface: object = can_transport_interface

    @abstractmethod
    def get_settings(self) -> bool:
        """
        Each driver must override this function to read the battery settings.
        It's called only once after a successful connection by `DbusHelper.setup_vedbus()`.

        See `battery_template.py` for an example.

        :return: False when fail, True if successful
        """
        return False

    @abstractmethod
    def refresh_data(self) -> bool:
        """
        Each driver must override this function to read battery data and populate this class.
        It's called each poll inverval just before the data is published to the vedbus.

        :return: False when fail, True if successful
        """
        return False

    def to_temperature(self, sensor: int, value: float) -> None:
        """
        Keep the temp value between -20 and 100 to handle sensor issues or no data.
        The BMS should already have protected the battery before those limits have been reached.

        :param sensor: temperature sensor number
        :param value: the sensor value
        :return: None
        """
        if sensor == 0:
            self.temperature_mos = round(min(max(value, -20), 100), 1)
        if sensor == 1:
            self.temperature_1 = round(min(max(value, -20), 100), 1)
        if sensor == 2:
            self.temperature_2 = round(min(max(value, -20), 100), 1)
        if sensor == 3:
            self.temperature_3 = round(min(max(value, -20), 100), 1)
        if sensor == 4:
            self.temperature_4 = round(min(max(value, -20), 100), 1)

    def manage_charge_voltage(self) -> None:
        """
        Manages the charge voltage by setting `self.control_voltage`.

        :return: None
        """
        # set min and max battery voltage if cell count is known
        if self.cell_count is not None:
            # set min battery voltage once
            if self.min_battery_voltage is None:
                self.min_battery_voltage = round(utils.MIN_CELL_VOLTAGE * self.cell_count, 2)

            # set max battery voltage once
            if self.max_battery_voltage is None:
                self.max_battery_voltage = round(utils.MAX_CELL_VOLTAGE * self.cell_count, 2)
        else:
            logger.debug("Cell count is not known yet. Can't set min and max battery voltage.")

        # enable soc reset voltage management only if needed
        if utils.SOC_RESET_AFTER_DAYS is not False:
            self.soc_reset_voltage_management()

        # apply dynamic charging voltage
        if utils.CVCM_ENABLE:
            # apply linear charging voltage
            if utils.LINEAR_LIMITATION_ENABLE:
                self.manage_charge_voltage_linear()
            # apply step charging voltage
            else:
                self.manage_charge_voltage_step()
        # apply fixed charging voltage
        else:
            self.control_voltage = round(self.max_battery_voltage, 2)
            self.charge_mode = "Keep always max voltage"

    def soc_calculation(self) -> float:
        """
        Calculates the SoC based on the coulomb counting method.

        :return: The calculated state of charge
        """
        current_time = time()

        SOC_RESET_TIME = 60

        if self.soc_calc_capacity_remain is not None:
            # calculate remaining capacity based on current
            self.soc_calc_capacity_remain = self.soc_calc_capacity_remain + self.current_calc * (current_time - self.soc_calc_capacity_remain_last_time) / 3600

            # limit soc_calc_capacity_remain to capacity and zero
            # in case 100% is reached and the battery is not fully charged
            # in case 0% is reached and the battery is not fully discharged
            self.soc_calc_capacity_remain = max(min(self.soc_calc_capacity_remain, self.capacity), 0)
            self.soc_calc_capacity_remain_last_time = current_time

            # execute checks only if one cell reaches min voltage
            # use lowest cell voltage, since in this case the battery is empty
            # else a unbalanced battery won't reach 0% and the BMS will shut down
            if self.get_min_cell_voltage() <= utils.MIN_CELL_VOLTAGE:
                # check if battery is still being discharged
                if self.current_calc < 0 and self.soc_calc_reset_start_time:
                    # set soc to 0%, if SOC_RESET_TIME is reached and soc_calc is not rounded 0%
                    if (int(current_time) - self.soc_calc_reset_start_time) > SOC_RESET_TIME and round(self.soc_calc, 0) != 0:
                        logger.info("SOC set to 0%")
                        self.soc_calc_capacity_remain = 0
                        self.soc_calc_reset_start_time = None
                else:
                    self.soc_calc_reset_start_time = int(current_time)
        else:
            # if soc_calc is not available initialize it from the BMS
            if self.soc_calc is None:
                # if there is a SOC from the BMS then use it
                if self.soc is not None:
                    self.soc_calc_capacity_remain = self.capacity * self.soc / 100
                    logger.debug("SOC initialized from BMS and set to " + str(self.soc) + "%")
                # else set it to 100%
                # this is currently (2024.04.13) not possible, since then the driver won't start, if there is no SOC
                # but leave it in case a BMS without SOC should be added
                else:
                    self.soc_calc_capacity_remain = self.capacity
                    logger.debug("SOC initialized and set to 100%")
            # else initialize it from dbus
            else:
                self.soc_calc_capacity_remain = self.capacity * self.soc_calc / 100 if self.soc_calc > 0 else 0
                logger.debug("SOC initialized from dbus and set to " + str(self.soc_calc) + "%")

            self.soc_calc_capacity_remain_last_time = current_time

        # calculate the SOC based on remaining capacity
        return round(max(min((self.soc_calc_capacity_remain / self.capacity) * 100, 100), 0), 3)

    def soc_reset_voltage_management(self) -> None:
        """
        Call this method only, if `SOC_RESET_AFTER_DAYS` is not False.

        It sets the `self.max_battery_voltage` to the `SOC_RESET_VOLTAGE` once needed.

        :return: None
        """

        soc_reset_last_reached_days_ago = 0 if self.soc_reset_last_reached == 0 else (((int(time()) - self.soc_reset_last_reached) / 60 / 60 / 24))

        # set soc_reset_requested to True, if the days are over
        # it gets set to False once the bulk voltage was reached once
        if (
            utils.SOC_RESET_AFTER_DAYS is not False
            and self.soc_reset_requested is False
            and self.allow_max_voltage
            and (self.soc_reset_last_reached == 0 or utils.SOC_RESET_AFTER_DAYS < soc_reset_last_reached_days_ago)
        ):
            self.soc_reset_requested = True

        self.soc_reset_battery_voltage = round(utils.SOC_RESET_VOLTAGE * self.cell_count, 2)

        if self.soc_reset_requested:
            self.max_battery_voltage = self.soc_reset_battery_voltage
        else:
            self.max_battery_voltage = round(utils.MAX_CELL_VOLTAGE * self.cell_count, 2)

    def manage_charge_voltage_linear(self) -> None:
        """
        Manages the charge voltage using linear interpolation by setting `self.control_voltage`.

        :return: None
        """
        found_high_cell_voltage = False
        voltage_sum = 0
        penalty_sum = 0
        time_diff = 0
        control_voltage = 0
        current_time = int(time())

        # meassurment and variation tolerance in volts
        measurement_tolerance_variation = 0.5

        try:
            # calculate voltage sum and check for cell overvoltage
            for i in range(self.cell_count):
                voltage = self.get_cell_voltage(i)
                if voltage:
                    voltage_sum += voltage

                    # calculate penalty sum to prevent single cell overcharge by using current cell voltage
                    if self.max_battery_voltage != self.soc_reset_battery_voltage and voltage > utils.MAX_CELL_VOLTAGE:
                        # found_high_cell_voltage: reset to False is not needed, since it is recalculated every second
                        found_high_cell_voltage = True
                        penalty_sum += voltage - utils.MAX_CELL_VOLTAGE
                    elif self.max_battery_voltage == self.soc_reset_battery_voltage and voltage > utils.SOC_RESET_VOLTAGE:
                        # found_high_cell_voltage: reset to False is not needed, since it is recalculated every second
                        found_high_cell_voltage = True
                        penalty_sum += voltage - utils.SOC_RESET_VOLTAGE

            voltage_cell_diff = self.get_max_cell_voltage() - self.get_min_cell_voltage()

            if self.max_voltage_start_time is None:
                # start timer, if max voltage is reached and cells are balanced
                if (
                    (self.max_battery_voltage - utils.VOLTAGE_DROP) <= voltage_sum
                    and voltage_cell_diff <= utils.CELL_VOLTAGE_DIFF_KEEP_MAX_VOLTAGE_UNTIL
                    and self.allow_max_voltage
                ):
                    self.max_voltage_start_time = current_time
                # allow max voltage again, if cells are unbalanced or SoC threshold is reached
                elif (
                    utils.SOC_LEVEL_TO_RESET_VOLTAGE_LIMIT > self.soc_calc or voltage_cell_diff >= utils.CELL_VOLTAGE_DIFF_TO_RESET_VOLTAGE_LIMIT
                ) and not self.allow_max_voltage:
                    self.allow_max_voltage = True
                else:
                    pass
            else:
                if voltage_cell_diff > utils.CELL_VOLTAGE_DIFF_KEEP_MAX_VOLTAGE_TIME_RESTART:
                    self.max_voltage_start_time = current_time

                time_diff = current_time - self.max_voltage_start_time
                # keep max voltage for MAX_VOLTAGE_TIME_SEC more seconds
                if utils.MAX_VOLTAGE_TIME_SEC < time_diff:
                    self.allow_max_voltage = False
                    self.max_voltage_start_time = None

                    if self.soc_calc <= utils.SOC_LEVEL_TO_RESET_VOLTAGE_LIMIT:
                        # set error code, to show in the GUI that something is wrong
                        self.manage_error_code(8)

                        # write to log, that reset to float was not possible
                        logger.error(
                            f"Could not change to float voltage. Battery SoC ({self.soc_calc}%) is lower"
                            + f" than SOC_LEVEL_TO_RESET_VOLTAGE_LIMIT ({utils.SOC_LEVEL_TO_RESET_VOLTAGE_LIMIT}%)."
                            + " Please reset SoC manually or lower the SOC_LEVEL_TO_RESET_VOLTAGE_LIMIT in the"
                            + ' "config.ini".'
                        )

                # we don't forget to reset max_voltage_start_time wenn we going to bulk(dynamic) mode
                # regardless of whether we were in absorption mode or not
                if voltage_sum < self.max_battery_voltage - measurement_tolerance_variation:
                    self.max_voltage_start_time = None

            # Bulk or Absorption mode
            if self.allow_max_voltage:

                # use I-Controller
                if utils.CVL_ICONTROLLER_MODE:
                    if self.control_voltage:
                        # 6 decimals are needed for a proper I-controller working
                        # https://github.com/Louisvdw/dbus-serialbattery/issues/1041
                        control_voltage = round(
                            self.control_voltage
                            - (
                                (
                                    self.get_max_cell_voltage()
                                    - (utils.SOC_RESET_VOLTAGE if self.soc_reset_requested else utils.MAX_CELL_VOLTAGE)
                                    - utils.CELL_VOLTAGE_DIFF_KEEP_MAX_VOLTAGE_UNTIL
                                )
                                * utils.CVL_ICONTROLLER_FACTOR
                            ),
                            6,
                        )
                    else:
                        control_voltage = self.max_battery_voltage

                    control_voltage = min(
                        max(control_voltage, self.min_battery_voltage),
                        self.max_battery_voltage,
                    )

                # use P-Controller
                else:
                    if found_high_cell_voltage:
                        # reduce voltage by penalty sum
                        # keep penalty above min battery voltage and below max battery voltage
                        control_voltage = round(
                            min(
                                max(
                                    voltage_sum - penalty_sum,
                                    self.min_battery_voltage,
                                ),
                                self.max_battery_voltage,
                            ),
                            6,
                        )
                    else:
                        control_voltage = self.max_battery_voltage

                self.control_voltage = control_voltage

                self.charge_mode = "Bulk" if self.max_voltage_start_time is None else "Absorption"
                if found_high_cell_voltage:
                    self.charge_mode += " Dynamic"

                if self.max_battery_voltage == self.soc_reset_battery_voltage:
                    self.charge_mode += " & SoC Reset"

                if self.get_balancing() and voltage_cell_diff >= utils.CELL_VOLTAGE_DIFF_TO_RESET_VOLTAGE_LIMIT:
                    self.charge_mode += " + Balancing"
            # Float mode
            else:
                float_voltage = round((utils.FLOAT_CELL_VOLTAGE * self.cell_count), 2)
                charge_mode = "Float"

                # reset bulk when going into float
                if self.soc_reset_requested:
                    # logger.info("set soc_reset_requested to False")
                    self.soc_reset_requested = False
                    self.soc_reset_last_reached = current_time

                if self.control_voltage:
                    # check if battery changed from bulk/absoprtion to float
                    if self.charge_mode is not None and not self.charge_mode.startswith("Float"):
                        self.transition_start_time = current_time
                        self.initial_control_voltage = self.control_voltage
                        charge_mode = "Float Transition"

                        # Assume battery SOC ist 100% at this stage
                        self.trigger_soc_reset()

                        # Set timestamp of full charge for history
                        if "timestamp_last_full_charge" not in self.history.exclude_values_to_calculate:
                            self.history.timestamp_last_full_charge = int(time())

                        if utils.SOC_CALCULATION:
                            logger.info("SOC set to 100%")
                            self.soc_calc_capacity_remain = self.capacity
                            self.soc_calc_reset_start_time = None

                    elif self.charge_mode.startswith("Float Transition"):
                        elapsed_time = current_time - self.transition_start_time
                        # Voltage reduction per second
                        VOLTAGE_REDUCTION_PER_SECOND = 0.01 / 10
                        voltage_reduction = min(
                            VOLTAGE_REDUCTION_PER_SECOND * elapsed_time,
                            self.initial_control_voltage - float_voltage,
                        )
                        self.control_voltage = self.initial_control_voltage - voltage_reduction

                        if self.control_voltage <= float_voltage:
                            self.control_voltage = float_voltage
                            charge_mode = "Float"
                        else:
                            charge_mode = "Float Transition"
                else:
                    self.control_voltage = float_voltage

                self.charge_mode = charge_mode

            self.charge_mode += " (Linear Mode)"

            # debug information
            if utils.GUI_PARAMETERS_SHOW_ADDITIONAL_INFO or logger.isEnabledFor(logging.DEBUG):

                soc_reset_days_ago = round((current_time - self.soc_reset_last_reached) / 60 / 60 / 24, 2)
                soc_reset_in_days = round(utils.SOC_RESET_AFTER_DAYS - soc_reset_days_ago, 2)

                driver_start_time_dt = datetime.fromtimestamp(self.driver_start_time)
                formatted_time = driver_start_time_dt.strftime("%Y.%m.%d %H:%M:%S")

                self.charge_mode_debug = (
                    f"driver started: {formatted_time} • running since: {self.get_seconds_to_string(int(time()) - self.driver_start_time)}\n"
                    + f"max_battery_voltage: {(self.max_battery_voltage):.2f} V • "
                    + f"control_voltage: {self.control_voltage:.2f} V\n"
                    + f"voltage: {self.voltage:.2f} V • "
                    + f"VOLTAGE_DROP: {utils.VOLTAGE_DROP:.2f} V\n"
                    + f"voltage_sum: {voltage_sum:.2f} V • "
                    + f"voltage_cell_diff: {voltage_cell_diff:.3f} V\n"
                    + f"max_cell_voltage: {self.get_max_cell_voltage()} V • penalty_sum: {penalty_sum:.3f} V\n"
                    + f"soc: {self.soc}% • soc_calc: {self.soc_calc}%\n"
                    + f"current: {self.current:.2f}A"
                    + (f" • current_calc: {self.current_calc:.2f} A\n" if self.current_calc is not None else "\n")
                    + f"current_time: {current_time}\n"
                    + f"linear_cvl_last_set: {self.linear_cvl_last_set}\n"
                    + f"charge_fet: {self.charge_fet} • control_allow_charge: {self.control_allow_charge}\n"
                    + f"discharge_fet: {self.discharge_fet} • "
                    + f"control_allow_discharge: {self.control_allow_discharge}\n"
                    + f"block_because_disconnect: {self.block_because_disconnect}\n"
                    + "soc_reset_last_reached: "
                    + ("Never" if self.soc_reset_last_reached == 0 else f"{soc_reset_days_ago}")
                    + f" d ago, next in {soc_reset_in_days} d\n"
                    + (
                        f"soc_calc_capacity_remain: {self.soc_calc_capacity_remain:.3f}/{self.capacity} Ah\n"
                        if self.soc_calc_capacity_remain is not None
                        else ""
                    )
                    + "soc_calc_reset_start_time: "
                    + (f"{int(current_time - self.soc_calc_reset_start_time)}/60" if self.soc_calc_reset_start_time is not None else "None")
                )

                self.charge_mode_debug_float = (
                    "-- switch to float requirements (Linear Mode) --\n"
                    + f"max_battery_voltage: {(self.max_battery_voltage - utils.VOLTAGE_DROP):.2f} <= "
                    + f"{voltage_sum:.2f} :voltage_sum\n"
                    + "AND\n"
                    + f"voltage_cell_diff: {voltage_cell_diff:.3f} <= "
                    + f"{utils.CELL_VOLTAGE_DIFF_KEEP_MAX_VOLTAGE_UNTIL:.3f} "
                    + ":CELL_VOLTAGE_DIFF_KEEP_MAX_VOLTAGE_UNTIL\n"
                    + "AND\n"
                    + f"allow_max_voltage: {self.allow_max_voltage} == True\n"
                    + "AND\n"
                    + f"MAX_VOLTAGE_TIME_SEC: {utils.MAX_VOLTAGE_TIME_SEC} < {time_diff} :time_diff"
                )

                self.charge_mode_debug_bulk = (
                    "-- switch to bulk requirements (Linear Mode) --\n"
                    + "a) SOC_LEVEL_TO_RESET_VOLTAGE_LIMIT: "
                    + f"{utils.SOC_LEVEL_TO_RESET_VOLTAGE_LIMIT} > {self.soc_calc} :soc_calc\n"
                    + "OR\n"
                    + f"b) voltage_cell_diff: {voltage_cell_diff:.3f} >= "
                    + f"{utils.CELL_VOLTAGE_DIFF_TO_RESET_VOLTAGE_LIMIT:.3f} "
                    + ":CELL_VOLTAGE_DIFF_TO_RESET_VOLTAGE_LIMIT\n"
                    + "AND\n"
                    + f"allow_max_voltage: {self.allow_max_voltage} == False"
                )

        except TypeError:
            self.control_voltage = round((utils.FLOAT_CELL_VOLTAGE * self.cell_count), 2)
            self.charge_mode = "Error, please check the logs!"

            # set error code, to show in the GUI that something is wrong
            self.manage_error_code(8)

            exception_type, exception_object, exception_traceback = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error("Non blocking exception occurred: " + f"{repr(exception_object)} of type {exception_type} in {file} line #{line}")

    def set_cvl_linear(self, control_voltage: float) -> bool:
        """
        Set CVL only once every `LINEAR_RECALCULATION_EVERY` seconds or if the CVL changes more than
        `LINEAR_RECALCULATION_ON_PERC_CHANGE` percent.

        TODO: Seems to not be needed anymore. Will be removed in future.

        :return: The status, if the CVL was set
        """
        current_time = int(time())
        diff = abs(self.control_voltage - control_voltage) if self.control_voltage is not None else 0

        if utils.LINEAR_RECALCULATION_EVERY <= current_time - self.linear_cvl_last_set or (
            diff >= self.control_voltage * utils.LINEAR_RECALCULATION_ON_PERC_CHANGE / 100 / 10  # for more precision, since the changes are small in this case
        ):
            self.control_voltage = control_voltage
            self.linear_cvl_last_set = current_time
            return True

        return False

    def manage_charge_voltage_step(self) -> None:
        """
        Manages the charge voltage using a step function by setting `self.control_voltage`.

        :return: None
        """
        voltage_sum = 0
        time_diff = 0
        current_time = int(time())

        try:
            # calculate battery sum
            for i in range(self.cell_count):
                voltage = self.get_cell_voltage(i)
                if voltage:
                    voltage_sum += voltage

            voltage_cell_diff = self.get_max_cell_voltage() - self.get_min_cell_voltage()

            if self.max_voltage_start_time is None:
                # check if max voltage is reached and start timer to keep max voltage
                if (self.max_battery_voltage - utils.VOLTAGE_DROP) <= voltage_sum and self.allow_max_voltage:
                    # example 2
                    self.max_voltage_start_time = current_time

                # check if reset soc is greater than battery soc
                # this prevents flapping between max and float voltage
                elif utils.SOC_LEVEL_TO_RESET_VOLTAGE_LIMIT > self.soc_calc and not self.allow_max_voltage:
                    self.allow_max_voltage = True

                # do nothing
                else:
                    pass

            # timer started
            else:
                time_diff = current_time - self.max_voltage_start_time
                if utils.MAX_VOLTAGE_TIME_SEC < time_diff:
                    self.allow_max_voltage = False
                    self.max_voltage_start_time = None

                else:
                    pass

            if self.allow_max_voltage:
                self.control_voltage = self.max_battery_voltage
                self.charge_mode = "Bulk" if self.max_voltage_start_time is None else "Absorption"

                if self.max_battery_voltage == self.soc_reset_battery_voltage:
                    self.charge_mode += " & SoC Reset"

            else:
                # check if battery changed from bulk/absoprtion to float
                if self.charge_mode is not None and not self.charge_mode.startswith("Float"):
                    # Assume battery SOC ist 100% at this stage
                    self.trigger_soc_reset()

                    # Set timestamp of full charge for history
                    if "timestamp_last_full_charge" not in self.history.exclude_values_to_calculate:
                        self.history.timestamp_last_full_charge = int(time())

                    if utils.SOC_CALCULATION:
                        logger.info("SOC set to 100%")
                        self.soc_calc_capacity_remain = self.capacity
                        self.soc_calc_reset_start_time = None

                self.control_voltage = round(utils.FLOAT_CELL_VOLTAGE * self.cell_count, 2)
                self.charge_mode = "Float"
                # reset bulk when going into float
                if self.soc_reset_requested:
                    # logger.info("set soc_reset_requested to False")
                    self.soc_reset_requested = False
                    self.soc_reset_last_reached = current_time

            self.charge_mode += " (Step Mode)"

            # debug information
            if utils.GUI_PARAMETERS_SHOW_ADDITIONAL_INFO or logger.isEnabledFor(logging.DEBUG):

                soc_reset_days_ago = round((current_time - self.soc_reset_last_reached) / 60 / 60 / 24, 2)
                soc_reset_in_days = round(utils.SOC_RESET_AFTER_DAYS - soc_reset_days_ago, 2)

                driver_start_time_dt = datetime.fromtimestamp(self.driver_start_time)
                formatted_time = driver_start_time_dt.strftime("%Y.%m.%d %H:%M:%S")

                self.charge_mode_debug = (
                    f"driver started: {formatted_time} • running since: {self.get_seconds_to_string(int(time()) - self.driver_start_time)}\n"
                    + f"max_battery_voltage: {(self.max_battery_voltage):.2f} V • "
                    + f"control_voltage: {self.control_voltage:.2f} V\n"
                    + f"voltage: {self.voltage:.2f} V • "
                    + f"VOLTAGE_DROP: {utils.VOLTAGE_DROP:.2f} V\n"
                    + f"voltage_sum: {voltage_sum:.2f} V • "
                    + f"voltage_cell_diff: {voltage_cell_diff:.3f} V\n"
                    + f"max_cell_voltage: {self.get_max_cell_voltage()} V\n"
                    + f"soc: {self.soc}% • soc_calc: {self.soc_calc}%\n"
                    + f"current: {self.current:.2f}A"
                    + (f" • current_calc: {self.current_calc:.2f} A\n" if self.current_calc is not None else "\n")
                    + f"current_time: {current_time}\n"
                    + f"linear_cvl_last_set: {self.linear_cvl_last_set}\n"
                    + f"charge_fet: {self.charge_fet} • control_allow_charge: {self.control_allow_charge}\n"
                    + f"discharge_fet: {self.discharge_fet} • "
                    + f"control_allow_discharge: {self.control_allow_discharge}\n"
                    + f"block_because_disconnect: {self.block_because_disconnect}\n"
                    + "soc_reset_last_reached: "
                    + ("Never" if self.soc_reset_last_reached == 0 else f"{soc_reset_days_ago}")
                    + f" d ago, next in {soc_reset_in_days} d\n"
                    + (
                        f"soc_calc_capacity_remain: {self.soc_calc_capacity_remain:.3f}/{self.capacity} Ah\n"
                        if self.soc_calc_capacity_remain is not None
                        else ""
                    )
                    + "soc_calc_reset_start_time: "
                    + (f"{int(current_time - self.soc_calc_reset_start_time)}/60" if self.soc_calc_reset_start_time is not None else "None")
                )

                self.charge_mode_debug_float = (
                    "-- switch to float requirements (Step Mode) --\n"
                    + f"max_battery_voltage: {(self.max_battery_voltage - utils.VOLTAGE_DROP):.2f} <= "
                    + f"{voltage_sum:.2f} :voltage_sum\n"
                    + "AND\n"
                    + f"allow_max_voltage: {self.allow_max_voltage} == True\n"
                    + "AND\n"
                    + f"MAX_VOLTAGE_TIME_SEC: {utils.MAX_VOLTAGE_TIME_SEC} < {time_diff} :time_diff"
                )

                self.charge_mode_debug_bulk = (
                    "-- switch to bulk requirements (Step Mode) --\n"
                    + "SOC_LEVEL_TO_RESET_VOLTAGE_LIMIT: "
                    + f"{utils.SOC_LEVEL_TO_RESET_VOLTAGE_LIMIT} > {self.soc_calc} :soc_calc\n"
                    + "AND\n"
                    + f"allow_max_voltage: {self.allow_max_voltage} == False"
                )

        except TypeError:
            self.control_voltage = round((utils.FLOAT_CELL_VOLTAGE * self.cell_count), 2)
            self.charge_mode = "Error, please check the logs!"

            # set error code, to show in the GUI that something is wrong
            self.manage_error_code(8)

            exception_type, exception_object, exception_traceback = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error("Non blocking exception occurred: " + f"{repr(exception_object)} of type {exception_type} in {file} line #{line}")

    def manage_charge_and_discharge_current(self) -> None:
        """
        Manages the charge and discharge current by setting `self.control_charge_current`
        and `self.control_discharge_current`.

        :return: None
        """
        # ---------- Manage Charge Current Limitations ----------
        charge_limits = {utils.MAX_BATTERY_CHARGE_CURRENT: "Max Battery Charge Current"}

        # if BMS limit is lower then config limit and therefore the values are not the same,
        # then the limit was also read from the BMS
        if isinstance(self.max_battery_charge_current, (int, float)) and utils.MAX_BATTERY_CHARGE_CURRENT > self.max_battery_charge_current:
            charge_limits.update({self.max_battery_charge_current: "BMS Settings"})

        if utils.CCCM_CV_ENABLE:
            tmp = self.calc_max_charge_current_from_cell_voltage()
            if self.max_battery_charge_current != tmp:
                if tmp in charge_limits:
                    # do not add string, if global limitation is applied
                    if charge_limits[tmp] != "Max Battery Charge Current":
                        charge_limits.update({tmp: charge_limits[tmp] + ", Cell Voltage"})
                    else:
                        pass
                else:
                    charge_limits.update({tmp: "Cell Voltage"})

        if utils.CCCM_T_ENABLE:
            tmp = self.calc_max_charge_current_from_temperature()
            if self.max_battery_charge_current != tmp:
                if tmp in charge_limits:
                    # do not add string, if global limitation is applied
                    if charge_limits[tmp] != "Max Battery Charge Current":
                        charge_limits.update({tmp: charge_limits[tmp] + ", Temp"})
                    else:
                        pass
                else:
                    charge_limits.update({tmp: "Temp"})

        if utils.CCCM_SOC_ENABLE:
            tmp = self.calc_max_charge_current_from_soc()
            if self.max_battery_charge_current != tmp:
                if tmp in charge_limits:
                    # do not add string, if global limitation is applied
                    if charge_limits[tmp] != "Max Battery Charge Current":
                        charge_limits.update({tmp: charge_limits[tmp] + ", SoC"})
                    else:
                        pass
                else:
                    charge_limits.update({tmp: "SoC"})

        # set CCL to 0, if BMS does not allow to charge
        if self.charge_fet is False or self.block_because_disconnect:
            if 0 in charge_limits:
                charge_limits.update({0: charge_limits[0] + ", BMS"})
            else:
                charge_limits.update({0: "BMS"})

        """
        do not set CCL immediately, but only
        - after LINEAR_RECALCULATION_EVERY passed
        - if CCL changes to 0
        - if CCL changes more than LINEAR_RECALCULATION_ON_PERC_CHANGE
        """
        ccl = round(min(charge_limits), 3)
        diff = abs(self.control_charge_current - ccl) if self.control_charge_current is not None else 0
        if (
            int(time()) - self.linear_ccl_last_set >= utils.LINEAR_RECALCULATION_EVERY
            or (diff >= self.control_charge_current * utils.LINEAR_RECALCULATION_ON_PERC_CHANGE / 100)
            or (ccl == 0 and self.control_charge_current != 0)
        ):
            self.linear_ccl_last_set = int(time())

            # Introduce a threshold mechanism to prevent flapping
            if ccl == 0:
                self.control_charge_current = ccl
                self.charge_limitation = charge_limits[min(charge_limits)]
            else:
                # Don't allow recovery if the new allowed current is smaller than 1% of the previous allowed current
                if self.control_charge_current == 0 and ccl < utils.MAX_BATTERY_CHARGE_CURRENT * utils.CHARGE_CURRENT_RECOVERY_THRESHOLD_PERCENT:
                    self.charge_limitation = charge_limits[min(charge_limits)] + " *"
                else:
                    self.control_charge_current = ccl
                    self.charge_limitation = charge_limits[min(charge_limits)]

        # set allow to charge to no, if CCL is 0
        if self.control_charge_current == 0:
            self.control_allow_charge = False
        else:
            self.control_allow_charge = True

        #####

        # ---------- Manage Discharge Current Limitations ----------
        discharge_limits = {utils.MAX_BATTERY_DISCHARGE_CURRENT: "Max Battery Discharge Current"}

        # if BMS limit is lower then config limit and therefore the values are not the same,
        # then the limit was also read from the BMS
        if isinstance(self.max_battery_discharge_current, (int, float)) and utils.MAX_BATTERY_DISCHARGE_CURRENT > self.max_battery_discharge_current:
            discharge_limits.update({self.max_battery_discharge_current: "BMS Settings"})

        if utils.DCCM_CV_ENABLE:
            tmp = self.calc_max_discharge_current_from_cell_voltage()
            if self.max_battery_discharge_current != tmp:
                if tmp in discharge_limits:
                    # do not add string, if global limitation is applied
                    if discharge_limits[tmp] != "Max Battery Discharge Current":
                        discharge_limits.update({tmp: discharge_limits[tmp] + ", Cell Voltage"})
                    else:
                        pass
                else:
                    discharge_limits.update({tmp: "Cell Voltage"})

        if utils.DCCM_T_ENABLE:
            tmp = self.calc_max_discharge_current_from_temperature()
            if self.max_battery_discharge_current != tmp:
                if tmp in discharge_limits:
                    # do not add string, if global limitation is applied
                    if discharge_limits[tmp] != "Max Battery Discharge Current":
                        discharge_limits.update({tmp: discharge_limits[tmp] + ", Temp"})
                    else:
                        pass
                else:
                    discharge_limits.update({tmp: "Temp"})

        if utils.DCCM_SOC_ENABLE:
            tmp = self.calc_max_discharge_current_from_soc()
            if self.max_battery_discharge_current != tmp:
                if tmp in discharge_limits:
                    # do not add string, if global limitation is applied
                    if discharge_limits[tmp] != "Max Battery Discharge Current":
                        discharge_limits.update({tmp: discharge_limits[tmp] + ", SoC"})
                    else:
                        pass
                else:
                    discharge_limits.update({tmp: "SoC"})

        # set DCL to 0, if BMS does not allow to discharge
        if self.discharge_fet is False or self.block_because_disconnect:
            if 0 in discharge_limits:
                discharge_limits.update({0: discharge_limits[0] + ", BMS"})
            else:
                discharge_limits.update({0: "BMS"})

        """
        do not set DCL immediately, but only
        - after LINEAR_RECALCULATION_EVERY passed
        - if DCL changes to 0
        - if DCL changes more than LINEAR_RECALCULATION_ON_PERC_CHANGE
        """
        dcl = round(min(discharge_limits), 3)
        diff = abs(self.control_discharge_current - dcl) if self.control_discharge_current is not None else 0
        if (
            int(time()) - self.linear_dcl_last_set >= utils.LINEAR_RECALCULATION_EVERY
            or (diff >= self.control_discharge_current * utils.LINEAR_RECALCULATION_ON_PERC_CHANGE / 100)
            or (dcl == 0 and self.control_discharge_current != 0)
        ):
            self.linear_dcl_last_set = int(time())

            # Introduce a threshold mechanism to prevent flapping
            if dcl == 0:
                self.control_discharge_current = dcl
                self.discharge_limitation = discharge_limits[min(discharge_limits)]
            else:
                # Don't allow recovery if the new allowed current is smaller than 1% of the previous allowed current
                if self.control_discharge_current == 0 and dcl < utils.MAX_BATTERY_DISCHARGE_CURRENT * utils.DISCHARGE_CURRENT_RECOVERY_THRESHOLD_PERCENT:
                    self.discharge_limitation = discharge_limits[min(discharge_limits)] + " *"
                else:
                    self.control_discharge_current = dcl
                    self.discharge_limitation = discharge_limits[min(discharge_limits)]

        # set allow to discharge to no, if DCL is 0
        if self.control_discharge_current == 0:
            self.control_allow_discharge = False
        else:
            self.control_allow_discharge = True

    def calc_max_charge_current_from_cell_voltage(self) -> float:
        """
        Calculate the maximum charge current referring to the cell voltage.

        :return: The maximum charge current
        """
        if self.get_max_cell_voltage() is None:
            logger.warning(
                "calc_max_charge_current_from_cell_voltage():"
                + f" get_max_cell_voltage() is {self.get_max_cell_voltage()}, using default current instead."
                + " If you don't see this warning very often, you can ignore it."
            )
            return self.max_battery_charge_current

        try:
            if utils.LINEAR_LIMITATION_ENABLE:
                return utils.calc_linear_relationship(
                    self.get_max_cell_voltage(),
                    utils.CELL_VOLTAGES_WHILE_CHARGING,
                    utils.MAX_CHARGE_CURRENT_CV,
                )
            return utils.calc_step_relationship(
                self.get_max_cell_voltage(),
                utils.CELL_VOLTAGES_WHILE_CHARGING,
                utils.MAX_CHARGE_CURRENT_CV,
                False,
            )
        except Exception:
            # set error code, to show in the GUI that something is wrong
            self.manage_error_code(8)

            logger.error(
                "calc_max_charge_current_from_cell_voltage(): Error while executing,"
                + " using default current instead."
                + " If you don't see this warning very often, you can ignore it."
            )
            logger.error(
                f"get_max_cell_voltage: {self.get_max_cell_voltage()}"
                + f" • CELL_VOLTAGES_WHILE_CHARGING: {utils.CELL_VOLTAGES_WHILE_CHARGING}"
                + f" • MAX_CHARGE_CURRENT_CV: {utils.MAX_CHARGE_CURRENT_CV}"
            )

            exception_type, exception_object, exception_traceback = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error("Non blocking exception occurred: " + f"{repr(exception_object)} of type {exception_type} in {file} line #{line}")
            return self.max_battery_charge_current

    def calc_max_discharge_current_from_cell_voltage(self) -> float:
        """
        Calculate the maximum discharge current referring to the cell voltage.

        :return: The maximum discharge current
        """
        if self.get_min_cell_voltage() is None:
            logger.warning(
                "calc_max_discharge_current_from_cell_voltage():"
                + f" get_min_cell_voltage() is {self.get_min_cell_voltage()}, using default current instead."
                + " If you don't see this warning very often, you can ignore it."
            )
            return self.max_battery_discharge_current

        try:
            if utils.LINEAR_LIMITATION_ENABLE:
                return utils.calc_linear_relationship(
                    self.get_min_cell_voltage(),
                    utils.CELL_VOLTAGES_WHILE_DISCHARGING,
                    utils.MAX_DISCHARGE_CURRENT_CV,
                )
            return utils.calc_step_relationship(
                self.get_min_cell_voltage(),
                utils.CELL_VOLTAGES_WHILE_DISCHARGING,
                utils.MAX_DISCHARGE_CURRENT_CV,
                True,
            )
        except Exception:
            # set error code, to show in the GUI that something is wrong
            self.manage_error_code(8)

            logger.error("calc_max_charge_current_from_cell_voltage(): Error while executing," + " using default current instead.")
            logger.error(
                f"get_min_cell_voltage: {self.get_min_cell_voltage()}"
                + f" • CELL_VOLTAGES_WHILE_DISCHARGING: {utils.CELL_VOLTAGES_WHILE_DISCHARGING}"
                + f" • MAX_DISCHARGE_CURRENT_CV: {utils.MAX_DISCHARGE_CURRENT_CV}"
            )

            exception_type, exception_object, exception_traceback = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error("Non blocking exception occurred: " + f"{repr(exception_object)} of type {exception_type} in {file} line #{line}")
            return self.max_battery_charge_current

    def calc_max_charge_current_from_temperature(self) -> float:
        """
        Calculate the maximum charge current referring to the temperature.

        :return: The maximum charge current
        """
        if self.get_max_temperature() is None or self.get_min_temperature() is None:
            logging.warning(
                "calc_max_charge_current_from_temperature():"
                + f" get_max_temperature() is {self.get_max_temperature()} or get_min_temperature() is {self.get_min_temperature()}"
                + ", using default current instead."
                + " If you don't see this warning very often, you can ignore it."
            )
            return self.max_battery_charge_current

        temperatures = {0: self.get_max_temperature(), 1: self.get_min_temperature()}

        try:
            for key, currentMaxTemperature in temperatures.items():
                if utils.LINEAR_LIMITATION_ENABLE:
                    temperatures[key] = utils.calc_linear_relationship(
                        currentMaxTemperature,
                        utils.TEMPERATURES_WHILE_CHARGING,
                        utils.MAX_CHARGE_CURRENT_T,
                    )
                else:
                    temperatures[key] = utils.calc_step_relationship(
                        currentMaxTemperature,
                        utils.TEMPERATURES_WHILE_CHARGING,
                        utils.MAX_CHARGE_CURRENT_T,
                        False,
                    )
            return min(temperatures[0], temperatures[1])
        except Exception:
            # set error code, to show in the GUI that something is wrong
            self.manage_error_code(8)

            logger.error("calc_max_charge_current_from_temperature(): Error while executing," + " using default current instead.")
            logger.error(
                f"temperatures: {temperatures}"
                + f" • TEMPERATURES_WHILE_CHARGING: {utils.TEMPERATURES_WHILE_CHARGING}"
                + f" • MAX_CHARGE_CURRENT_T: {utils.MAX_CHARGE_CURRENT_T}"
            )

            exception_type, exception_object, exception_traceback = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error("Non blocking exception occurred: " + f"{repr(exception_object)} of type {exception_type} in {file} line #{line}")
            return self.max_battery_charge_current

    def calc_max_discharge_current_from_temperature(self) -> float:
        """
        Calculate the maximum discharge current referring to the temperature.

        :return: The maximum discharge current
        """
        if self.get_max_temperature() is None or self.get_min_temperature() is None:
            logging.warning(
                "calc_max_discharge_current_from_temperature():"
                + f" get_max_temperature() is {self.get_max_temperature()} or get_min_temperature() is {self.get_min_temperature()}"
                + ", using default current instead."
                + " If you don't see this warning very often, you can ignore it."
            )
            return self.max_battery_discharge_current

        temperatures = {0: self.get_max_temperature(), 1: self.get_min_temperature()}

        try:
            for key, currentMaxTemperature in temperatures.items():
                if utils.LINEAR_LIMITATION_ENABLE:
                    temperatures[key] = utils.calc_linear_relationship(
                        currentMaxTemperature,
                        utils.TEMPERATURES_WHILE_DISCHARGING,
                        utils.MAX_DISCHARGE_CURRENT_T,
                    )
                else:
                    temperatures[key] = utils.calc_step_relationship(
                        currentMaxTemperature,
                        utils.TEMPERATURES_WHILE_DISCHARGING,
                        utils.MAX_DISCHARGE_CURRENT_T,
                        True,
                    )
            return min(temperatures[0], temperatures[1])
        except Exception:
            # set error code, to show in the GUI that something is wrong
            self.manage_error_code(8)

            logger.error("calc_max_discharge_current_from_temperature(): Error while executing," + " using default current instead.")
            logger.error(
                f"temperatures: {temperatures}"
                + f" • TEMPERATURES_WHILE_DISCHARGING: {utils.TEMPERATURES_WHILE_DISCHARGING}"
                + f" • MAX_DISCHARGE_CURRENT_T: {utils.MAX_DISCHARGE_CURRENT_T}"
            )

            exception_type, exception_object, exception_traceback = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error("Non blocking exception occurred: " + f"{repr(exception_object)} of type {exception_type} in {file} line #{line}")
            return self.max_battery_charge_current

    def calc_max_charge_current_from_soc(self) -> float:
        """
        Calculate the maximum charge current referring to the SoC.

        :return: The maximum charge current
        """
        try:
            if utils.LINEAR_LIMITATION_ENABLE:
                return utils.calc_linear_relationship(
                    self.soc_calc,
                    utils.SOC_WHILE_CHARGING,
                    utils.MAX_CHARGE_CURRENT_SOC,
                )
            return utils.calc_step_relationship(
                self.soc_calc,
                utils.SOC_WHILE_CHARGING,
                utils.MAX_CHARGE_CURRENT_SOC,
                True,
            )
        except Exception:
            # set error code, to show in the GUI that something is wrong
            self.manage_error_code(8)

            logger.error("calc_max_charge_current_from_soc(): Error while executing," + " using default current instead.")
            logger.error(
                f"soc_calc: {self.soc_calc}"
                + f" • SOC_WHILE_CHARGING: {utils.SOC_WHILE_CHARGING}"
                + f" • MAX_CHARGE_CURRENT_SOC: {utils.MAX_CHARGE_CURRENT_SOC}"
            )

            exception_type, exception_object, exception_traceback = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
            return self.max_battery_charge_current

    def calc_max_discharge_current_from_soc(self) -> float:
        """
        Calculate the maximum discharge current referring to the SoC.

        :return: The maximum discharge current
        """
        try:
            if utils.LINEAR_LIMITATION_ENABLE:
                return utils.calc_linear_relationship(
                    self.soc_calc,
                    utils.SOC_WHILE_DISCHARGING,
                    utils.MAX_DISCHARGE_CURRENT_SOC,
                )
            return utils.calc_step_relationship(
                self.soc_calc,
                utils.SOC_WHILE_DISCHARGING,
                utils.MAX_DISCHARGE_CURRENT_SOC,
                True,
            )
        except Exception:
            # set error code, to show in the GUI that something is wrong
            self.manage_error_code(8)

            logger.error("calc_max_discharge_current_from_soc: Error while executing," + " using default current instead.")
            logger.error(
                f"soc_calc: {self.soc_calc}"
                + f" • SOC_WHILE_DISCHARGING: {utils.SOC_WHILE_DISCHARGING}"
                + f" • MAX_DISCHARGE_CURRENT_SOC: {utils.MAX_DISCHARGE_CURRENT_SOC}"
            )

            exception_type, exception_object, exception_traceback = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
            return self.max_battery_discharge_current

    def get_min_cell(self) -> int:
        """
        Get the cell with the lowest voltage.

        :return: The number of the cell with the lowest voltage
        """
        min_voltage = 9999
        min_cell = None
        if len(self.cells) == 0 and hasattr(self, "cell_min_no"):
            return self.cell_min_no

        for c in range(min(len(self.cells), self.cell_count)):
            if self.cells[c].voltage is not None and min_voltage > self.cells[c].voltage:
                min_voltage = self.cells[c].voltage
                min_cell = c
        return min_cell

    def get_max_cell(self) -> int:
        """
        Get the cell with the highest voltage.

        :return: The number of the cell with the highest voltage
        """
        max_voltage = 0
        max_cell = None
        if len(self.cells) == 0 and hasattr(self, "cell_max_no"):
            return self.cell_max_no

        for c in range(min(len(self.cells), self.cell_count)):
            if self.cells[c].voltage is not None and max_voltage < self.cells[c].voltage:
                max_voltage = self.cells[c].voltage
                max_cell = c
        return max_cell

    def get_min_cell_desc(self) -> Union[str, None]:
        """
        Get the description of the cell with the lowest voltage.

        :return: The description of the cell with the lowest voltage
        """
        cell_no = self.get_min_cell()
        return cell_no if cell_no is None else "C" + str(cell_no + 1)

    def get_max_cell_desc(self) -> Union[str, None]:
        """
        Get the description of the cell with the highest voltage.

        :return: The description of the cell with the highest voltage
        """
        cell_no = self.get_max_cell()
        return cell_no if cell_no is None else "C" + str(cell_no + 1)

    def get_cell_voltage(self, idx: int) -> Union[float, None]:
        """
        Get the voltage of a specific cell.

        :param idx: The index of the cell
        :return: The voltage of the cell
        """
        if idx >= min(len(self.cells), self.cell_count):
            return None
        return self.cells[idx].voltage

    def get_cell_voltage_sum(self) -> float:
        """
        This method returns the sum of all cell voltages.

        :return: The sum of all cell voltages
        """
        voltage_sum = 0
        for i in range(self.cell_count):
            voltage = self.get_cell_voltage(i)
            if voltage:
                voltage_sum += voltage
        return voltage_sum

    def get_cell_balancing(self, idx: int) -> Union[int, None]:
        """
        Get the balancing status of a specific cell.

        :param idx: The index of the cell
        :return: The balancing status of the cell
        """
        if idx >= min(len(self.cells), self.cell_count):
            return None
        if self.cells[idx].balance is not None and self.cells[idx].balance:
            return 1
        return 0

    def get_capacity_remain(self) -> Union[float, None]:
        """
        Get the remaining capacity of the battery.
        Use `self.capacity_remain` if it is set, otherwise calculate it using `self.capacity` and `self.soc_calc`.

        :return: The remaining capacity of the battery
        """
        if self.capacity_remain is not None:
            return self.capacity_remain
        if self.capacity is not None and self.soc_calc is not None:
            return self.capacity * self.soc_calc / 100
        return None

    def get_capacity_consumed(self) -> Union[float, None]:
        """
        Get the consumed capacity of the battery.

        :return: The consumed capacity of the battery
        """
        if self.capacity is not None and self.get_capacity_remain() is not None:
            return abs(self.capacity - self.get_capacity_remain()) * -1

        return None

    def get_time_to_soc(self, soc_target: float, percent_per_second: float, only_number: bool = False) -> str:
        """
        Calculate the time to reach a specific SoC target.

        :param soc_target: The target SoC
        :param percent_per_second: The percentage per second
        :param only_number: Whether to return only the seconds
        :return: The time to reach the target SoC
        """
        if self.current_calc is None or soc_target is None or percent_per_second is None:
            return None

        if self.current_calc > 0:
            soc_diff = soc_target - self.soc_calc
        else:
            soc_diff = self.soc_calc - soc_target

        """
        calculate only positive SoC points, since negative points have no sense
        when charging only points above current SoC are shown
        when discharging only points below current SoC are shown
        """
        if soc_diff < 0:
            return None

        time_to_go_str = None
        if self.soc_calc != soc_target and percent_per_second != 0 and (soc_diff > 0 or utils.TIME_TO_SOC_INC_FROM is True):
            seconds_to_go = int(soc_diff / percent_per_second)
            time_to_go_str = ""

            if only_number or utils.TIME_TO_SOC_VALUE_TYPE & 1:
                time_to_go_str += str(seconds_to_go)
                if not only_number and utils.TIME_TO_SOC_VALUE_TYPE & 2:
                    time_to_go_str += " ["
            if not only_number and utils.TIME_TO_SOC_VALUE_TYPE & 2:
                time_to_go_str += self.get_seconds_to_string(seconds_to_go)

                if utils.TIME_TO_SOC_VALUE_TYPE & 1:
                    time_to_go_str += "]"

        return time_to_go_str

    def get_seconds_to_string(self, seconds: int, precision: int = 3) -> str:
        """
        Transforms seconds to a string in the format: 1d 1h 1m 1s (Victron Style)

        :param seconds: The seconds to transform
        :param precision:
            - 0 = 1d
            - 1 = 1d 1h
            - 2 = 1d 1h 1m
            - 3 = 1d 1h 1m 1s

        This was added, since timedelta() returns strange values, if time is negative
        e.g.: seconds: -70245
            --> timedelta output: -1 day, 4:29:15
            --> calculation: -1 day + 4:29:15
            --> real value -19:30:45

        """
        tmp = "" if seconds >= 0 else "-"
        seconds = abs(seconds)

        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)

        tmp += (str(d) + "d ") if d > 0 else ""
        tmp += (str(h) + "h ") if precision >= 1 and h > 0 else ""
        tmp += (str(m) + "m ") if precision >= 2 and m > 0 else ""
        tmp += (str(s) + "s ") if precision == 3 and s > 0 else ""

        return tmp.rstrip()

    def get_min_cell_voltage(self) -> Union[float, None]:
        """
        Get the voltage of the cell with the lowest voltage.

        :return: The voltage of the cell with the lowest voltage
        """
        min_voltage = None
        if hasattr(self, "cell_min_voltage"):
            min_voltage = self.cell_min_voltage

        if min_voltage is None:
            try:
                min_voltage = min(c.voltage for c in self.cells if c.voltage is not None)
            except ValueError:
                pass
        return min_voltage

    def get_max_cell_voltage(self) -> Union[float, None]:
        max_voltage = None
        if hasattr(self, "cell_max_voltage"):
            max_voltage = self.cell_max_voltage

        if max_voltage is None:
            try:
                max_voltage = max(c.voltage for c in self.cells if c.voltage is not None)
            except ValueError:
                pass
        return max_voltage

    def get_midvoltage(self) -> Tuple[Union[float, None], Union[float, None]]:
        """
        This method returns the Voltage "in the middle of the battery"
        as well as a deviation of an ideally balanced battery. It does so by calculating the sum of the first half
        of the cells and adding 1/2 of the "middle cell" voltage (if it exists)
        :return: a tuple of the voltage in the middle, as well as a percentage deviation (total_voltage / 2)
        """
        if not utils.MIDPOINT_ENABLE or self.cell_count is None or self.cell_count == 0 or self.cell_count < 4 or len(self.cells) != self.cell_count:
            return None, None

        halfcount = int(math.floor(self.cell_count / 2))
        uneven_cells_offset = self.cell_count % 2
        half1voltage = 0
        half2voltage = 0

        try:
            half1voltage = sum(cell.voltage for cell in self.cells[:halfcount] if cell.voltage is not None)
            half2voltage = sum(cell.voltage for cell in self.cells[halfcount + uneven_cells_offset :] if cell.voltage is not None)
        except ValueError:
            pass

        try:
            extra = 0 if self.cell_count % 2 == 0 else self.cells[halfcount].voltage / 2
            # get the midpoint of the battery
            midpoint = half1voltage + extra
            return (
                abs(midpoint),
                abs((half2voltage - half1voltage) / (half2voltage + half1voltage) * 100),
            )
        except ValueError:
            return None, None

    def get_balancing(self) -> int:
        for c in range(min(len(self.cells), self.cell_count)):
            if self.cells[c].balance is not None and self.cells[c].balance:
                return 1
        return 0

    def get_temperature(self) -> Union[float, None]:
        try:
            temperature_map = {1: self.temperature_1, 2: self.temperature_2, 3: self.temperature_3, 4: self.temperature_4}
            temperature = temperature_map.get(utils.TEMPERATURE_SOURCE_BATTERY)
            if temperature is not None:
                return temperature

            temperatures = [t for t in [self.temperature_1, self.temperature_2, self.temperature_3, self.temperature_4] if t is not None]
            if not temperatures:
                return None

            return round(sum(temperatures) / len(temperatures), 1)

        except TypeError:
            return None

    def get_min_temperature(self) -> Union[float, None]:
        try:
            temperatures = [t for t in [self.temperature_1, self.temperature_2, self.temperature_3, self.temperature_4] if t is not None]
            if not temperatures:
                return None
            return min(temperatures)
        except TypeError:
            return None

    def get_min_temperature_id(self) -> Union[str, None]:
        try:
            temperatures = [(t, i) for i, t in enumerate([self.temperature_1, self.temperature_2, self.temperature_3, self.temperature_4]) if t is not None]
            if not temperatures:
                return None
            index = min(temperatures)[1]
            if index == 0:
                return utils.TEMPERATURE_1_NAME
            if index == 1:
                return utils.TEMPERATURE_2_NAME
            if index == 2:
                return utils.TEMPERATURE_3_NAME
            if index == 3:
                return utils.TEMPERATURE_4_NAME
        except TypeError:
            return None

    def get_max_temperature(self) -> Union[float, None]:
        try:
            temperatures = [t for t in [self.temperature_1, self.temperature_2, self.temperature_3, self.temperature_4] if t is not None]
            if not temperatures:
                return None
            return max(temperatures)
        except TypeError:
            return None

    def get_max_temperature_id(self) -> Union[str, None]:
        try:
            temperatures = [(t, i) for i, t in enumerate([self.temperature_1, self.temperature_2, self.temperature_3, self.temperature_4]) if t is not None]
            if not temperatures:
                return None
            index = max(temperatures)[1]
            if index == 0:
                return utils.TEMPERATURE_1_NAME
            if index == 1:
                return utils.TEMPERATURE_2_NAME
            if index == 2:
                return utils.TEMPERATURE_3_NAME
            if index == 3:
                return utils.TEMPERATURE_4_NAME
        except TypeError:
            return None

    def get_allow_to_charge(self) -> bool:
        return True if self.charge_fet and self.control_allow_charge and self.block_because_disconnect is False else False

    def get_allow_to_discharge(self) -> bool:
        return True if self.discharge_fet and self.control_allow_discharge and self.block_because_disconnect is False else False

    def get_allow_to_balance(self) -> bool:
        return True if self.balance_fet else False

    def validate_data(self) -> bool:
        """
        Used to validate the data received from the BMS.
        If the data is in the thresholds return True,
        else return False since it's very probably not a BMS
        """
        if self.capacity is not None and (self.capacity < 0 or self.capacity > 5000):
            logger.debug("Capacity outside of thresholds (from 0 to 5000): " + str(self.capacity))
            return False
        if self.current is not None and abs(self.current) > 1000:
            logger.debug("Current outside of thresholds (from -1000 to 1000): " + str(self.current))
            return False
        if self.voltage is not None and (self.voltage < 0 or self.voltage > 100):
            logger.debug("Voltage outside of thresholds (form 0 to 100): " + str(self.voltage))
            return False
        if self.soc is not None and (self.soc < 0 or self.soc > 100):
            logger.debug("SoC outside of thresholds (from 0 to 100): " + str(self.soc))
            return False

        return True

    def setup_external_sensor(self) -> None:
        """
        Setup external sensor and it's dbus items
        """
        import dbus
        import os
        from dbus.mainloop.glib import DBusGMainLoop
        from vedbus import VeDbusItemImport

        # setup external dbus paths
        try:
            DBusGMainLoop(set_as_default=True)

            # connect to the sessionbus, on a CC GX the systembus is used
            dbus_connection = dbus.SessionBus() if "DBUS_SESSION_BUS_ADDRESS" in os.environ else dbus.SystemBus()

            # dictionary containing the different items
            dbus_objects = {}

            # check if the dbus service is available
            is_present_in_vebus = utils.EXTERNAL_SENSOR_DBUS_DEVICE in dbus_connection.list_names()

            if is_present_in_vebus:

                if utils.EXTERNAL_SENSOR_DBUS_PATH_CURRENT is not None:
                    logger.info("Using external sensor for current: " + f"{utils.EXTERNAL_SENSOR_DBUS_DEVICE}{utils.EXTERNAL_SENSOR_DBUS_PATH_CURRENT}")
                    dbus_objects["Current"] = VeDbusItemImport(
                        dbus_connection,
                        utils.EXTERNAL_SENSOR_DBUS_DEVICE,
                        utils.EXTERNAL_SENSOR_DBUS_PATH_CURRENT,
                    )

                if utils.EXTERNAL_SENSOR_DBUS_PATH_SOC is not None:
                    logger.info("Using external sensor for SOC: " + f"{utils.EXTERNAL_SENSOR_DBUS_DEVICE}{utils.EXTERNAL_SENSOR_DBUS_PATH_SOC}")
                    dbus_objects["Soc"] = VeDbusItemImport(
                        dbus_connection,
                        utils.EXTERNAL_SENSOR_DBUS_DEVICE,
                        utils.EXTERNAL_SENSOR_DBUS_PATH_SOC,
                    )

                self.dbus_external_objects = dbus_objects

        except Exception:
            # set to None to avoid crashing, fallback to battery current
            utils.EXTERNAL_SENSOR_DBUS_DEVICE = None
            utils.EXTERNAL_SENSOR_DBUS_PATH_CURRENT = None
            utils.EXTERNAL_SENSOR_DBUS_PATH_SOC = None
            self.dbus_external_objects = None
            (
                exception_type,
                exception_object,
                exception_traceback,
            ) = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error("Exception occurred: " + f"{repr(exception_object)} of type {exception_type} in {file} line #{line}")
            logger.error("External current sensor setup failed, fallback to internal sensor")

    def get_current(self) -> Union[float, None]:
        """
        Get the current, either from:
        - the external sensor
        - the battery

        :return: The current
        """
        current_time = time()

        # Has to be calculated from last measurement until now
        if self.current_calc is not None and self.current_calc_last_time is not None:
            # Calculate charge based on the current from last measurement until now
            charge = self.current_calc / 3600 * (current_time - self.current_calc_last_time)

            # Coloumb count charged charge
            self.charge_charged += charge if charge > 0 else 0

            # Coloumb count discharged charge
            self.charge_discharged += charge * -1 if charge < 0 else 0
            self.charge_discharged_last += charge * -1 if charge < 0 else 0

        # get external sensor value
        if self.dbus_external_objects is not None and "Current" in self.dbus_external_objects and self.dbus_external_objects["Current"] is not None:
            current_external = round(self.dbus_external_objects["Current"].get_value(), 3)
            logger.debug(f"current: {self.current} - current_external: {current_external}")
            current = current_external
        else:
            # calculate current only, if lists are different
            if utils.CURRENT_CORRECTION:
                # calculate current from real current
                current = round(
                    utils.calc_linear_relationship(
                        self.current,
                        utils.CURRENT_REPORTED_BY_BMS,
                        utils.CURRENT_MEASURED_BY_USER,
                    ),
                    3,
                )
                # set for debugging
                self.current_corrected = current
            else:
                # use current as it is
                current = self.current

        self.current_calc_last_time = current_time
        return current

    def get_power(self) -> Union[float, None]:
        """
        Calculate the power from the current and voltage.

        :return: The power
        """
        current_time = time()

        # Has to be calculated from last measurement until now
        if self.power_calc is not None and self.power_calc_last_time is not None:
            # Calculate energy based on the power from last measurement until now
            energy = self.power_calc / 3600 * (current_time - self.power_calc_last_time)

            # Coloumb count charged energy
            self.energy_charged += energy if energy > 0 else 0

            # Coloumb count discharged energy
            self.energy_discharged += energy * -1 if energy < 0 else 0

        power = self.voltage * self.current_calc if self.current_calc is not None and self.voltage is not None else None

        self.power_calc_last_time = current_time
        return power

    def get_soc(self) -> Union[float, None]:
        """
        Get the state of charge, either from:
        - the external sensor
        - the calculated value
        - the battery

        :return: The state of charge
        """
        # get external sensor value
        if self.dbus_external_objects is not None and "Soc" in self.dbus_external_objects and self.dbus_external_objects["Soc"] is not None:
            soc_external = round(self.dbus_external_objects["Soc"].get_value(), 3)
            logger.debug(f"soc: {self.soc} - soc_external: {soc_external}")
            return soc_external
        # get calculated value
        elif utils.SOC_CALCULATION:
            return self.soc_calculation()
        # get value from battery
        else:
            return self.soc

    def set_calculated_data(self) -> None:
        """
        Execute all calculations and set the calculated data.

        :return: None
        """
        self.current_calc = self.get_current()
        self.power_calc = self.get_power()
        self.soc_calc = self.get_soc()

    def manage_error_code(self, error_code: int = 8) -> None:
        """
        This method is used to process errors.
        It sets the error code after 180 errors within 3 hours.

        :param error_code: The error code to display
        """
        self.error_timestamps.append(int(time()))

        # only keep last 180 errors
        if len(self.error_timestamps) > 180:
            # remove first element
            self.error_timestamps.pop(0)

        # check if
        #     there are more or equal to 180 errors
        #     the first error in the list is within the last 3 hours
        #     the error code is different from the current error
        if len(self.error_timestamps) >= 180 and int(time()) - self.error_timestamps[0] <= (60 * 60 * 3) and self.error_code != error_code:
            # set error code
            self.error_code = error_code

    def manage_error_code_reset(self) -> None:
        """
        This method is used to reset the error code.
        """
        # check if
        #     there are more or equal to 180 errors
        #     the first error in the list is not within the last 3 hours
        #     the error code is not already None
        if len(self.error_timestamps) >= 180 and int(time()) - self.error_timestamps[0] > (60 * 60 * 3) and self.error_code is not None:
            self.error_code = None

    def log_cell_data(self) -> bool:
        if logger.getEffectiveLevel() > logging.INFO and len(self.cells) == 0:
            return False

        cell_res = ""
        cell_counter = 1
        for c in self.cells:
            cell_res += "[{0}]{1}V ".format(cell_counter, c.voltage)
            cell_counter = cell_counter + 1
        logger.debug("Cells:" + cell_res)
        return True

    def log_settings(self) -> None:
        cell_counter = len(self.cells)
        logger.info(f"Battery {self.type} connected to dbus from {self.port}")
        logger.info("========== Settings ==========")
        logger.info(
            f"> Connection voltage: {self.voltage} V | Current: {self.current_calc} A | SoC: {self.soc}%"
            + (f" | SoC calc: {self.soc_calc:.0f}%" if utils.SOC_CALCULATION else "")
        )
        logger.info(f"> Cell count: {self.cell_count} | Cells populated: {cell_counter}")
        logger.info(f"> LINEAR LIMITATION ENABLE: {utils.LINEAR_LIMITATION_ENABLE}")
        logger.info(
            f"> MIN CELL VOLTAGE: {utils.MIN_CELL_VOLTAGE:.3f} V "
            + f"| MAX CELL VOLTAGE: {utils.MAX_CELL_VOLTAGE:.3f} V"
            + f"| FLOAT CELL VOLTAGE: {utils.FLOAT_CELL_VOLTAGE:.3f} V"
        )
        logger.info(
            f"> MAX BATTERY CHARGE CURRENT: {utils.MAX_BATTERY_CHARGE_CURRENT} A | " + f"MAX BATTERY DISCHARGE CURRENT: {utils.MAX_BATTERY_DISCHARGE_CURRENT} A"
        )
        if (
            (utils.MAX_BATTERY_CHARGE_CURRENT != self.max_battery_charge_current or utils.MAX_BATTERY_DISCHARGE_CURRENT != self.max_battery_discharge_current)
            and self.max_battery_charge_current is not None
            and self.max_battery_discharge_current is not None
        ):
            logger.info(
                f"> MAX BATTERY CHARGE CURRENT: {self.max_battery_charge_current} A | "
                + f"MAX BATTERY DISCHARGE CURRENT: {self.max_battery_discharge_current} A (read from BMS)"
            )
        logger.info(f"> CVCM:     {utils.CVCM_ENABLE}")
        logger.info(f"> CCCM CV:  {str(utils.CCCM_CV_ENABLE).ljust(5)} | DCCM CV:  {utils.DCCM_CV_ENABLE}")
        logger.info(f"> CCCM T:   {str(utils.CCCM_T_ENABLE).ljust(5)} | DCCM T:   {utils.DCCM_T_ENABLE}")
        logger.info(f"> CCCM SOC: {str(utils.CCCM_SOC_ENABLE).ljust(5)} | DCCM SOC: {utils.DCCM_SOC_ENABLE}")
        logger.info(f"> CHARGE FET: {self.charge_fet} | DISCHARGE FET: {self.discharge_fet} | BALANCE FET: {self.balance_fet}")
        logger.info(f"Serial Number/Unique Identifier: {self.unique_identifier()}")

        return

    def reset_soc_callback(self, path: str, value: int) -> bool:
        # callback for handling reset soc request
        return False  # return False to indicate that the callback was not handled

    def force_charging_off_callback(self, path: str, value: int) -> bool:
        return False  # return False to indicate that the callback was not handled

    def force_discharging_off_callback(self, path: str, value: int) -> bool:
        return False  # return False to indicate that the callback was not handled

    def turn_balancing_off_callback(self, path: str, value: int) -> bool:
        return False  # return False to indicate that the callback was not handled

    def trigger_soc_reset(self) -> bool:
        """
        This method can be used to implement SOC reset when the battery is assumed to be full
        """
        return False  # return False to indicate that the callback was not handled

    def history_calculate_values(self) -> None:
        """
        Calculate missing values based on the history data
        """
        if "deepest_discharge" not in self.history.exclude_values_to_calculate and self.get_capacity_consumed() is not None:
            # Has to be negative
            if self.history.deepest_discharge is None or self.history.deepest_discharge > self.get_capacity_consumed():
                self.history.deepest_discharge = self.get_capacity_consumed()

        if "last_discharge" not in self.history.exclude_values_to_calculate:
            # Has to be negative
            if self.history.last_discharge is None:
                self.history.last_discharge = 0
            elif self.current_avg is not None:
                if self.current_avg < 0 and self.previous_current_avg is not None and self.previous_current_avg >= 0:
                    self.charge_discharged_last = 0
                if self.current_avg <= 0:
                    self.history.last_discharge = self.charge_discharged_last

        if "full_discharges" not in self.history.exclude_values_to_calculate:
            if self.history.full_discharges is None:
                self.history.full_discharges = 0
            else:
                if self.soc_calc == 0:
                    self.history.full_discharges += 1
                    self.full_discharge_active = True

                if self.full_discharge_active and self.soc_calc > 15:
                    self.full_discharge_active = False

        if "total_ah_drawn" not in self.history.exclude_values_to_calculate:
            # Has to be negative
            if self.history.total_ah_drawn is None:
                # Check if charge_cycles are already available from BMS
                if self.history.charge_cycles is not None and self.history.charge_cycles > 0 and self.capacity is not None and self.capacity > 0:
                    self.history.total_ah_drawn = self.history.charge_cycles * self.capacity * -1
                else:
                    self.history.total_ah_drawn = 0
            elif self.charge_discharged is not None:
                self.history.total_ah_drawn += self.charge_discharged
                # reset charge_discharged, since it is already added to the history
                self.charge_discharged = 0

        if "charge_cycles" not in self.history.exclude_values_to_calculate:
            if self.history.total_ah_drawn is not None and self.history.total_ah_drawn > 0 and self.capacity is not None and self.capacity > 0:
                self.history.charge_cycles = self.history.total_ah_drawn / self.capacity

        if "average_discharge" not in self.history.exclude_values_to_calculate:
            # Has to be negative
            if self.history.total_ah_drawn is not None and self.history.charge_cycles is not None and self.history.charge_cycles > 0:
                self.history.average_discharge = self.history.total_ah_drawn / self.history.charge_cycles

        if "minimum_voltage" not in self.history.exclude_values_to_calculate:
            if self.history.minimum_voltage is None or self.history.minimum_voltage > self.voltage:
                self.history.minimum_voltage = self.voltage

        if "maximum_voltage" not in self.history.exclude_values_to_calculate:
            if self.history.maximum_voltage is None or self.history.maximum_voltage < self.voltage:
                self.history.maximum_voltage = self.voltage

        if "minimum_cell_voltage" not in self.history.exclude_values_to_calculate and self.get_min_cell_voltage() is not None:
            if self.history.minimum_cell_voltage is None or self.history.minimum_cell_voltage > self.get_min_cell_voltage():
                self.history.minimum_cell_voltage = self.get_min_cell_voltage()

        if "maximum_cell_voltage" not in self.history.exclude_values_to_calculate and self.get_max_cell_voltage() is not None:
            if self.history.maximum_cell_voltage is None or self.history.maximum_cell_voltage < self.get_max_cell_voltage():
                self.history.maximum_cell_voltage = self.get_max_cell_voltage()

        if "low_voltage_alarms" not in self.history.exclude_values_to_calculate:
            if self.history.low_voltage_alarms is None:
                self.history.low_voltage_alarms = 0
            elif (self.protection.low_voltage is not None and self.protection.low_voltage > 0 and self.protection.previous_low_voltage == 0) or (
                self.protection.low_cell_voltage is not None and self.protection.low_cell_voltage > 0 and self.protection.previous_low_cell_voltage == 0
            ):
                self.history.low_voltage_alarms += 1

        if "high_voltage_alarms" not in self.history.exclude_values_to_calculate:
            if self.history.high_voltage_alarms is None:
                self.history.high_voltage_alarms = 0
            elif (self.protection.high_voltage is not None and self.protection.high_voltage > 0 and self.protection.previous_high_voltage == 0) or (
                self.protection.high_cell_voltage is not None and self.protection.high_cell_voltage > 0 and self.protection.previous_high_cell_voltage == 0
            ):
                self.history.high_voltage_alarms += 1

        if "minimum_temperature" not in self.history.exclude_values_to_calculate and self.get_min_temperature() is not None:
            if self.history.minimum_temperature is None or self.history.minimum_temperature > self.get_min_temperature():
                self.history.minimum_temperature = self.get_min_temperature()

        if "maximum_temperature" not in self.history.exclude_values_to_calculate and self.get_max_temperature() is not None:
            if self.history.maximum_temperature is None or self.history.maximum_temperature < self.get_max_temperature():
                self.history.maximum_temperature = self.get_max_temperature()

        if "discharged_energy" not in self.history.exclude_values_to_calculate:
            if self.history.discharged_energy is None:
                self.history.discharged_energy = (
                    utils.FLOAT_CELL_VOLTAGE * self.cell_count * self.capacity * self.history.charge_cycles / 1000
                    if self.history.charge_cycles is not None
                    else 0
                )
            elif self.energy_discharged is not None:
                self.history.discharged_energy += self.energy_discharged / 1000
                # reset energy_discharged, since it is already added to the history
                self.energy_discharged = 0

        if "charged_energy" not in self.history.exclude_values_to_calculate:
            if self.history.charged_energy is None:
                self.history.charged_energy = (
                    utils.FLOAT_CELL_VOLTAGE * self.cell_count * self.capacity * self.history.charge_cycles / 1000
                    if self.history.charge_cycles is not None
                    else 0
                )
            elif self.energy_charged is not None:
                self.history.charged_energy += self.energy_charged / 1000
                # reset energy_charged, since it is already added to the history
                self.energy_charged = 0

    def history_reset_callback(self, path: str, value: int) -> bool:
        """
        Callback to reset the history values.

        :param path: the path
        :param value: the value
        :return: True if successful
        """
        reset_mappings = {
            # Reset all history values
            1: [],
            # Reset capacity history values
            2: ["deepest_discharge", "last_discharge", "charge_cycles", "full_discharges", "total_ah_drawn"],
            # Reset voltage history values
            3: ["minimum_voltage", "maximum_voltage", "minimum_cell_voltage", "maximum_cell_voltage"],
            # Reset time history values
            4: ["timestamp_last_full_charge"],
            # Reset alarm history values
            5: ["low_voltage_alarms", "high_voltage_alarms"],
            # Reset temperature history values
            6: ["minimum_temperature", "maximum_temperature"],
            # Reset energy history values
            7: ["charged_energy", "discharged_energy"],
        }

        if value in reset_mappings:
            self.history.reset_values(reset_mappings[value])

        self.history.clear = 0

        if utils.HISTORY_ENABLE:
            self.history_calculate_values()

        return True
