# -*- coding: utf-8 -*-
import sys
import os
import platform
import dbus
import traceback
from time import sleep, time
from utils import logger, publish_config_variables
import utils
from xml.etree import ElementTree
import requests
import threading
import json

# add path to velib_python
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "ext", "velib_python"))
from vedbus import VeDbusService  # noqa: E402
from ve_utils import get_vrm_portal_id  # noqa: E402
from settingsdevice import SettingsDevice  # noqa: E402


class SystemBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SYSTEM)


class SessionBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SESSION)


def get_bus() -> dbus.bus.BusConnection:
    return SessionBus() if "DBUS_SESSION_BUS_ADDRESS" in os.environ else SystemBus()


class DbusHelper:
    """
    This class is used to handle all the dbus communication.
    """

    EMPTY_DICT = {}

    def __init__(self, battery, bms_address=None):
        self.battery = battery
        self.instance = 1
        self.settings = None
        self.error = {"count": 0, "timestamp_first": None, "timestamp_last": None}
        self.cell_voltages_good = None
        self._dbusname = (
            "com.victronenergy.battery."
            + self.battery.port[self.battery.port.rfind("/") + 1 :]
            + ("__" + str(bms_address) if bms_address is not None and bms_address != 0 else "")
        )
        self._dbusservice = VeDbusService(self._dbusname, get_bus(), register=False)
        self.bms_id = "".join(
            # remove all non alphanumeric characters except underscore from the identifier
            c if c.isalnum() else "_"
            for c in self.battery.unique_identifier()
        )
        self.path_battery = None
        self.save_charge_details_last = {
            "allow_max_voltage": self.battery.allow_max_voltage,
            "max_voltage_start_time": self.battery.max_voltage_start_time,
            "soc_calc": (self.battery.soc_calc if self.battery.soc_calc is not None else ""),
            "soc_reset_last_reached": self.battery.soc_reset_last_reached,
            "history_values": "",
        }
        self.history_calculated_last_time: int = 0
        """
        Last time the history values were calculated.
        """
        self.telemetry_upload_error_count: int = 0
        self.telemetry_upload_interval: int = 60 * 60 * 24 * 7  # 1 week
        self.telemetry_upload_last: int = 0
        self.telemetry_upload_running: bool = False

    def create_pid_file(self) -> bool:
        """
        Create a pid file for the driver with the device instance as file name suffix.
        Keep the file locked for the entire script runtime, to prevent another instance from running with
        the same device instance. This is achieved by maintaining a reference to the "pid_file" object for
        the entire script runtime storing "pid_file" as an instance variable "self.pid_file".

        :return: True if the pid file was created successfully, False if the file is already locked.
        """
        # only used for this function
        import fcntl

        # path to the PID file
        pid_file_path = f"/var/tmp/dbus-serialbattery_{self.instance}.pid"

        try:
            # open file in append mode to not flush content, if the file is locked
            self.pid_file = open(pid_file_path, "a")

            # try to lock the file
            fcntl.flock(self.pid_file, fcntl.LOCK_EX | fcntl.LOCK_NB)

        # fail, if the file is already locked
        except OSError:
            logger.error(
                "** DRIVER STOPPED! Another battery with the same serial number/unique identifier " + f'"{self.battery.unique_identifier()}" found! **'
            )
            logger.error("Please check that the batteries have unique identifiers.")

            if "Ah" in self.battery.unique_identifier():
                logger.error("Change the battery capacities to be unique.")
                logger.error("Example for batteries with 280 Ah:")
                logger.error("- Battery 1: 279 Ah")
                logger.error("- Battery 2: 280 Ah")
                logger.error("- Battery 3: 281 Ah")
                logger.error("This little difference does not matter for the battery.")
            else:
                logger.error("Change the customizable field in your BMS settings to be unique.")
            logger.error("To see which battery already uses this serial number/unique identifier check " + f'this file "{pid_file_path}"')
            logger.error("")
            logger.error("If you can't change any data in your BMS then set USE_PORT_AS_UNIQUE_ID = True in the config.ini file.")

            self.pid_file.close()
            sleep(60)
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

        # Seek to the beginning of the file
        self.pid_file.seek(0)
        # Truncate the file to 0 bytes
        self.pid_file.truncate()
        # Write content to file
        self.pid_file.write(f"{self._dbusname}:{os.getpid()}\n")
        # Flush the file buffer
        self.pid_file.flush()

        # Ensure the changes are written to the disk
        # os.fsync(self.pid_file.fileno())

        logger.debug(f"PID file created successfully: {pid_file_path}")

        return True

    def setup_instance(self) -> bool:
        """
        Sets up the instance of the battery by checking if it was already connected once.
        If the battery was already connected, it retrieves the instance from the dbus settings and
        updates the last seen time.
        If the battery was not connected before, it creates the settings and sets the instance to the
        next available one.

        :return: True if the instance was set up successfully, False if the instance could not be set up.
        """

        # bms_id = self.battery.production if self.battery.production is not None else \
        #     self.battery.port[self.battery.port.rfind('/') + 1:]
        # bms_id = self.battery.port[self.battery.port.rfind("/") + 1 :]
        logger.debug("setup_instance(): start")

        custom_name = self.battery.custom_name()
        device_instance = "1"
        device_instances_used = []
        found_bms = False
        self.path_battery = "/Settings/Devices/serialbattery" + "_" + str(self.bms_id)

        # prepare settings class
        self.settings = SettingsDevice(get_bus(), self.EMPTY_DICT, self.handle_changed_setting)
        logger.debug("setup_instance(): SettingsDevice")

        # get all the settings from the dbus
        settings_from_dbus = self.get_settings_with_values(
            get_bus(),
            "com.victronenergy.settings",
            "/Settings/Devices",
        )
        logger.debug("setup_instance(): get_settings_with_values")
        # output:
        # {
        #     "Settings": {
        #         "Devices": {
        #             "serialbattery_JK_B2A20S20P": {
        #                 "AllowMaxVoltage",
        #                 "ClassAndVrmInstance": "battery:3",
        #                 "CustomName": "My Battery 1",
        #                 "LastSeen": "1700926114",
        #                 "MaxVoltageStartTime": "",
        #                 "SocResetLastReached": 0,
        #                 "UniqueIdentifier": "JK_B2A20S20P",
        #             },
        #             "serialbattery_JK_B2A20S25P": {
        #                 "AllowMaxVoltage",
        #                 "ClassAndVrmInstance": "battery:4",
        #                 "CustomName": "My Battery 2",
        #                 "LastSeen": "1700926114",
        #                 "MaxVoltageStartTime": "",
        #                 "SocResetLastReached": 0,
        #                 "UniqueIdentifier": "JK_B2A20S25P",
        #             },
        #             "serialbattery_ttyUSB0": {
        #                 "ClassAndVrmInstance": "battery:1",
        #             },
        #             "serialbattery_ttyUSB1": {
        #                 "ClassAndVrmInstance": "battery:2",
        #             },
        #             "vegps_ttyUSB0": {
        #                 "ClassAndVrmInstance": "gps:0"
        #             },
        #         }
        #     }
        # }

        # loop through devices in dbus settings
        if "Settings" in settings_from_dbus and "Devices" in settings_from_dbus["Settings"]:
            for key, value in settings_from_dbus["Settings"]["Devices"].items():
                # check if it's a serialbattery
                if "serialbattery" in key:
                    # check used device instances
                    if "ClassAndVrmInstance" in value:
                        device_instances_used.append(value["ClassAndVrmInstance"][value["ClassAndVrmInstance"].rfind(":") + 1 :])

                    # check the unique identifier, if the battery was already connected once
                    # if so, get the last saved data
                    if "UniqueIdentifier" in value and value["UniqueIdentifier"] == self.bms_id:
                        # set found_bms to true
                        found_bms = True

                        # check if the battery has ClassAndVrmInstance set
                        if "ClassAndVrmInstance" in value and value["ClassAndVrmInstance"] != "":
                            # get the instance from the object name
                            device_instance = int(value["ClassAndVrmInstance"][value["ClassAndVrmInstance"].rfind(":") + 1 :])
                            logger.info(f"Reconnected to previously identified battery with DeviceInstance: {device_instance}")

                        # check if the battery has AllowMaxVoltage set
                        if "AllowMaxVoltage" in value and value["AllowMaxVoltage"] != "":

                            try:
                                self.battery.allow_max_voltage = True if int(value["AllowMaxVoltage"]) == 1 else False
                                logger.debug(f"AllowMaxVoltage read from dbus: {self.battery.allow_max_voltage}")
                            except Exception:
                                # set error code, to show in the GUI that something is wrong
                                self.battery.manage_error_code(8)

                                logger.error("AllowMaxVoltage could not be converted to type int: " + str(value["AllowMaxVoltage"]))

                        # check if the battery has CustomName set
                        if "CustomName" in value and value["CustomName"] != "":
                            custom_name = value["CustomName"]

                        # check if the battery has MaxVoltageStartTime set
                        if "MaxVoltageStartTime" in value and value["MaxVoltageStartTime"] != "":
                            try:
                                self.battery.max_voltage_start_time = int(value["MaxVoltageStartTime"])
                                logger.debug(f"MaxVoltageStartTime read from dbus: {self.battery.max_voltage_start_time}")
                            except Exception:
                                # set error code, to show in the GUI that something is wrong
                                self.battery.manage_error_code(8)

                                logger.error("MaxVoltageStartTime could not be converted to type int: " + str(value["MaxVoltageStartTime"]))

                        # check if the battery has SocCalc set
                        # load SOC from dbus only if SOC_CALCULATION is enabled
                        if utils.SOC_CALCULATION:
                            if "SocCalc" in value:
                                try:
                                    self.battery.soc_calc = float(value["SocCalc"])
                                    logger.debug(f"Soc_calc read from dbus: {self.battery.soc_calc}")
                                except Exception:
                                    # set error code, to show in the GUI that something is wrong
                                    self.battery.manage_error_code(8)

                                    logger.error("SocCalc could not be converted to type float: " + str(value["SocCalc"]))
                            else:
                                logger.debug("Soc_calc not found in dbus")

                        # check if the battery has SocResetLastReached set
                        if "SocResetLastReached" in value and value["SocResetLastReached"] != "":
                            try:
                                self.battery.soc_reset_last_reached = int(value["SocResetLastReached"])
                                logger.debug(f"SocResetLastReached read from dbus: {self.battery.soc_reset_last_reached}")
                            except Exception:
                                # set error code, to show in the GUI that something is wrong
                                self.battery.manage_error_code(8)

                                logger.error("SocResetLastReached could not be converted to type int: " + str(value["SocResetLastReached"]))

                        # check if the battery has HistoryValues set
                        if "HistoryValues" in value and value["HistoryValues"] != "":
                            try:
                                history_values = json.loads(value["HistoryValues"])
                                logger.debug(f"HistoryValues read from dbus: {history_values}")
                                for key in history_values:
                                    setattr(self.battery.history, key, float(history_values[key]))
                                    # Restore value after driver restart
                                    if key == "last_discharge":
                                        self.battery.charge_discharged_last = float(history_values[key])

                            except Exception:
                                # set error code, to show in the GUI that something is wrong
                                self.battery.manage_error_code(8)

                                logger.error("HistoryValues could not be converted from json: " + str(value["HistoryValues"]))

                    # check the last seen time and remove the battery it it was not seen for 30 days
                    elif "LastSeen" in value and int(value["LastSeen"]) < int(time()) - (60 * 60 * 24 * 30):
                        # remove entry
                        del_return = self.remove_settings(
                            get_bus(),
                            "com.victronenergy.settings",
                            "/Settings/Devices/" + key,
                            [
                                "AllowMaxVoltage",
                                "ClassAndVrmInstance",
                                "CustomName",
                                "LastSeen",
                                "MaxVoltageStartTime",
                                "SocCalc",
                                "SocResetLastReached",
                                "HistoryValues",
                                "UniqueIdentifier",
                            ],
                        )
                        logger.info(f"Remove /Settings/Devices/{key} from dbus. Delete result: {del_return}")

                    # check if the battery has a last seen time, if not then it's an old entry and can be removed
                    elif "LastSeen" not in value:
                        del_return = self.remove_settings(
                            get_bus(),
                            "com.victronenergy.settings",
                            "/Settings/Devices/" + key,
                            ["ClassAndVrmInstance"],
                        )
                        logger.info(f"Remove /Settings/Devices/{key} from dbus. " + f"Old entry. Delete result: {del_return}")

                if "ruuvi" in key:
                    # check if Ruuvi tag is enabled, if not remove entry.
                    if "Enabled" in value and value["Enabled"] == "0" and "ClassAndVrmInstance" not in value:
                        del_return = self.remove_settings(
                            get_bus(),
                            "com.victronenergy.settings",
                            "/Settings/Devices/" + key,
                            ["CustomName", "Enabled", "TemperatureType"],
                        )
                        logger.info(
                            f"Remove /Settings/Devices/{key} from dbus. "
                            + f"Ruuvi tag was disabled and had no ClassAndVrmInstance. Delete result: {del_return}"
                        )

        logger.debug("setup_instance(): for loop ended")

        # create class and crm instance
        class_and_vrm_instance = "battery:" + str(device_instance)

        # preare settings and write them to com.victronenergy.settings
        settings = {
            "AllowMaxVoltage": [
                self.path_battery + "/AllowMaxVoltage",
                1 if self.battery.allow_max_voltage else 0,
                0,
                0,
            ],
            "ClassAndVrmInstance": [
                self.path_battery + "/ClassAndVrmInstance",
                class_and_vrm_instance,
                0,
                0,
            ],
            "CustomName": [
                self.path_battery + "/CustomName",
                custom_name,
                0,
                0,
            ],
            "LastSeen": [
                self.path_battery + "/LastSeen",
                int(time()),
                0,
                0,
            ],
            "MaxVoltageStartTime": [
                self.path_battery + "/MaxVoltageStartTime",
                (self.battery.max_voltage_start_time if self.battery.max_voltage_start_time is not None else ""),
                0,
                0,
            ],
            "SocCalc": [
                self.path_battery + "/SocCalc",
                (self.battery.soc_calc if self.battery.soc_calc is not None else ""),
                0,
                0,
            ],
            "SocResetLastReached": [
                self.path_battery + "/SocResetLastReached",
                self.battery.soc_reset_last_reached,
                0,
                0,
            ],
            "HistoryValues": [
                self.path_battery + "/HistoryValues",
                "",
                0,
                0,
            ],
            "UniqueIdentifier": [
                self.path_battery + "/UniqueIdentifier",
                self.bms_id,
                0,
                0,
            ],
        }

        # update last seen
        if found_bms:
            self.set_settings(
                get_bus(),
                "com.victronenergy.settings",
                self.path_battery,
                "LastSeen",
                int(time()),
            )

        self.settings.addSettings(settings)
        self.battery.role, self.instance = self.get_role_instance()
        logger.info(f"Use DeviceInstance: {self.instance}")

        logger.debug(f"Found DeviceInstances: {device_instances_used}")

        # create pid file
        if not self.create_pid_file():
            return False

        return True

    def get_role_instance(self) -> tuple:
        """
        Get the role and instance from the settings.

        :return: Tuple with role and instance.
        """
        val = self.settings["ClassAndVrmInstance"].split(":")
        logger.debug(f"Use DeviceInstance: {int(val[1])}")
        return val[0], int(val[1])

    def handle_changed_setting(self, setting, oldvalue, newvalue) -> None:
        """
        Handle the changed settings from dbus.

        :param setting: The setting that was changed.
        :param oldvalue: The old value of the setting.
        :param newvalue: The new value of the setting.
        """
        if setting == "ClassAndVrmInstance":
            old_instance = self.instance
            self.battery.role, self.instance = self.get_role_instance()
            if old_instance != self.instance:
                logger.info(f"Changed to DeviceInstance: {self.instance}")
            return
        if setting == "CustomName":
            if oldvalue != newvalue:
                logger.info(f"Changed to CustomName: {newvalue}")
            return

    # this function is called when the battery is initiated
    def setup_vedbus(self) -> bool:
        """
        Set up dbus service and device instance and notify of all the attributes we intend to update.
        This is only called once when a battery is initiated.

        :return: True if the setup was successful, False if the setup failed.
        """
        if not self.setup_instance():
            return False

        logger.info(f"Use dbus ServiceName: {self._dbusname}")

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path("/Mgmt/ProcessName", __file__)
        self._dbusservice.add_path("/Mgmt/ProcessVersion", "Python " + platform.python_version())
        self._dbusservice.add_path("/Mgmt/Connection", self.battery.connection_name())

        # Create the mandatory objects
        self._dbusservice.add_path("/DeviceInstance", self.instance)
        # this product ID was reserved by Victron Energy for the dbus-serialbattery driver
        self._dbusservice.add_path("/ProductId", 0xBA77)
        self._dbusservice.add_path("/ProductName", self.battery.product_name())
        self._dbusservice.add_path("/FirmwareVersion", str(utils.DRIVER_VERSION))
        self._dbusservice.add_path("/HardwareVersion", self.battery.hardware_version)
        self._dbusservice.add_path("/Connected", 1)
        self._dbusservice.add_path(
            "/CustomName",
            self.settings["CustomName"],
            writeable=True,
            onchangecallback=self.custom_name_callback,
        )
        self._dbusservice.add_path("/Serial", self.bms_id, writeable=True)
        self._dbusservice.add_path("/DeviceName", self.battery.custom_field, writeable=True)

        self._dbusservice.add_path("/Manufacturer", self.battery.type)
        self._dbusservice.add_path("/Family", self.battery.hardware_version)

        self._dbusservice.add_path("/State", self.battery.state, writeable=True)
        self._dbusservice.add_path("/ErrorCode", self.battery.error_code, writeable=True)
        self._dbusservice.add_path("/ConnectionInformation", "")

        # Create static battery info
        self._dbusservice.add_path(
            "/Info/BatteryLowVoltage",
            self.battery.min_battery_voltage,
            writeable=True,
        )
        self._dbusservice.add_path(
            "/Info/MaxChargeVoltage",
            self.battery.max_battery_voltage,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.2f}V".format(v),
        )
        self._dbusservice.add_path(
            "/Info/MaxChargeCurrent",
            self.battery.max_battery_charge_current,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.2f}A".format(v),
        )
        self._dbusservice.add_path(
            "/Info/MaxDischargeCurrent",
            self.battery.max_battery_discharge_current,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.2f}A".format(v),
        )

        self._dbusservice.add_path("/Info/ChargeMode", None, writeable=True)
        self._dbusservice.add_path("/Info/ChargeModeDebug", None, writeable=True)
        self._dbusservice.add_path("/Info/ChargeModeDebugFloat", None, writeable=True)
        self._dbusservice.add_path("/Info/ChargeModeDebugBulk", None, writeable=True)
        self._dbusservice.add_path("/Info/ChargeLimitation", None, writeable=True)
        self._dbusservice.add_path("/Info/DischargeLimitation", None, writeable=True)

        self._dbusservice.add_path("/System/NrOfCellsPerBattery", self.battery.cell_count, writeable=True)
        self._dbusservice.add_path("/System/NrOfModulesOnline", 1, writeable=True)
        self._dbusservice.add_path("/System/NrOfModulesOffline", 0, writeable=True)
        self._dbusservice.add_path("/System/NrOfModulesBlockingCharge", None, writeable=True)
        self._dbusservice.add_path("/System/NrOfModulesBlockingDischarge", None, writeable=True)
        self._dbusservice.add_path(
            "/Capacity",
            self.battery.get_capacity_remain(),
            writeable=True,
            gettextcallback=lambda p, v: "{:0.2f}Ah".format(v),
        )
        self._dbusservice.add_path(
            "/InstalledCapacity",
            self.battery.capacity,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.0f}Ah".format(v),
        )
        self._dbusservice.add_path(
            "/ConsumedAmphours",
            None,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.0f}Ah".format(v),
        )

        # Create SOC, DC and System items
        self._dbusservice.add_path("/Soc", None, writeable=True)
        # add original SOC for comparing
        if utils.SOC_CALCULATION or utils.EXTERNAL_SENSOR_DBUS_PATH_SOC is not None:
            self._dbusservice.add_path("/SocBms", None, writeable=True)

        self._dbusservice.add_path(
            "/Dc/0/Voltage",
            None,
            writeable=True,
            gettextcallback=lambda p, v: "{:2.2f}V".format(v),
        )
        self._dbusservice.add_path(
            "/Dc/0/Current",
            None,
            writeable=True,
            gettextcallback=lambda p, v: "{:2.2f}A".format(v),
        )
        self._dbusservice.add_path(
            "/Dc/0/Power",
            None,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.0f}W".format(v),
        )
        self._dbusservice.add_path("/Dc/0/Temperature", None, writeable=True)
        self._dbusservice.add_path(
            "/Dc/0/MidVoltage",
            None,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.2f}V".format(v),
        )
        self._dbusservice.add_path(
            "/Dc/0/MidVoltageDeviation",
            None,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.1f}%".format(v),
        )

        # Create battery extras
        self._dbusservice.add_path("/System/MinCellTemperature", None, writeable=True)
        self._dbusservice.add_path("/System/MinTemperatureCellId", None, writeable=True)
        self._dbusservice.add_path("/System/MaxCellTemperature", None, writeable=True)
        self._dbusservice.add_path("/System/MaxTemperatureCellId", None, writeable=True)
        self._dbusservice.add_path("/System/MOSTemperature", None, writeable=True)
        self._dbusservice.add_path("/System/Temperature1", None, writeable=True)
        self._dbusservice.add_path("/System/Temperature1Name", None, writeable=True)
        self._dbusservice.add_path("/System/Temperature2", None, writeable=True)
        self._dbusservice.add_path("/System/Temperature2Name", None, writeable=True)
        self._dbusservice.add_path("/System/Temperature3", None, writeable=True)
        self._dbusservice.add_path("/System/Temperature3Name", None, writeable=True)
        self._dbusservice.add_path("/System/Temperature4", None, writeable=True)
        self._dbusservice.add_path("/System/Temperature4Name", None, writeable=True)
        self._dbusservice.add_path(
            "/System/MaxCellVoltage",
            None,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.3f}V".format(v),
        )
        self._dbusservice.add_path("/System/MaxVoltageCellId", None, writeable=True)
        self._dbusservice.add_path(
            "/System/MinCellVoltage",
            None,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.3f}V".format(v),
        )
        self._dbusservice.add_path("/System/MinVoltageCellId", None, writeable=True)

        self._dbusservice.add_path("/History/DeepestDischarge", None, writeable=True)
        self._dbusservice.add_path("/History/LastDischarge", None, writeable=True)
        self._dbusservice.add_path("/History/AverageDischarge", None, writeable=True)
        self._dbusservice.add_path("/History/ChargeCycles", None, writeable=True)
        self._dbusservice.add_path("/History/FullDischarges", None, writeable=True)
        self._dbusservice.add_path("/History/TotalAhDrawn", None, writeable=True)
        self._dbusservice.add_path("/History/MinimumVoltage", None, writeable=True)
        self._dbusservice.add_path("/History/MaximumVoltage", None, writeable=True)
        self._dbusservice.add_path("/History/MinimumCellVoltage", None, writeable=True)
        self._dbusservice.add_path("/History/MaximumCellVoltage", None, writeable=True)
        self._dbusservice.add_path("/History/TimeSinceLastFullCharge", None, writeable=True)
        self._dbusservice.add_path("/History/LowVoltageAlarms", None, writeable=True)
        self._dbusservice.add_path("/History/HighVoltageAlarms", None, writeable=True)
        self._dbusservice.add_path("/History/MinimumTemperature", None, writeable=True)
        self._dbusservice.add_path("/History/MaximumTemperature", None, writeable=True)
        self._dbusservice.add_path("/History/DischargedEnergy", None, writeable=True)
        self._dbusservice.add_path("/History/ChargedEnergy", None, writeable=True)
        self._dbusservice.add_path("/History/Clear", self.battery.history.clear, writeable=True, onchangecallback=self.battery.history_reset_callback)
        self._dbusservice.add_path("/History/CanBeCleared", 1, writeable=True)

        self._dbusservice.add_path("/Balancing", None, writeable=True)
        self._dbusservice.add_path("/Io/AllowToCharge", 0, writeable=True)
        self._dbusservice.add_path("/Io/AllowToDischarge", 0, writeable=True)
        self._dbusservice.add_path("/Io/AllowToBalance", 0, writeable=True)
        self._dbusservice.add_path(
            "/Io/ForceChargingOff",
            (0 if "force_charging_off_callback" in self.battery.available_callbacks else None),
            writeable=True,
            onchangecallback=self.battery.force_charging_off_callback,
        )
        self._dbusservice.add_path(
            "/Io/ForceDischargingOff",
            (0 if "force_discharging_off_callback" in self.battery.available_callbacks else None),
            writeable=True,
            onchangecallback=self.battery.force_discharging_off_callback,
        )
        self._dbusservice.add_path(
            "/Io/TurnBalancingOff",
            (0 if "turn_balancing_off_callback" in self.battery.available_callbacks else None),
            writeable=True,
            onchangecallback=self.battery.turn_balancing_off_callback,
        )
        # self._dbusservice.add_path('/SystemSwitch', 1, writeable=True)

        # Create the alarms
        self._dbusservice.add_path("/Alarms/LowVoltage", None, writeable=True)
        self._dbusservice.add_path("/Alarms/HighVoltage", None, writeable=True)
        self._dbusservice.add_path("/Alarms/LowCellVoltage", None, writeable=True)
        self._dbusservice.add_path("/Alarms/HighCellVoltage", None, writeable=True)
        self._dbusservice.add_path("/Alarms/LowSoc", None, writeable=True)
        self._dbusservice.add_path("/Alarms/StateOfHealth", None, writeable=True)
        self._dbusservice.add_path("/Alarms/HighChargeCurrent", None, writeable=True)
        self._dbusservice.add_path("/Alarms/HighDischargeCurrent", None, writeable=True)
        self._dbusservice.add_path("/Alarms/CellImbalance", None, writeable=True)
        self._dbusservice.add_path("/Alarms/InternalFailure", None, writeable=True)
        self._dbusservice.add_path("/Alarms/HighChargeTemperature", None, writeable=True)
        self._dbusservice.add_path("/Alarms/LowChargeTemperature", None, writeable=True)
        self._dbusservice.add_path("/Alarms/HighTemperature", None, writeable=True)
        self._dbusservice.add_path("/Alarms/LowTemperature", None, writeable=True)
        self._dbusservice.add_path("/Alarms/BmsCable", None, writeable=True)
        self._dbusservice.add_path("/Alarms/HighInternalTemperature", None, writeable=True)
        self._dbusservice.add_path("/Alarms/FuseBlown", None, writeable=True)

        # cell voltages
        if utils.BATTERY_CELL_DATA_FORMAT > 0:
            for i in range(1, self.battery.cell_count + 1):
                cellpath = "/Cell/%s/Volts" if (utils.BATTERY_CELL_DATA_FORMAT & 2) else "/Voltages/Cell%s"
                self._dbusservice.add_path(
                    cellpath % (str(i)),
                    None,
                    writeable=True,
                    gettextcallback=lambda p, v: "{:0.3f}V".format(v),
                )
                if utils.BATTERY_CELL_DATA_FORMAT & 1:
                    self._dbusservice.add_path("/Balances/Cell%s" % (str(i)), None, writeable=True)
            pathbase = "Cell" if (utils.BATTERY_CELL_DATA_FORMAT & 2) else "Voltages"
            self._dbusservice.add_path(
                "/%s/Sum" % pathbase,
                None,
                writeable=True,
                gettextcallback=lambda p, v: "{:2.2f}V".format(v),
            )
            self._dbusservice.add_path(
                "/%s/Diff" % pathbase,
                None,
                writeable=True,
                gettextcallback=lambda p, v: "{:0.3f}V".format(v),
            )

        self._dbusservice.add_path("/TimeToGo", None, writeable=True)
        self._dbusservice.add_path(
            "/CurrentAvg",
            None,
            writeable=True,
            gettextcallback=lambda p, v: "{:0.2f}A".format(v),
        )

        # Create TimeToSoC items only if enabled, battery capacity is set and points are available
        if utils.TIME_TO_GO_ENABLE and self.battery.capacity is not None and len(utils.TIME_TO_SOC_POINTS) > 0:
            for num in utils.TIME_TO_SOC_POINTS:
                self._dbusservice.add_path("/TimeToSoC/" + str(num), None, writeable=True)

        logger.debug(f"Publish config values: {utils.PUBLISH_CONFIG_VALUES}")
        if utils.PUBLISH_CONFIG_VALUES:
            publish_config_variables(self._dbusservice)

        self._dbusservice.add_path("/Settings/HasTemperature", 1, writeable=True)

        if self.battery.has_settings:
            self._dbusservice.add_path("/Settings/HasSettings", 1, writeable=False)
            self._dbusservice.add_path(
                "/Settings/ResetSoc",
                0,
                writeable=True,
                onchangecallback=self.battery.reset_soc_callback,
            )

        self._dbusservice.add_path("/JsonData", None, writeable=False)

        # register VeDbusService after all paths where added
        # https://github.com/victronenergy/velib_python/commit/494f9aef38f46d6cfcddd8b1242336a0a3a79563
        # https://github.com/victronenergy/velib_python/commit/88a183d099ea5c60139e4d7494f9044e2dedd2d4
        self._dbusservice.register()

        return True

    def publish_battery(self, loop) -> None:
        """
        Publishes the battery data to dbus.
        This is called every battery.poll_interval milli second as set up per battery type to read and update the data

        :param loop: The main loop of the driver.
        """
        try:
            # Call the battery's refresh_data function
            result = self.battery.refresh_data()

            # Check if external sensor is still connected
            if utils.EXTERNAL_SENSOR_DBUS_DEVICE is not None and (
                utils.EXTERNAL_SENSOR_DBUS_PATH_CURRENT is not None or utils.EXTERNAL_SENSOR_DBUS_PATH_SOC is not None
            ):
                # Check if external sensor was and is still connected
                if self.battery.dbus_external_objects is not None and utils.EXTERNAL_SENSOR_DBUS_DEVICE not in get_bus().list_names():
                    logger.error("External current sensor was disconnected, falling back to internal sensor")
                    self.battery.dbus_external_objects = None

                # Check if external current sensor was not connected and is now connected
                elif self.battery.dbus_external_objects is None and utils.EXTERNAL_SENSOR_DBUS_DEVICE in get_bus().list_names():
                    logger.info("External current sensor was connected, switching to external sensor")
                    self.battery.setup_external_sensor()

            # Calculate the values for the battery
            self.battery.set_calculated_data()

            if result:
                # reset error variables
                self.error["count"] = 0
                self.battery.online = True
                self.battery.connection_info = "Connected"

                # unblock charge/discharge, if it was blocked when battery went offline
                if utils.BLOCK_ON_DISCONNECT:
                    self.battery.block_because_disconnect = False

                # reset cell voltages good
                if self.cell_voltages_good is not None:
                    self.cell_voltages_good = None

            else:
                # update error variables
                if self.error["count"] == 0:
                    self.error["timestamp_first"] = int(time())

                self.error["timestamp_last"] = int(time())
                self.error["count"] += 1

                time_since_first_error = self.error["timestamp_last"] - self.error["timestamp_first"]

                # if the battery did not update in 10 second, it's assumed to be offline
                if time_since_first_error >= 10:

                    if self.battery.online:
                        # set battery offline
                        self.battery.online = False

                        # reset the battery values
                        self.battery.init_values()
                        logger.error(">>> ERROR: Battery does not respond, init/reset values <<<")

                        # block charge/discharge
                        if utils.BLOCK_ON_DISCONNECT:
                            self.battery.block_because_disconnect = True

                # check if the cell voltages are good to go for some minutes
                if self.cell_voltages_good is None:
                    self.cell_voltages_good = (
                        True
                        if self.battery.get_min_cell_voltage() > utils.BLOCK_ON_DISCONNECT_VOLTAGE_MIN
                        and self.battery.get_max_cell_voltage() < utils.BLOCK_ON_DISCONNECT_VOLTAGE_MAX
                        else False
                    )
                    logger.info(
                        f"cell_voltages_good: {self.cell_voltages_good} - "
                        + f"min: {self.battery.get_min_cell_voltage()} > {utils.BLOCK_ON_DISCONNECT_VOLTAGE_MIN} - "
                        + f"max: {self.battery.get_max_cell_voltage()} < {utils.BLOCK_ON_DISCONNECT_VOLTAGE_MAX}"
                    )

                # set connection info
                self.battery.connection_info = (
                    f"Connection lost since {time_since_first_error} s, "
                    + "disconnect at "
                    + f"{(60 * utils.BLOCK_ON_DISCONNECT_TIMEOUT_MINUTES if self.cell_voltages_good else 60):.0f} s"
                )

                # if the battery did not update in 60 second, it's assumed to be completely failed
                if time_since_first_error >= 60 and (utils.BLOCK_ON_DISCONNECT or not self.cell_voltages_good):
                    loop.quit()

                # if the cells are between 3.2 and 3.3 volt we can continue for some time
                if time_since_first_error >= 60 * utils.BLOCK_ON_DISCONNECT_TIMEOUT_MINUTES and not utils.BLOCK_ON_DISCONNECT:
                    loop.quit()

            # This is to manage CVCL
            self.battery.manage_charge_voltage()

            # This is to manage CCL\DCL
            self.battery.manage_charge_and_discharge_current()

            # Manage battery error code reset
            # Check if the error code should be reset every hour
            if self.battery.error_code_last_reset_check < int(time()) - 3600:
                # Check if the error code should be reset
                self.battery.manage_error_code_reset()
                # Update the last check time
                self.battery.error_code_last_reset_check = int(time())

            # Manage battery state, if not set to error (10)
            # change state from initializing to running, if there is no error
            if self.battery.state == 0:
                self.battery.state = 9

            # change state from running to standby, if charging and discharging is not allowed
            if self.battery.state == 9 and not self.battery.get_allow_to_charge() and not self.battery.get_allow_to_discharge():
                self.battery.state = 14

            # change state from standby to running, if charging or discharging is allowed
            if self.battery.state == 14 and (self.battery.get_allow_to_charge() or self.battery.get_allow_to_discharge()):
                self.battery.state = 9

            # publish all the data from the battery object to dbus
            self.publish_dbus()

            # upload telemetry data
            self.telemetry_upload()

        except Exception:
            traceback.print_exc()
            loop.quit()

    def publish_dbus(self) -> None:
        """
        Publishes the battery data to dbus and refresh it.
        """
        self._dbusservice["/System/NrOfCellsPerBattery"] = self.battery.cell_count
        if utils.SOC_CALCULATION or utils.EXTERNAL_SENSOR_DBUS_PATH_SOC is not None:
            self._dbusservice["/Soc"] = round(self.battery.soc_calc, 2) if self.battery.soc_calc is not None else None
            # add original SOC for comparing
            self._dbusservice["/SocBms"] = round(self.battery.soc, 2) if self.battery.soc is not None else None
        else:
            self._dbusservice["/Soc"] = round(self.battery.soc_calc, 2) if self.battery.soc is not None else None
        self._dbusservice["/Dc/0/Voltage"] = round(self.battery.voltage, 2) if self.battery.voltage is not None else None
        self._dbusservice["/Dc/0/Current"] = round(self.battery.current_calc, 2) if self.battery.current_calc is not None else None
        self._dbusservice["/Dc/0/Power"] = round(self.battery.power_calc, 2) if self.battery.power_calc is not None else None
        self._dbusservice["/Dc/0/Temperature"] = self.battery.get_temperature()
        self._dbusservice["/Capacity"] = self.battery.get_capacity_remain()
        self._dbusservice["/ConsumedAmphours"] = self.battery.get_capacity_consumed()

        midpoint, deviation = self.battery.get_midvoltage()
        if midpoint is not None:
            self._dbusservice["/Dc/0/MidVoltage"] = midpoint
            self._dbusservice["/Dc/0/MidVoltageDeviation"] = deviation

        # Update battery extras
        self._dbusservice["/State"] = self.battery.state
        # https://github.com/victronenergy/veutil/blob/master/inc/veutil/ve_regs_payload.h
        # https://github.com/victronenergy/veutil/blob/master/src/qt/bms_error.cpp
        self._dbusservice["/ErrorCode"] = self.battery.error_code
        self._dbusservice["/ConnectionInformation"] = self.battery.connection_info

        self._dbusservice["/History/DeepestDischarge"] = (
            abs(self.battery.history.deepest_discharge) * -1 if self.battery.history.deepest_discharge is not None else None
        )
        self._dbusservice["/History/LastDischarge"] = abs(self.battery.history.last_discharge) * -1 if self.battery.history.last_discharge is not None else None
        self._dbusservice["/History/AverageDischarge"] = (
            abs(self.battery.history.average_discharge) * -1 if self.battery.history.average_discharge is not None else None
        )
        self._dbusservice["/History/TotalAhDrawn"] = abs(self.battery.history.total_ah_drawn) * -1 if self.battery.history.total_ah_drawn is not None else None
        self._dbusservice["/History/ChargeCycles"] = self.battery.history.charge_cycles
        self._dbusservice["/History/FullDischarges"] = self.battery.history.full_discharges
        self._dbusservice["/History/MinimumVoltage"] = self.battery.history.minimum_voltage
        self._dbusservice["/History/MaximumVoltage"] = self.battery.history.maximum_voltage
        self._dbusservice["/History/MinimumCellVoltage"] = self.battery.history.minimum_cell_voltage
        self._dbusservice["/History/MaximumCellVoltage"] = self.battery.history.maximum_cell_voltage
        self._dbusservice["/History/TimeSinceLastFullCharge"] = (
            int(time()) - self.battery.history.timestamp_last_full_charge if self.battery.history.timestamp_last_full_charge is not None else None
        )
        self._dbusservice["/History/LowVoltageAlarms"] = self.battery.history.low_voltage_alarms
        self._dbusservice["/History/HighVoltageAlarms"] = self.battery.history.high_voltage_alarms
        self._dbusservice["/History/MinimumTemperature"] = self.battery.history.minimum_temperature
        self._dbusservice["/History/MaximumTemperature"] = self.battery.history.maximum_temperature
        self._dbusservice["/History/DischargedEnergy"] = self.battery.history.discharged_energy
        self._dbusservice["/History/ChargedEnergy"] = self.battery.history.charged_energy
        self._dbusservice["/History/Clear"] = self.battery.history.clear

        self._dbusservice["/Io/AllowToCharge"] = 1 if self.battery.get_allow_to_charge() else 0
        self._dbusservice["/Io/AllowToDischarge"] = 1 if self.battery.get_allow_to_discharge() else 0
        self._dbusservice["/Io/AllowToBalance"] = 1 if self.battery.get_allow_to_balance() else 0
        self._dbusservice["/System/NrOfModulesBlockingCharge"] = 0 if self.battery.get_allow_to_charge() else 1
        self._dbusservice["/System/NrOfModulesBlockingDischarge"] = 0 if self.battery.get_allow_to_discharge() else 1
        self._dbusservice["/System/NrOfModulesOnline"] = 1 if self.battery.online else 0
        self._dbusservice["/System/NrOfModulesOffline"] = 0 if self.battery.online else 1
        self._dbusservice["/System/MinCellTemperature"] = self.battery.get_min_temperature()
        self._dbusservice["/System/MinTemperatureCellId"] = self.battery.get_min_temperature_id()
        self._dbusservice["/System/MaxCellTemperature"] = self.battery.get_max_temperature()
        self._dbusservice["/System/MaxTemperatureCellId"] = self.battery.get_max_temperature_id()
        self._dbusservice["/System/MOSTemperature"] = self.battery.temperature_mos
        self._dbusservice["/System/Temperature1"] = self.battery.temperature_1
        self._dbusservice["/System/Temperature1Name"] = utils.TEMPERATURE_1_NAME
        self._dbusservice["/System/Temperature2"] = self.battery.temperature_2
        self._dbusservice["/System/Temperature2Name"] = utils.TEMPERATURE_2_NAME
        self._dbusservice["/System/Temperature3"] = self.battery.temperature_3
        self._dbusservice["/System/Temperature3Name"] = utils.TEMPERATURE_3_NAME
        self._dbusservice["/System/Temperature4"] = self.battery.temperature_4
        self._dbusservice["/System/Temperature4Name"] = utils.TEMPERATURE_4_NAME

        # Voltage control
        self._dbusservice["/Info/MaxChargeVoltage"] = (
            round(self.battery.control_voltage + utils.VOLTAGE_DROP, 2) if self.battery.control_voltage is not None else None
        )

        # Charge control
        self._dbusservice["/Info/MaxChargeCurrent"] = self.battery.control_charge_current
        self._dbusservice["/Info/MaxDischargeCurrent"] = self.battery.control_discharge_current

        # Voltage and charge control info (custom dbus paths)
        self._dbusservice["/Info/ChargeMode"] = self.battery.charge_mode
        self._dbusservice["/Info/ChargeModeDebug"] = self.battery.charge_mode_debug
        self._dbusservice["/Info/ChargeModeDebugFloat"] = self.battery.charge_mode_debug_float
        self._dbusservice["/Info/ChargeModeDebugBulk"] = self.battery.charge_mode_debug_bulk
        self._dbusservice["/Info/ChargeLimitation"] = self.battery.charge_limitation
        self._dbusservice["/Info/DischargeLimitation"] = self.battery.discharge_limitation

        # Updates from cells
        self._dbusservice["/System/MinVoltageCellId"] = self.battery.get_min_cell_desc()
        self._dbusservice["/System/MaxVoltageCellId"] = self.battery.get_max_cell_desc()
        self._dbusservice["/System/MinCellVoltage"] = self.battery.get_min_cell_voltage()
        self._dbusservice["/System/MaxCellVoltage"] = self.battery.get_max_cell_voltage()
        self._dbusservice["/Balancing"] = self.battery.get_balancing()

        # Update the alarms
        self.battery.protection.set_previous()
        self._dbusservice["/Alarms/LowVoltage"] = self.battery.protection.low_voltage
        self._dbusservice["/Alarms/LowCellVoltage"] = self.battery.protection.low_cell_voltage
        # disable high voltage warning temporarly, if loading to bulk voltage and bulk voltage reached is 30 minutes ago
        self._dbusservice["/Alarms/HighVoltage"] = (
            self.battery.protection.high_voltage
            if (self.battery.soc_reset_requested is False and self.battery.soc_reset_last_reached < int(time()) - (60 * 30))
            else 0
        )
        self._dbusservice["/Alarms/HighCellVoltage"] = (
            self.battery.protection.high_cell_voltage
            if (self.battery.soc_reset_requested is False and self.battery.soc_reset_last_reached < int(time()) - (60 * 30))
            else 0
        )
        self._dbusservice["/Alarms/LowSoc"] = self.battery.protection.low_soc
        self._dbusservice["/Alarms/HighChargeCurrent"] = self.battery.protection.high_charge_current
        self._dbusservice["/Alarms/HighDischargeCurrent"] = self.battery.protection.high_discharge_current
        self._dbusservice["/Alarms/CellImbalance"] = self.battery.protection.cell_imbalance
        self._dbusservice["/Alarms/InternalFailure"] = self.battery.protection.internal_failure
        self._dbusservice["/Alarms/HighChargeTemperature"] = self.battery.protection.high_charge_temperature
        self._dbusservice["/Alarms/LowChargeTemperature"] = self.battery.protection.low_charge_temperature
        self._dbusservice["/Alarms/HighTemperature"] = self.battery.protection.high_temperature
        self._dbusservice["/Alarms/LowTemperature"] = self.battery.protection.low_temperature
        self._dbusservice["/Alarms/BmsCable"] = 2 if self.battery.block_because_disconnect else 0
        self._dbusservice["/Alarms/HighInternalTemperature"] = self.battery.protection.high_internal_temperature
        self._dbusservice["/Alarms/FuseBlown"] = self.battery.protection.fuse_blown

        # cell voltages
        if utils.BATTERY_CELL_DATA_FORMAT > 0:
            try:
                voltage_sum = 0
                for i in range(self.battery.cell_count):
                    voltage = self.battery.get_cell_voltage(i)
                    cellpath = "/Cell/%s/Volts" if (utils.BATTERY_CELL_DATA_FORMAT & 2) else "/Voltages/Cell%s"
                    self._dbusservice[cellpath % (str(i + 1))] = voltage
                    if utils.BATTERY_CELL_DATA_FORMAT & 1:
                        self._dbusservice["/Balances/Cell%s" % (str(i + 1))] = self.battery.get_cell_balancing(i)
                    if voltage:
                        voltage_sum += voltage
                pathbase = "Cell" if (utils.BATTERY_CELL_DATA_FORMAT & 2) else "Voltages"
                self._dbusservice["/%s/Sum" % pathbase] = round(voltage_sum, 2)
                self._dbusservice["/%s/Diff" % pathbase] = round(
                    self.battery.get_max_cell_voltage() - self.battery.get_min_cell_voltage(),
                    3,
                )
            except Exception:
                # set error code, to show in the GUI that something is wrong
                self.battery.manage_error_code(8)

                exception_type, exception_object, exception_traceback = sys.exc_info()
                file = exception_traceback.tb_frame.f_code.co_filename
                line = exception_traceback.tb_lineno
                logger.error("Non blocking exception occurred: " + f"{repr(exception_object)} of type {exception_type} in {file} line #{line}")

        # Calculate average current for the last 300 cycles
        self.battery.previous_current_avg = self.battery.current_avg
        if self.battery.current_calc is not None:
            self.battery.current_avg_lst.append(self.battery.current_calc)
            # delete oldest value
            if len(self.battery.current_avg_lst) > 300:
                del self.battery.current_avg_lst[0]

            self.battery.current_avg = round(
                sum(self.battery.current_avg_lst) / len(self.battery.current_avg_lst),
                2,
            )
        else:
            self.battery.current_avg = None

        self._dbusservice["/CurrentAvg"] = self.battery.current_avg

        # Update TimeToGo and/or TimeToSoC
        try:
            # if Time-To-Go or Time-To-SoC is enabled

            if (
                self.battery.capacity is not None
                and self.battery.current_avg is not None
                and (utils.TIME_TO_GO_ENABLE or len(utils.TIME_TO_SOC_POINTS) > 0)
                and (int(time()) - self.battery.time_to_soc_update >= utils.TIME_TO_SOC_RECALCULATE_EVERY)
            ):
                self.battery.time_to_soc_update = int(time())

                percent_per_seconds = abs(self.battery.current_avg / (self.battery.capacity / 100)) / 3600

                # Update TimeToGo item
                if utils.TIME_TO_GO_ENABLE and percent_per_seconds is not None:

                    # Get settings from dbus
                    settings_battery_life = self.get_settings_with_values(
                        get_bus(),
                        "com.victronenergy.settings",
                        "/Settings/CGwacs/BatteryLife",
                    )
                    settings_hub4mode = self.get_settings_with_values(
                        get_bus(),
                        "com.victronenergy.settings",
                        "/Settings/CGwacs/Hub4Mode",
                    )

                    hub4mode = int(settings_hub4mode["Settings"]["CGwacs"]["Hub4Mode"]) if "Settings" in settings_hub4mode else None
                    state = (
                        int(settings_battery_life["Settings"]["CGwacs"]["BatteryLife"]["State"])
                        if "Settings" in settings_battery_life and "State" in settings_battery_life["Settings"]["CGwacs"]["BatteryLife"]
                        else None
                    )

                    if (
                        hub4mode == 1
                        and state != 9
                        and "Settings" in settings_battery_life
                        and "MinimumSocLimit" in settings_battery_life["Settings"]["CGwacs"]["BatteryLife"]
                        and "SocLimit" in settings_battery_life["Settings"]["CGwacs"]["BatteryLife"]
                    ):
                        # Optimized without BatteryLife
                        if state >= 10 and state <= 12:
                            time_to_go_soc = int(float(settings_battery_life["Settings"]["CGwacs"]["BatteryLife"]["MinimumSocLimit"]))
                            logger.debug(f"Time-to-Go: Use /Settings/CGwacs/BatteryLife/MinimumSocLimit: {time_to_go_soc}")
                        # Optimized with BatteryLife
                        else:
                            time_to_go_soc = int(float(settings_battery_life["Settings"]["CGwacs"]["BatteryLife"]["SocLimit"]))
                            logger.debug(f"Time-to-Go: Use /Settings/CGwacs/BatteryLife/SocLimit: {time_to_go_soc}")
                    # External control
                    # Keep batteries charged
                    # all others fall back to default
                    else:
                        time_to_go_soc = utils.SOC_LOW_WARNING
                        logger.debug(f"Time-to-Go: Use utils.SOC_LOW_WARNING: {time_to_go_soc}")

                    # Update TimeToGo item, has to be a positive int since it's used from dbus-systemcalc-py
                    time_to_go = self.battery.get_time_to_soc(
                        # switch value depending on charging/discharging
                        (time_to_go_soc if self.battery.current_avg < 0 else 100),
                        percent_per_seconds,
                        True,
                    )

                    # Check that time_to_go is not None and current is not near zero
                    self._dbusservice["/TimeToGo"] = abs(int(time_to_go)) if time_to_go is not None and abs(self.battery.current_avg) > 0.1 else None

                # Update TimeToSoc items
                if len(utils.TIME_TO_SOC_POINTS) > 0:
                    for num in utils.TIME_TO_SOC_POINTS:
                        self._dbusservice["/TimeToSoC/" + str(num)] = (
                            self.battery.get_time_to_soc(num, percent_per_seconds) if self.battery.current_avg else None
                        )

        except Exception:
            # set error code, to show in the GUI that something is wrong
            self.battery.manage_error_code(8)

            exception_type, exception_object, exception_traceback = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error("Non blocking exception occurred: " + f"{repr(exception_object)} of type {exception_type} in {file} line #{line}")

        # calculate history values every 60 seconds
        if utils.HISTORY_ENABLE and int(time()) - self.history_calculated_last_time > 60:
            self.battery.history_calculate_values()
            self.history_calculated_last_time = int(time())

        # save settings every 15 seconds to dbus
        if int(time()) % 15:
            self.save_current_battery_state()

        if self.battery.soc is not None:
            logger.debug("logged to dbus [%s]" % str(round(self.battery.soc, 2)))
            self.battery.log_cell_data()

        if self.battery.has_settings:
            self._dbusservice["/Settings/ResetSoc"] = self.battery.reset_soc

        # get all paths from the dbus service
        if utils.PUBLISH_BATTERY_DATA_AS_JSON:
            all_items = self._dbusservice._dbusnodes["/"].GetItems()

            # Convert dbus data types to python native data types
            all_items = {key: self.dbus_to_python(value["Value"]) for key, value in all_items.items()}

            # Filter out unwanted keys
            filtered_data = {key: value for key, value in all_items.items() if key not in ["/JsonData", "/Settings/ResetSoc", "/Settings/HasSettings"]}

            # Set empty lists to empty string
            filtered_data = {key: "" if value == [] else value for key, value in filtered_data.items()}

            cascaded_data_json = json.dumps(self.cascade_data(filtered_data))

            # publish the data to the JsonData path
            self._dbusservice["/JsonData"] = cascaded_data_json

    def dbus_to_python(self, data) -> any:
        """
        convert dbus data types to python native data types

        :param data: The data to convert.
        :return: The converted data.
        """
        if isinstance(data, dbus.String):
            data = str(data)
        elif isinstance(data, dbus.Boolean):
            data = bool(data)
        elif isinstance(data, dbus.Int64):
            data = int(data)
        elif isinstance(data, dbus.Double):
            data = float(data)
        elif isinstance(data, dbus.Array):
            data = [self.dbus_to_python(value) for value in data]
        elif isinstance(data, dbus.Dictionary):
            new_data = dict()
            for key in data.keys():
                new_data[self.dbus_to_python(key)] = self.dbus_to_python(data[key])
            data = new_data
        return data

    def cascade_data(self, data) -> dict:
        """
        Cascade the data to a nested dictionary structure.

        :param data: The data to cascade.
        :return: The cascaded data.
        """
        cascaded = {}
        for key, value in data.items():
            parts = key.strip("/").split("/")
            d = cascaded
            for part in parts[:-1]:
                if part not in d:
                    d[part] = {}
                d = d[part]
            d[parts[-1]] = value
        return cascaded

    def get_settings_with_values(self, bus, service: str, object_path: str, recursive: bool = True) -> dict:
        """
        Get all settings with values from dbus.

        :param bus: The dbus object.
        :param service: The service name.
        :param object_path: The object path.
        :param recursive: If True, it will get all settings with values recursively.
        :return: A dictionary with all settings and values.
        """
        # print(object_path)
        obj = bus.get_object(service, object_path)
        iface = dbus.Interface(obj, "org.freedesktop.DBus.Introspectable")
        xml_string = iface.Introspect()
        # print(xml_string)
        result = {}
        for child in ElementTree.fromstring(xml_string):
            if child.tag == "node" and recursive:
                if object_path == "/":
                    object_path = ""
                new_path = "/".join((object_path, child.attrib["name"]))
                # result.update(get_settings_with_values(bus, service, new_path))
                result_sub = self.get_settings_with_values(bus, service, new_path)
                self.merge_dicts(result, result_sub)
            elif child.tag == "interface":
                if child.attrib["name"] == "com.victronenergy.Settings":
                    settings_iface = dbus.Interface(obj, "com.victronenergy.BusItem")
                    method = settings_iface.get_dbus_method("GetValue")
                    try:
                        value = method()
                        if type(value) is not dbus.Dictionary:
                            # result[object_path] = str(value)
                            self.merge_dicts(
                                result,
                                self.create_nested_dict(object_path, str(value)),
                            )
                            # print(f"{object_path}: {value}")
                        if not recursive:
                            return value
                    except dbus.exceptions.DBusException as e:
                        # set error code, to show in the GUI that something is wrong
                        self.battery.manage_error_code(8)

                        logger.error(f"get_settings_with_values(): Failed to get value: {e}")

        return result

    def set_settings(self, bus, service: str, object_path: str, setting_name: str, value) -> bool:
        """
        Set a setting with a value to dbus.

        :param bus: The dbus object.
        :param service: The service name.
        :param object_path: The object path.
        :param setting_name: The setting name.
        :param value: The value to set.
        :return: True if the setting was set, otherwise False.
        """
        # check if value is None
        if value is None:
            return False

        obj = bus.get_object(service, object_path + "/" + setting_name)
        # iface = dbus.Interface(obj, "org.freedesktop.DBus.Introspectable")
        # xml_string = iface.Introspect()
        # print(xml_string)
        settings_iface = dbus.Interface(obj, "com.victronenergy.BusItem")
        method = settings_iface.get_dbus_method("SetValue")
        try:
            logger.debug(f"Setted setting {object_path}/{setting_name} to {value}")
            return True if method(value) == 0 else False
        except dbus.exceptions.DBusException as e:
            # set error code, to show in the GUI that something is wrong
            self.battery.manage_error_code(8)

            logger.error(f"Failed to set setting: {e}")

    def remove_settings(self, bus, service: str, object_path: str, setting_name: list) -> bool:
        """
        Remove a setting from dbus.

        :param bus: The dbus object.
        :param service: The service name.
        :param object_path: The object path.
        :param setting_name: The setting name.
        :return: True if the setting was removed, otherwise False.
        """
        obj = bus.get_object(service, object_path)
        # iface = dbus.Interface(obj, "org.freedesktop.DBus.Introspectable")
        # xml_string = iface.Introspect()
        # print(xml_string)
        settings_iface = dbus.Interface(obj, "com.victronenergy.Settings")
        method = settings_iface.get_dbus_method("RemoveSettings")
        try:
            logger.debug(f"Removed setting at {object_path}")
            return True if method(setting_name) == 0 else False
        except dbus.exceptions.DBusException as err:
            # set error code, to show in the GUI that something is wrong
            self.battery.manage_error_code(8)

            logger.error("Failed to remove setting")
            logger.error(err)

    def create_nested_dict(self, path, value) -> dict:
        """
        Creates a nested dictionary from a given path and value.

        This function takes a string path, splits it by "/", and creates a nested dictionary structure
        where each part of the path becomes a key in the dictionary. The final part of the path is
        assigned the provided value.

        :param path: A string representing the path, with parts separated by "/".
        :param value: The value to assign to the final key in the nested dictionary.
        :return: A nested dictionary representing the path and value.
        """
        keys = path.strip("/").split("/")
        result = current = {}
        for key in keys[:-1]:
            current[key] = {}
            current = current[key]
        current[keys[-1]] = value
        return result

    def merge_dicts(self, dict1, dict2) -> None:
        """
        Merges dict2 into dict1 recursively.

        This function takes two dictionaries and merges dict2 into dict1. If a key exists in both dictionaries
        and the corresponding values are also dictionaries, it merges those dictionaries recursively. Otherwise,
        it overwrites the value in dict1 with the value from dict2.

        :param dict1: The dictionary to merge into.
        :param dict2: The dictionary to merge from.
        :return: None
        """
        for key in dict2:
            if key in dict1 and isinstance(dict1[key], dict) and isinstance(dict2[key], dict):
                self.merge_dicts(dict1[key], dict2[key])
            else:
                dict1[key] = dict2[key]

    def custom_name_callback(self, path, value) -> str:
        """
        Callback function to set a custom name for the battery.

        This function sets a custom name for the battery by updating the settings on the D-Bus.
        It logs the result of the operation and returns the new value if the operation was successful,
        otherwise it returns None.

        :param path: The D-Bus path where the custom name should be set.
        :param value: The custom name to set.
        :return: The custom name if the operation was successful, otherwise None.
        """
        result = self.set_settings(
            get_bus(),
            "com.victronenergy.settings",
            self.path_battery,
            "CustomName",
            value,
        )
        logger.debug(f'CustomName changed to "{value}" for {self.path_battery}: {result}')
        return value if result else None

    # save current battery states to dbus
    def save_current_battery_state(self) -> bool:
        """
        Save the current battery state to dbus.

        This function saves the current battery state to dbus. It checks if the values have changed and
        only saves the values that have changed.

        :return: True if the values have been saved, otherwise False.
        """
        result = True

        if self.battery.allow_max_voltage != self.save_charge_details_last["allow_max_voltage"]:
            result = result + self.set_settings(
                get_bus(),
                "com.victronenergy.settings",
                self.path_battery,
                "AllowMaxVoltage",
                1 if self.battery.allow_max_voltage else 0,
            )
            logger.debug(f"Saved AllowMaxVoltage. Before {self.save_charge_details_last['allow_max_voltage']}, " + f"after {self.battery.allow_max_voltage}")
            self.save_charge_details_last["allow_max_voltage"] = self.battery.allow_max_voltage

        if self.battery.max_voltage_start_time != self.save_charge_details_last["max_voltage_start_time"]:
            result = result and self.set_settings(
                get_bus(),
                "com.victronenergy.settings",
                self.path_battery,
                "MaxVoltageStartTime",
                (self.battery.max_voltage_start_time if self.battery.max_voltage_start_time is not None else ""),
            )
            logger.debug(
                f"Saved MaxVoltageStartTime. Before {self.save_charge_details_last['max_voltage_start_time']}, "
                + f"after {self.battery.max_voltage_start_time}"
            )
            self.save_charge_details_last["max_voltage_start_time"] = self.battery.max_voltage_start_time

        if self.battery.soc_calc != self.save_charge_details_last["soc_calc"]:
            result = result and self.set_settings(
                get_bus(),
                "com.victronenergy.settings",
                self.path_battery,
                "SocCalc",
                self.battery.soc_calc,
            )
            logger.debug(f"soc_calc written to dbus: {self.battery.soc_calc}")
            self.save_charge_details_last["soc_calc"] = self.battery.soc_calc

        if self.battery.soc_reset_last_reached != self.save_charge_details_last["soc_reset_last_reached"]:
            result = result and self.set_settings(
                get_bus(),
                "com.victronenergy.settings",
                self.path_battery,
                "SocResetLastReached",
                self.battery.soc_reset_last_reached,
            )
            logger.debug(
                f"Saved SocResetLastReached. Before {self.save_charge_details_last['soc_reset_last_reached']}, "
                + f"after {self.battery.soc_reset_last_reached}",
            )
            self.save_charge_details_last["soc_reset_last_reached"] = self.battery.soc_reset_last_reached

        # copy history values
        history_values_dict = self.battery.history.__dict__.copy()
        # remove values that should not be saved
        history_remove_values = self.battery.history.exclude_values_to_calculate + ["exclude_values_to_calculate"]
        # remove keys that should not be saved
        for key in history_remove_values:
            history_values_dict.pop(key, None)
        # remove keys with None values
        keys_to_remove = [key for key, value in history_values_dict.items() if value is None]
        for key in keys_to_remove:
            history_values_dict.pop(key)

        history_values = json.dumps(history_values_dict)
        if history_values != self.save_charge_details_last["history_values"]:
            result = result and self.set_settings(
                get_bus(),
                "com.victronenergy.settings",
                self.path_battery,
                "HistoryValues",
                history_values,
            )
            logger.debug(
                f"Saved HistoryValues. Before {self.save_charge_details_last['history_values']}, after {history_values}",
            )
            self.save_charge_details_last["history_values"] = history_values

        return result

    def telemetry_upload(self) -> None:
        """
        Check if telemetry should be uploaded
        """
        if utils.TELEMETRY:
            # check if telemetry should be uploaded
            if not self.telemetry_upload_running and self.telemetry_upload_last + self.telemetry_upload_interval < int(time()):
                self.telemetry_upload_thread = threading.Thread(target=self.telemetry_upload_async)
                self.telemetry_upload_thread.start()

    def telemetry_upload_async(self) -> None:
        """
        Run telemetry upload in a separate thread
        """
        self.telemetry_upload_running = True

        # logger.info("Uploading telemetry data")

        # read the version of Venus OS
        with open("/opt/victronenergy/version", "r") as f:
            venus_version = f.readline().strip()

        # read the device type
        with open("/sys/firmware/devicetree/base/model", "r") as f:
            gx_device_type = f.readline().strip()

        # assemble the data to be uploaded
        data = {
            "vrm_id": get_vrm_portal_id(),
            "venus_os_version": venus_version,
            "gx_device_type": gx_device_type,
            "driver_version": utils.DRIVER_VERSION,
            "device_instance": self.instance,
            "bms_type": self.battery.type,
            "cell_count": self.battery.cell_count,
            "connection_type": self.battery.connection_name(),
            "driver_runtime": int(time()) - self.battery.start_time,
            "error_code": (self.battery.error_code if self.battery.error_code is not None else 0),
        }

        # post data to the server as json
        try:
            response = requests.post(
                "https://github.md0.eu/venus-os_dbus-serialbattery/telemetry.php",
                data=data,
                timeout=60,
                # verify=False,
            )
            response.raise_for_status()

            self.telemetry_upload_error_count = 0
            self.telemetry_upload_last = int(time())

            # logger.info(f"Telemetry uploaded: {response.text}")

        except Exception:
            self.telemetry_upload_error_count += 1

            """
            (
                exception_type,
                exception_object,
                exception_traceback,
            ) = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error(
                "Non blocking exception occurred: "
                + f"{repr(exception_object)} of type {exception_type} in {file} line #{line}"
            )
            """

            if self.telemetry_upload_error_count >= 5:
                self.telemetry_upload_error_count = 0
                self.telemetry_upload_last = int(time())

                # logger.error(
                #     "Failed to upload telemetry 5 times."
                #     + f"Retry on next interval in {self.telemetry_upload_interval} s."
                # )
            else:

                # Check if the main thread is still alive
                #
                main_thread = threading.main_thread()

                # Wait 59 minutes before retrying
                sleep_time = 60 * 59
                sleep_count = 0

                while main_thread.is_alive() and sleep_count < sleep_time:
                    # wait 14 minutes before retrying, 1 minute request timeout, 14 minutes sleep
                    sleep(1)
                    sleep_count += 1

        self.telemetry_upload_running = False
