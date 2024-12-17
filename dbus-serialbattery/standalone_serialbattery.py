############################################################################
#                                                                          #
#    Copyright (C) 2024 by macGH                                           #
#                                                                          #
#    For LICENSE see LICENSE file of                                       #
#    https://github.com/mr-manuel/venus-os_dbus-serialbattery              #
#                                                                          #
############################################################################

# NOTES
# This part is maintained by https://github.com/MacGH23

# Reading BMS via dbus-serialbattery
# Re-used
# https://github.com/mr-manuel/venus-os_dbus-serialbattery
# to make this class
# currently only tested with
# - JKBMS B2A8S20P
# - DALY BMS
# and with original JK RS485 USB adapter and Daly USB-UART adapter !
# but the original dbus serial tested and it should work with all other devices, too
#
# Use at your own risk !
#
# The return is a list of data.
# Depending on the cellcount, the list is longer or shorter
# Check first item for cellcount !
# Cellcount: Nr
# CellVolt1 to CellVolt[nr] in *1000 notation -> 3200 = 3,2V
# ....
# Temp_Fet in °C
# Temp_1   in °C
# temp_2   in °C
# BatVolt in *100 notation -> 2380 = 23,80V
# Current in *100 notation -> 1300 = 13,00A; positive = DisCharge current, negative = Charge current
# SOC     in % (0..100)
#
# Version history
# macGH 20.08.2024  Version 0.1.0
# macGH 06.12.2024  Version 0.2.0: Update to newest serialbattery code

######################################################################################
# Explanations (see also standalone_serialbattery_test.py for an example)
######################################################################################

######################################################################################
# def __init__(self, devpath, driverOption, devadr, loglevel):
#
# devpath
# Add the /dev/tty device here, mostly .../dev/ttyUSB0, if empty default path /dev/ttyUSB0 is used
#
# driverOption
# Id for bluetooth and can devices
# 0 : autotetect for all non BT / CAN devices
# 1 : JKBMS bluettooth - Jkbms_Ble
# 2 : JDB bluetooth    - LltJbd_Ble
# 3 : LiTime bluetooth - LiTime_Ble
# 10: CAN devices for JKBAMS and DALY
#
# devadr
# bluetooth address as string or "" empty
#
# loglevel
# Enter Loglevel 0,10,20,30,40,50
# CRITICAL   50
# ERROR      40
# WARNING    30
# INFO       20
# DEBUG      10
# NOTSET      0
######################################################################################


import os
import sys
import logging

from typing import Union
from time import sleep

from standalone_helper import DbusHelper
import utils
from battery import Battery

from utils import (
    BMS_TYPE,
    logger,
    BATTERY_ADDRESSES,
)

# import battery classes
# TODO: import only the classes that are needed
from bms.daly import Daly
from bms.daren_485 import Daren485
from bms.ecs import Ecs
from bms.eg4_lifepower import EG4_Lifepower
from bms.eg4_ll import EG4_LL
from bms.felicity import Felicity
from bms.heltecmodbus import HeltecModbus
from bms.hlpdatabms4s import HLPdataBMS4S
from bms.jkbms import Jkbms
from bms.jkbms_pb import Jkbms_pb
from bms.lltjbd import LltJbd
from bms.renogy import Renogy
from bms.seplos import Seplos
from bms.seplosv3 import Seplosv3

# add ext folder to sys.path
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "ext"))

# enabled only if explicitly set in config under "BMS_TYPE"
if "ANT" in BMS_TYPE:
    from bms.ant import ANT
if "MNB" in BMS_TYPE:
    from bms.mnb import MNB
if "Sinowealth" in BMS_TYPE:
    from bms.sinowealth import Sinowealth

