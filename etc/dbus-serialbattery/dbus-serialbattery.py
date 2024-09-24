#!/usr/bin/python
# -*- coding: utf-8 -*-
from typing import Union

from time import sleep
from datetime import datetime
from dbus.mainloop.glib import DBusGMainLoop

import sys

from gi.repository import GLib as gobject

# Victron packages
# from ve_utils import exit_on_error

from dbushelper import DbusHelper
from utils import logger
import utils
from battery import Battery
import math

# import battery classes
from bms.daly import Daly
from bms.daren_485 import Daren485
from bms.ecs import Ecs
from bms.eg4_lifepower import EG4_Lifepower
from bms.eg4_ll import EG4_LL
from bms.heltecmodbus import HeltecModbus
from bms.hlpdatabms4s import HLPdataBMS4S
from bms.jkbms import Jkbms
from bms.jkbms_pb import Jkbms_pb
from bms.lltjbd import LltJbd
from bms.renogy import Renogy
from bms.seplos import Seplos
from bms.seplosv3 import Seplosv3

# enabled only if explicitly set in config under "BMS_TYPE"
if "ANT" in utils.BMS_TYPE:
    from bms.ant import ANT
if "MNB" in utils.BMS_TYPE:
    from bms.mnb import MNB
if "Sinowealth" in utils.BMS_TYPE:
    from bms.sinowealth import Sinowealth

supported_bms_types = [
    # For multiple boards (1-16) in parallel, specify board addresses (0x40-0x4F) via MODBUS_ADDRESSES in config.ini
    #     (see "BMSTYPE = Daly" in config.default.ini), and enable the following line... optionally disable
    #     the 2 Daly lines following.
    # {"bms": Daly, "baud": 9600},
    {"bms": Daly, "baud": 9600, "address": b"\x40"},
    {"bms": Daly, "baud": 9600, "address": b"\x80"},
    {"bms": Daren485, "baud": 19200, "address": b"\x01"},
    {"bms": Ecs, "baud": 19200},
    {"bms": EG4_Lifepower, "baud": 9600, "address": b"\x01"},
    {"bms": EG4_LL, "baud": 9600, "address": b"\x01"},
    {"bms": HeltecModbus, "baud": 9600, "address": b"\x01"},
    {"bms": HLPdataBMS4S, "baud": 9600},
    {"bms": Jkbms, "baud": 115200},
    {"bms": Jkbms_pb, "baud": 115200, "address": b"\x01"},
    {"bms": LltJbd, "baud": 9600},
    {"bms": Renogy, "baud": 9600, "address": b"\x30"},
    {"bms": Renogy, "baud": 9600, "address": b"\xF7"},
    {"bms": Seplos, "baud": 19200, "address": b"\x00"},
    {"bms": Seplosv3, "baud": 19200},
]

# enabled only if explicitly set in config under "BMS_TYPE"
if "ANT" in utils.BMS_TYPE:
    supported_bms_types.append({"bms": ANT, "baud": 19200})
if "MNB" in utils.BMS_TYPE:
    supported_bms_types.append({"bms": MNB, "baud": 9600})
if "Sinowealth" in utils.BMS_TYPE:
    supported_bms_types.append({"bms": Sinowealth, "baud": 9600})

expected_bms_types = [
    battery_type
    for battery_type in supported_bms_types
    if battery_type["bms"].__name__ in utils.BMS_TYPE or len(utils.BMS_TYPE) == 0
]

logger.info("")
logger.info("Starting dbus-serialbattery")


# check if utils.BMS_TYPE is not empty and all BMS types in the list are supported
if len(utils.BMS_TYPE) > 0:
    for bms_type in utils.BMS_TYPE:
        if bms_type not in [bms["bms"].__name__ for bms in supported_bms_types]:
            logger.error(
                f'ERROR >>> BMS type "{bms_type}" is not supported. Supported BMS types are: '
                + f"{', '.join([bms['bms'].__name__ for bms in supported_bms_types])}"
                + "; Disabled by default: ANT, MNB, Sinowealth"
            )
            sys.exit(1)


# count loops
loop_count = 0


