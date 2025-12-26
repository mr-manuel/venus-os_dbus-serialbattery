# -*- coding: utf-8 -*-

# NOTES
# Added by https://github.com/mr-manuel

# avoid importing wildcards, remove unused imports
from battery import Battery, Cell
from typing import Callable
from utils import (
    logger,
    MQTT_BROKER_ADDRESS,
    MQTT_BROKER_PORT,
    MQTT_TLS_ENABLED,
    MQTT_TLS_PATH_TO_CA,
    MQTT_TLS_INSECURE,
    MQTT_USERNAME,
    MQTT_PASSWORD,
)
from time import sleep, time
from gi.repository import GLib
import paho.mqtt.client as mqtt
import os
import sys
import json

# add path to velib_python
sys.path.insert(1, os.path.join(os.path.dirname(os.path.dirname(__file__)), "ext", "velib_python"))
from ve_utils import get_vrm_portal_id  # noqa: E402


class Generic_Mqtt(Battery):
    def __init__(self, port, baud, address):
        super(Generic_Mqtt, self).__init__(port, baud, address)
        self.type = self.BATTERYTYPE
        # Exclude history values from calculation if they are provided from the BMS
        self.history.exclude_values_to_calculate = []
        self.mqtt_topic = address
        self.mqtt_connected = False
        self._new_data_callback = None
        """
        When _new_data_callback() is called this function chain will be executed:
        ```
        dbus-serialbattery.py: poll_battery()
        |- dbushelper.py: publish_battery()
            |- dbushelper.py: battery.refresh_data()
            |- dbushelper.py: publish_dbus()
        ```
        """

        self.battery_data_last_success = 0
        """
        Timestamp when the battery data was last successfully received.
        """

    BATTERYTYPE = "Generic MQTT"

    def test_connection(self):
        """
        call a function that will connect to the battery, send a command and retrieve the result.
        The result or call should be unique to this BMS. Battery name or version, etc.
        Return True if success, False for failure
        """
        result = False
        try:
            # MQTT setup
            client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id="DbusSerialbattery_" + get_vrm_portal_id(),
            )
            client.on_disconnect = self.on_disconnect
            client.on_connect = self.on_connect
            client.on_message = self.on_message

            # check tls and use settings, if provided
            if MQTT_TLS_ENABLED:
                logger.info("MQTT client: TLS is enabled")

                if MQTT_TLS_PATH_TO_CA != "":
                    logger.info('MQTT client: TLS: custom ca "%s" used' % MQTT_TLS_PATH_TO_CA)
                    client.tls_set(MQTT_TLS_PATH_TO_CA, tls_version=2)
                else:
                    client.tls_set(tls_version=2)

                if MQTT_TLS_INSECURE:
                    logger.info("MQTT client: TLS certificate server hostname verification disabled")
                    client.tls_insecure_set(True)

            # check if username and password are set
            if MQTT_USERNAME != "" and MQTT_PASSWORD != "":
                logger.info('MQTT client: Using username "%s" and password to connect' % MQTT_USERNAME)
                client.username_pw_set(username=MQTT_USERNAME, password=MQTT_PASSWORD)

            # connect to broker
            logger.info(f"MQTT client: Connecting to broker {MQTT_BROKER_ADDRESS} on port {MQTT_BROKER_PORT}")
            client.connect(host=MQTT_BROKER_ADDRESS, port=int(MQTT_BROKER_PORT))
            client.loop_start()

            # wait to receive first data
            i = 0
            timeout = 30
            while self.battery_data_last_success == 0:
                if i % 12 != 0 or i == 0:
                    logger.info("Waiting 5 seconds for receiving first data...")
                else:
                    logger.warning("Waiting since %s seconds for receiving first data..." % str(i * 5))

                # check if timeout was exceeded
                if timeout != 0 and timeout <= (i * 5):
                    logger.error("Timeout of %i seconds exceeded, since no new MQTT message was received in this time." % timeout)
                    return False

                sleep(5)
                i += 1

            return True

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

    def connection_name(self):
        return "MQTT: " + self.mqtt_topic

    def use_callback(self, callback: Callable) -> bool:
        """
        Register a callback function that will be called, when new data is available from the battery.
        The callback will be called in the main thread via GLib.idle_add to be thread
        safe with dbus and GLib.
        """
        self._new_data_callback = callback
        return True

    def _run_callback_once(self):
        """
        Helper to run the callback only once in the main thread via GLib.idle_add.
        """
        if self._new_data_callback is not None:
            self._new_data_callback()
        return False

    def get_settings(self):
        """
        After successful connection get_settings() will be called to set up the battery
        Set all values that only need to be set once
        Return True if success, False for failure
        """
        # this is done on_message when receiving the first MQTT message

        return True

    def refresh_data(self):
        """
        call all functions that will refresh the battery data.
        This will be called for every iteration (1 second)
        Return True if success, False for failure
        """
        # this is done on_message when receiving a new MQTT message
        refresh_data_timeout = 5 + 1
        if (int(time()) - self.battery_data_last_success) > refresh_data_timeout:
            logger.debug("Timeout of %i seconds exceeded, since no new MQTT message was received in this time." % refresh_data_timeout)
            return False

        return True

    # MQTT requests
    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            logger.info("MQTT client: Connected to MQTT broker!")
            self.mqtt_connected = True
            client.subscribe(self.mqtt_topic)
        else:
            logger.error("MQTT client: Failed to connect, return code %d\n", reason_code)

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        logger.warning("MQTT client: Got disconnected")
        if reason_code != 0:
            logger.warning("MQTT client: Unexpected MQTT disconnection. Will auto-reconnect")
        else:
            logger.warning("MQTT client: reason_code value:" + str(reason_code))

        while not self.mqtt_connected:
            try:
                logger.warning(f"MQTT client: Trying to reconnect to broker {MQTT_BROKER_ADDRESS} on port {MQTT_BROKER_PORT}")
                client.connect(host=MQTT_BROKER_ADDRESS, port=MQTT_BROKER_PORT)
                self.mqtt_connected = True
            except Exception as err:
                logger.error(f"MQTT client: Error in retrying to connect with broker ({MQTT_BROKER_ADDRESS}:{MQTT_BROKER_PORT}): {err}")
                logger.error("MQTT client: Retrying in 15 seconds")
                self.mqtt_connected = False
                sleep(15)

    def on_message(self, client, userdata, msg):
        try:

            # get JSON from topic
            if msg.topic == self.mqtt_topic:
                if msg.payload != "" and msg.payload != b"":
                    jsonpayload = json.loads(msg.payload)
                    logger.debug("MQTT client: Received new MQTT message on topic " + msg.topic)
                    logger.debug("MQTT payload: " + str(msg.payload))

                    # List of settings: (value name, type, is_mandatory)
                    battery_values = [
                        # mandatory settings
                        ("cell_count", int, True),
                        ("capacity", float, True),
                        ("serial_number", str, True),
                        # optional settings
                        ("max_battery_charge_current", float, False),
                        ("max_battery_discharge_current", float, False),
                        ("custom_field", str, False),  # Example optional field
                        ("max_battery_voltage_bms", float, False),
                        ("min_battery_voltage_bms", float, False),
                        ("production", str, False),
                        ("hardware_version", str, False),
                        # status data
                        ("voltage", float, True),
                        ("current", float, True),
                        ("soc", float, True),
                        ("temperature_1", float, True),
                        ("charge_fet", bool, True),
                        ("discharge_fet", bool, True),
                        # optional status data
                        ("capacity_remain", float, False),
                        ("soh", float, False),
                        ("temperature_2", float, False),
                        ("temperature_3", float, False),
                        ("temperature_4", float, False),
                        ("temperature_mos", float, False),
                        ("balance_fet", bool, False),
                        # cell data
                        ("cells", dict, True),
                        # protection data
                        ("protection", dict, False),
                        # history data
                        ("history", dict, False),
                    ]

                    missing_values = []
                    for value, value_type, is_mandatory in battery_values:
                        if value == "cell_count" and value in jsonpayload:
                            if self.cell_count is None:
                                # set cell count only once
                                if isinstance(jsonpayload[value], int):
                                    self.cell_count = int(jsonpayload[value])
                                else:
                                    logger.error(
                                        f"Received JSON MQTT message has incorrect type for value '{value}'. "
                                        + f"Expected int, got {type(jsonpayload[value]).__name__}."
                                    )
                                    missing_values.append(value)
                            elif self.cell_count != int(jsonpayload[value]):
                                logger.error(
                                    f"Received JSON MQTT message has different cell count ({jsonpayload[value]}) than previously set ({self.cell_count})."
                                )
                                logger.error("Restart the driver to apply the new cell count.")
                                return

                        if value == "cells" and value in jsonpayload:
                            """
                            sample payload
                            "cells": [
                                {"voltage": 3.65, "balance": false},
                                {"voltage": 3.66, "balance": false},
                                {"voltage": 3.64, "balance": false},
                                {"voltage": 3.67, "balance": false}
                                ...
                            ]
                            """
                            # set cell data
                            cells_data_all = jsonpayload["cells"]

                            # Accept both dict (with string keys) and list (index = cell number)
                            if isinstance(cells_data_all, list):
                                # check cell count
                                if len(cells_data_all) != self.cell_count:
                                    logger.error(
                                        f"Cell count ({len(cells_data_all)}) is not matching the number of provided cells ({self.cell_count}) in MQTT message."
                                    )
                                    missing_values.append(value)
                                else:
                                    # prepare self.cells if not already done
                                    if len(self.cells) != self.cell_count:
                                        self.cells = []
                                        for _ in range(self.cell_count):
                                            self.cells.append(Cell(False))

                                    for cell_number in range(len(cells_data_all)):
                                        cell_data = cells_data_all[cell_number]
                                        if isinstance(cell_data, dict):
                                            # set voltage
                                            if "voltage" in cell_data:
                                                if isinstance(cell_data["voltage"], (int, float)):
                                                    self.cells[cell_number].voltage = float(cell_data["voltage"])
                                                else:
                                                    logger.error(
                                                        f"Received JSON MQTT message has incorrect type for cell '{cell_number}' voltage. "
                                                        + f"Expected float, got {type(cell_data['voltage']).__name__}."
                                                    )
                                                    missing_values.append(value)
                                            else:
                                                logger.error(f"Cell voltage is missing for cell '{cell_number}' in MQTT message.")
                                                missing_values.append(value)

                                            # set balance status if provided
                                            if "balance" in cell_data:
                                                if isinstance(cell_data["balance"], bool):
                                                    self.cells[cell_number].balance = cell_data["balance"]
                                                else:
                                                    logger.error(
                                                        f"Received JSON MQTT message has incorrect type for cell '{cell_number}' balance. "
                                                        + f"Expected bool, got {type(cell_data['balance']).__name__}."
                                                    )
                                                    missing_values.append(value)
                                            # balance status is optional, so no error if missing

                        # update sub-dictionaries
                        elif (value == "protection" or value == "history") and value_type == dict:
                            if value in jsonpayload and isinstance(jsonpayload[value], dict):
                                target_obj = getattr(self, value, None)
                                if target_obj is not None:
                                    for sub_key, sub_val in jsonpayload[value].items():
                                        if hasattr(target_obj, sub_key):
                                            setattr(target_obj, sub_key, sub_val)

                        elif value in jsonpayload:
                            # check type for numeric values
                            if value_type in (int, float):
                                if isinstance(jsonpayload[value], (int, float)):
                                    setattr(self, value, value_type(jsonpayload[value]))
                                else:
                                    logger.error(
                                        f"Received JSON MQTT message has incorrect type for value '{value}'. "
                                        + f"Expected {value_type.__name__}, got {type(jsonpayload[value]).__name__}."
                                    )
                                    missing_values.append(value)
                            # check type for strict types
                            else:
                                if isinstance(jsonpayload[value], value_type):
                                    setattr(self, value, jsonpayload[value])
                                else:
                                    logger.error(
                                        f"Received JSON MQTT message has incorrect type for value '{value}'. "
                                        + f"Expected {value_type.__name__}, got {type(jsonpayload[value]).__name__}."
                                    )
                                    missing_values.append(value)
                        elif is_mandatory:
                            missing_values.append(value)

                    if missing_values:
                        logger.error(f"Received JSON MQTT message is missing mandatory values: {', '.join(missing_values)}.")
                        logger.debug("MQTT payload: " + str(msg.payload)[1:])
                        return

                    # update timestamp of last successful data reception
                    self.battery_data_last_success = int(time())

                    # Schedule the callback in the main thread using GLib.idle_add.
                    # This is necessary because dbus and GLib are not thread-safe, and calling dbus methods
                    # from the MQTT thread can cause segmentation faults. By using idle_add, we ensure that
                    # all dbus updates happen safely in the main event loop.
                    if self._new_data_callback is not None:
                        GLib.idle_add(self._run_callback_once)

                else:
                    logger.warning("Received JSON MQTT message was empty and therefore it was ignored")
                    logger.debug("MQTT payload: " + str(msg.payload)[1:])

        except TypeError as e:
            logger.error("Received message is not valid. Check the README and sample payload. %s" % e)
            logger.debug("MQTT payload: " + str(msg.payload)[1:])

        except ValueError as e:
            logger.error("Received message is not a valid JSON. Check the README and sample payload. %s" % e)
            logger.debug("MQTT payload: " + str(msg.payload)[1:])

        except Exception:
            exception_type, exception_object, exception_traceback = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            print(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
            logger.debug("MQTT payload: " + str(msg.payload)[1:])
            (
                exception_type,
                exception_object,
                exception_traceback,
            ) = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