supported_bms_types = [
    {"bms": Daly, "baud": 9600, "address": b"\x40"},
    {"bms": Daly, "baud": 9600, "address": b"\x80"},
    {"bms": Daren485, "baud": 19200, "address": b"\x01"},
    {"bms": Ecs, "baud": 19200},
    {"bms": EG4_Lifepower, "baud": 9600, "address": b"\x01"},
    {"bms": EG4_LL, "baud": 9600, "address": b"\x01"},
    {"bms": Felicity, "baud": 9600, "address": b"\x01"},
    {"bms": HeltecModbus, "baud": 9600, "address": b"\x01"},
    {"bms": HLPdataBMS4S, "baud": 9600},
    {"bms": Jkbms, "baud": 115200},
    {"bms": Jkbms_pb, "baud": 115200, "address": b"\x01"},
    {"bms": LltJbd, "baud": 9600, "address": b"\x00"},
    {"bms": Renogy, "baud": 9600, "address": b"\x30"},
    {"bms": Renogy, "baud": 9600, "address": b"\xF7"},
    {"bms": Seplos, "baud": 19200, "address": b"\x00"},
    {"bms": Seplosv3, "baud": 19200},
]


class standalone_serialbattery:

    def init_bms_types(self):
        self.supported_bms_types = supported_bms_types

        # enabled only if explicitly set in config under "BMS_TYPE"
        if "ANT" in BMS_TYPE:
            self.supported_bms_types.append({"bms": ANT, "baud": 19200})
        if "MNB" in BMS_TYPE:
            self.supported_bms_types.append({"bms": MNB, "baud": 9600})
        if "Sinowealth" in BMS_TYPE:
            self.supported_bms_types.append({"bms": Sinowealth, "baud": 9600})

        self.expected_bms_types = [battery_type for battery_type in self.supported_bms_types if battery_type["bms"].__name__ in BMS_TYPE or len(BMS_TYPE) == 0]

    def __init__(self, devpath, driverOption, devadr, loglevel):
        # init with default
        self.init_bms_types()
        self.devpath = "/dev/ttyUSB0"  # just try if is is the common devpath
        self.loglevel = 20  # just use info as default
        self.driveroption = driverOption
        self.devadr = devadr

        if devpath != "":
            self.devpath = devpath
        if loglevel != "":
            self.loglevel = loglevel

        logging.debug("Init bms class")
        self.cells = [0] * 24
        self.battery = {}
        self.helper = {}
        self.BatIds = []

    def bms_open(self):
        logging.info("open serial interface")
        # check if BMS_TYPE is not empty and all BMS types in the list are supported
        if len(BMS_TYPE) > 0:
            for bms_type in BMS_TYPE:
                if bms_type not in [bms["bms"].__name__ for bms in self.supported_bms_types]:
                    logging.error(
                        f'ERROR >>> BMS type "{bms_type}" is not supported. Supported BMS types are: '
                        + f"{', '.join([bms['bms'].__name__ for bms in self.supported_bms_types])}"
                        + "; Disabled by default: ANT, MNB, Sinowealth"
                    )
                    raise Exception("BMS DEVICE NOT IN SUPPORTED LIST")

        if self.driveroption != 0:  # no autodetect for Bluetooth, CAN and serial
            """
            Import ble classes only, if it's a ble port, else the driver won't start due to missing python modules
            This prevent problems when using the driver only with a serial connection
            """
            if self.driveroption <= 3:  # bluetooth

                if self.driveroption == 1:  # "Jkbms_Ble":
                    # noqa: F401 --> ignore flake "imported but unused" error
                    from bms.jkbms_ble import Jkbms_Ble  # noqa: F401

                if self.driveroption == 2:  # "LltJbd_Ble":
                    # noqa: F401 --> ignore flake "imported but unused" error
                    from bms.lltjbd_ble import LltJbd_Ble  # noqa: F401

                if self.driveroption == 3:  # "LiTime_Ble":
                    # noqa: F401 --> ignore flake "imported but unused" error
                    from bms.litime_ble import LiTime_Ble  # noqa: F401

                class_ = eval(self.devpath)
                testbms = class_("ble_" + self.devadr.replace(":", "").lower(), 9600, self.devadr)

                if testbms.test_connection():
                    logging.info("Connection established to " + testbms.__class__.__name__)
                    self.battery[0] = testbms

            if self.driveroption == 10:  # can interface
                """
                Import CAN classes only, if it's a can port, else the driver won't start due to missing python modules
                This prevent problems when using the driver only with a serial connection
                """
                from bms.daly_can import Daly_Can
                from bms.jkbms_can import Jkbms_Can

                # only try CAN BMS on CAN port
                self.supported_bms_types = [
                    {"bms": Daly_Can},
                    {"bms": Jkbms_Can},
                ]

                self.expected_bms_types = [
                    battery_type for battery_type in self.supported_bms_types if battery_type["bms"].__name__ in BMS_TYPE or len(BMS_TYPE) == 0
                ]

                # start the corresponding CanReceiverThread if BMS for this type found
                from utils_can import CanReceiverThread

                try:
                    can_thread = CanReceiverThread.get_instance(bustype="socketcan", channel=self.devpath)
                except Exception as e:
                    print(f"Error: {e}")

                logging.debug("Wait shortly to make sure that all needed data is in the cache")
                # Slowest message cycle trasmission is every 1 second, wait a bit more for the fist time to fetch all needed data
                sleep(2)

                # check if BATTERY_ADDRESSES is not empty
                if BATTERY_ADDRESSES:
                    logging.info(">>> CAN multi device mode")
                    for address in BATTERY_ADDRESSES:
                        checkbatt = self.get_battery(self.devpath, address, can_thread.get_message_cache)
                        if checkbatt is not None:
                            self.battery[address] = checkbatt
                            logging.info("Successful battery connection at " + self.devpath + " and this device address " + str(address))
                        else:
                            logging.warning("No battery connection at " + self.devpath + " and this device address " + str(address))
                # use default address
                else:
                    self.battery[0] = self.get_battery(self.devpath, None, can_thread.get_message_cache)

        else:  # Serial, modbus, ...
            # check if BMS_TYPE is not empty and all BMS types in the list are supported
            # self.check_bms_types(supported_bms_types, "serial")

            # wait some seconds to be sure that the serial connection is ready
            # else the error throw a lot of timeouts
            sleep(1)

            # check if BATTERY_ADDRESSES is not empty
            if BATTERY_ADDRESSES:
                for address in BATTERY_ADDRESSES:
                    checkbatt = self.get_battery(self.devpath, address)
                    if checkbatt is not None:
                        self.battery[address] = checkbatt
                        logger.info("Successful battery connection at " + self.devpath + " and this Modbus address " + str(address))
                    else:
                        logger.warning("No battery connection at " + self.devpath + " and this Modbus address " + str(address))
            # use default address
            else:
                self.battery[0] = self.get_battery(self.devpath)

        # check if at least one BMS was found
        battery_found = False

        for key_address in self.battery:
            if self.battery[key_address] is not None:
                battery_found = True

        if not battery_found:
            logging.error(
                "ERROR >>> No battery connection at "
                + self.devpath
                + (" and this Modbus addresses: " + ", ".join(utils.MODBUS_ADDRESSES) if utils.MODBUS_ADDRESSES else "")
            )
            raise Exception("BMS DEVICE NOT FOUND")

        for key_address in self.battery:
            self.helper[key_address] = DbusHelper(self.battery[key_address], key_address)
            self.BatIds.append(key_address)

        # print log at this point, else not all data is correctly populated
        # self.battery.log_settings()
        return self.BatIds

    def check_bms_types(self, supported_bms_types, type) -> None:
        """
        Checks if BMS_TYPE is not empty and all specified BMS types are supported.

        :param supported_bms_types: List of supported BMS types.
        :param type: The type of BMS connection (ble, can, or serial).
        :return: None
        """
        # Get only BMS_TYPE that end with "_Ble"
        if type == "ble":
            bms_types = [type for type in BMS_TYPE if type.endswith("_Ble")]

        # Get only BMS_TYPE that end with "_Can"
        if type == "can":
            bms_types = [type for type in BMS_TYPE if type.endswith("_Can")]

        # Get only BMS_TYPE that do not end with "_Ble" or "_Can"
        if type == "serial":
            bms_types = [type for type in BMS_TYPE if not type.endswith("_Ble") and not type.endswith("_Can")]

        if len(bms_types) > 0:
            for bms_type in bms_types:
                if bms_type not in [bms["bms"].__name__ for bms in supported_bms_types]:
                    logger.error(
                        f'ERROR >>> BMS type "{bms_type}" is not supported. Supported BMS types are: '
                        + f"{', '.join([bms['bms'].__name__ for bms in supported_bms_types])}"
                        + "; Disabled by default: ANT, MNB, Sinowealth"
                    )
                    raise (None, None, 1)

    def get_battery(self, _port: str, _modbus_address: hex = None, _can_message_cache_callback: callable = None) -> Union[Battery, None]:
        # all the different batteries the driver support and need to test for
        # try to establish communications with the battery 3 times, else exit
        retry = 1
        retries = 2
        while retry <= retries:
            logging.info("-- Testing BMS: " + str(retry) + " of " + str(retries) + " rounds")
            # create a new battery object that can read the battery and run connection test
            for test in self.expected_bms_types:
                # noinspection PyBroadException
                try:
                    if _modbus_address is not None:
                        # convert hex string to bytes
                        _bms_address = bytes.fromhex(_modbus_address.replace("0x", ""))
                    elif "address" in test:
                        _bms_address = test["address"]
                    else:
                        _bms_address = None

                    logging.info(
                        "Testing "
                        + test["bms"].__name__
                        + (' at address "' + utils.bytearray_to_string(_bms_address) + '"' if _bms_address is not None else "")
                    )
                    batteryClass = test["bms"]
                    baud = test["baud"] if "baud" in test else None
                    battery: Battery = batteryClass(port=_port, baud=baud, address=_bms_address)
                    if battery.test_connection() and battery.validate_data():
                        logging.info("-- Connection established to " + battery.__class__.__name__)
                        return battery
                except KeyboardInterrupt:
                    return None
                except Exception:
                    (
                        exception_type,
                        exception_object,
                        exception_traceback,
                    ) = sys.exc_info()
                    file = exception_traceback.tb_frame.f_code.co_filename
                    line = exception_traceback.tb_lineno
                    logging.error("Non blocking exception occurred: " + f"{repr(exception_object)} of type {exception_type} in {file} line #{line}")
                    # Ignore any malfunction test_function()
                    pass
            retry += 1
            sleep(0.5)

        return None

    def bms_close(self):
        logging.debug("close serial interface")

    #############################################################################
    # Read Write operation function
    def bms_read(self, BatId=0):
        Status = []

        try:
            # Read all command
            logging.debug("Reading BMS")
            self.helper[BatId].publish_battery(True)

            # Cellcount
            # Cellvoltage
            # temp_FET
            # temp1
            # temp2
            # temp3
            # temp4
            # total voltage
            # current
            # soc

            logging.debug("Analyse BMS")
            self.cell_count = self.helper[BatId].battery.cell_count
            Status.append(self.cell_count)

            # Voltages in 1000 -> 3590 = 3.590V
            for i in range(self.cell_count):
                voltage = int(self.helper[BatId].battery.get_cell_voltage(i) * 1000)
                Status.append(voltage)
                self.cells[i] = voltage

            self.temp_fet = self.helper[BatId].battery.temp_mos
            self.temp_1 = self.helper[BatId].battery.temp1
            self.temp_2 = self.helper[BatId].battery.temp2
            self.temp_3 = self.helper[BatId].battery.temp3
            self.temp_4 = self.helper[BatId].battery.temp4
            if self.temp_fet is None:
                self.temp_fet = 0
            if self.temp_1 is None:
                self.temp_1 = 0
            if self.temp_2 is None:
                self.temp_2 = 0
            if self.temp_3 is None:
                self.temp_3 = 0
            if self.temp_4 is None:
                self.temp_4 = 0
            Status.append(self.temp_fet)
            Status.append(self.temp_1)
            Status.append(self.temp_2)
            Status.append(self.temp_3)
            Status.append(self.temp_4)

            # Battery voltage in 100 -> 25,81 = 2581
            self.voltage = int(self.helper[BatId].battery.voltage * 100)
            Status.append(self.voltage)

            # Current in 100 -> 9,4A = 940; + = charge; - = discharge
            self.act_current = int(self.helper[BatId].battery.current * 100)
            Status.append(self.act_current)

            # Remaining capacity, %
            self.soc = self.helper[BatId].battery.soc
            Status.append(self.soc)

        except Exception as e:
            logging.error("Error during reading BMS")
            logging.error(str(e))

        return Status