def main():
    # NameError: free variable 'expected_bms_types' referenced before assignment in enclosing scope
    global expected_bms_types

    def poll_battery(loop) -> bool:
        """
        Polls the battery for data and updates it on the dbus
        """
        global loop_count

        # count execution time in milliseconds
        start = datetime.now()

        for key_address in battery:
            helper[key_address].publish_battery(loop)

        runtime = (datetime.now() - start).total_seconds()
        logger.debug(f"Polling data took {runtime:.3f} seconds")

        # check if polling took too long and adjust poll interval, but only after 5 loops
        # since the first polls are always slower
        if loop_count > 5 and runtime > battery[first_key].poll_interval / 1000:
            new_poll_interval = math.ceil(runtime + 0.8) * 1000
            battery[first_key].poll_interval = new_poll_interval
            logger.warning(
                f"Polling took too long. Set to {new_poll_interval/1000:.3f} s"
            )

        loop_count += 1

        return True

    def get_battery(_port: str, _modbus_address: hex = None) -> Union[Battery, None]:
        # all the different batteries the driver support and need to test for
        # try to establish communications with the battery 3 times, else exit
        retry = 1
        retries = 3
        while retry <= retries:
            logger.info(
                "-- Testing BMS: " + str(retry) + " of " + str(retries) + " rounds"
            )
            # create a new battery object that can read the battery and run connection test
            for test in expected_bms_types:
                # noinspection PyBroadException
                try:
                    if _modbus_address is not None:
                        # convert hex string to bytes
                        _bms_address = bytes.fromhex(_modbus_address.replace("0x", ""))
                    elif "address" in test:
                        _bms_address = test["address"]
                    else:
                        _bms_address = None

                    logger.info(
                        "Testing "
                        + test["bms"].__name__
                        + (
                            ' at address "'
                            + utils.bytearray_to_string(_bms_address)
                            + '"'
                            if _bms_address is not None
                            else ""
                        )
                    )
                    batteryClass = test["bms"]
                    baud = test["baud"]
                    battery: Battery = batteryClass(
                        port=_port, baud=baud, address=_bms_address
                    )
                    if battery.test_connection() and battery.validate_data():
                        logger.info(
                            "Connection established to " + battery.__class__.__name__
                        )
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
                    logger.error(
                        "Non blocking exception occurred: "
                        + f"{repr(exception_object)} of type {exception_type} in {file} line #{line}"
                    )
                    # Ignore any malfunction test_function()
                    pass
            retry += 1
            sleep(0.5)

        return None

    def get_port() -> str:
        # Get the port we need to use from the argument
        if len(sys.argv) > 1:
            port = sys.argv[1]
            if port not in utils.EXCLUDED_DEVICES:
                return port
            else:
                logger.debug(
                    "Stopping dbus-serialbattery: "
                    + str(port)
                    + " is excluded trough the config file"
                )
                sleep(60)
                # exit with error in order that the serialstarter goes on
                sys.exit(1)
        else:
            # just for MNB-SPI
            logger.info("No Port needed")
            return "/dev/ttyUSB9"

    # read the version of Venus OS
    with open("/opt/victronenergy/version", "r") as f:
        venus_version = f.readline().strip()
    # show Venus OS version
    logger.info("Venus OS " + venus_version)

    # show the version of the driver
    logger.info("dbus-serialbattery v" + str(utils.DRIVER_VERSION))

    port = get_port()
    battery = {}

    # wait some seconds to be sure that the serial connection is ready
    # else the error throw a lot of timeouts
    sleep(16)

    if port.endswith("_Ble"):
        """
        Import ble classes only, if it's a ble port, else the driver won't start due to missing python modules
        This prevent problems when using the driver only with a serial connection
        """

        if len(sys.argv) <= 2:
            logger.error("Bluetooth address is missing in the command line arguments")
        else:
            ble_address = sys.argv[2]

            if port == "Jkbms_Ble":
                # noqa: F401 --> ignore flake "imported but unused" error
                from bms.jkbms_ble import Jkbms_Ble  # noqa: F401

            if port == "LltJbd_Ble":
                # noqa: F401 --> ignore flake "imported but unused" error
                from bms.lltjbd_ble import LltJbd_Ble  # noqa: F401

            class_ = eval(port)

            # do not remove ble_ prefix, since the dbus service cannot be only numbers
            testbms = class_(
                "ble_" + ble_address.replace(":", "").lower(), 9600, ble_address
            )

            if testbms.test_connection():
                logger.info("Connection established to " + testbms.__class__.__name__)
                battery[0] = testbms

    elif port.startswith("can"):
        """
        Import CAN classes only, if it's a can port, else the driver won't start due to missing python modules
        This prevent problems when using the driver only with a serial connection
        """
        from bms.daly_can import Daly_Can
        from bms.jkbms_can import Jkbms_Can

        # only try CAN BMS on CAN port
        supported_bms_types = [
            {"bms": Daly_Can, "baud": 250000},
            {"bms": Jkbms_Can, "baud": 250000},
        ]

        expected_bms_types = [
            battery_type
            for battery_type in supported_bms_types
            if battery_type["bms"].__name__ in utils.BMS_TYPE
            or len(utils.BMS_TYPE) == 0
        ]

        battery[0] = get_battery(port)

    else:
        # check if MODBUS_ADDRESSES is not empty
        if utils.MODBUS_ADDRESSES:
            for address in utils.MODBUS_ADDRESSES:
                checkbatt = get_battery(port, address)
                if checkbatt is not None:
                    battery[address] = checkbatt
                    logger.info(
                        "Successful battery connection at "
                        + port
                        + " and this Modbus address "
                        + str(address)
                    )
                else:
                    logger.warning(
                        "No battery connection at "
                        + port
                        + " and this Modbus address "
                        + str(address)
                    )
        # use default address
        else:
            battery[0] = get_battery(port)

    # check if at least one BMS was found
    battery_found = False

    for key_address in battery:
        if battery[key_address] is not None:
            battery_found = True

    if not battery_found:
        logger.error(
            "ERROR >>> No battery connection at "
            + port
            + (
                " and this Modbus addresses: " + ", ".join(utils.MODBUS_ADDRESSES)
                if utils.MODBUS_ADDRESSES
                else ""
            )
        )
        sys.exit(1)

    # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
    DBusGMainLoop(set_as_default=True)
    if sys.version_info.major == 2:
        gobject.threads_init()
    mainloop = gobject.MainLoop()

    # Get the initial values for the battery used by setup_vedbus
    helper = {}

    for key_address in battery:
        helper[key_address] = DbusHelper(battery[key_address], key_address)
        if not helper[key_address].setup_vedbus():
            logger.error(
                "ERROR >>> Problem with battery set up at "
                + port
                + (
                    " and this Modbus address: " + ", ".join(utils.MODBUS_ADDRESSES)
                    if utils.MODBUS_ADDRESSES
                    else ""
                )
            )
            sys.exit(1)

    # get first key from battery dict
    first_key = list(battery.keys())[0]

    # try using active callback on this battery (normally only used for Bluetooth BMS)
    if not battery[first_key].use_callback(lambda: poll_battery(mainloop)):
        # change poll interval if set in config
        if utils.POLL_INTERVAL is not None:
            battery[first_key].poll_interval = utils.POLL_INTERVAL

        logger.info(f"Polling data every {battery[first_key].poll_interval/1000:.3f} s")

        # if not possible, poll the battery every poll_interval milliseconds
        gobject.timeout_add(
            battery[first_key].poll_interval,
            lambda: poll_battery(mainloop),
        )

    # print log at this point, else not all data is correctly populated
    for key_address in battery:
        battery[key_address].log_settings()

    # check config, if there are any invalid values trigger "settings incorrect" error
    # and set the battery in error state to prevent chargin/discharging
    if not utils.validate_config_values():
        for key_address in battery:
            battery[key_address].state = 10
            battery[key_address].error_code = 119

    # use external current sensor if configured
    if (
        utils.EXTERNAL_CURRENT_SENSOR_DBUS_DEVICE is not None
        and utils.EXTERNAL_CURRENT_SENSOR_DBUS_PATH is not None
    ):
        for key_address in battery:
            battery[key_address].monitor_external_current()

    # Run the main loop
    try:
        mainloop.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
