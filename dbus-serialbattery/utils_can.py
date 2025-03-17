# -*- coding: utf-8 -*-
import threading
import can
import subprocess
from utils import logger
from time import sleep, time


class CanTransportInterface:
    """
    Class to manage the CAN transport interface
    """

    can_message_cache_callback: callable = None
    can_bus = None


class CanReceiverThread(threading.Thread):
    """
    Class to receive CAN messages on a separate thread
    """

    _instances = {}

    def __init__(self, channel, bustype):

        # singleton for tuple
        if (channel, bustype) in CanReceiverThread._instances:
            raise Exception("Instance already exists for this configuration!")

        super().__init__(name=f"CanReceiverThread-{channel}")
        self.channel = channel
        self.bustype = bustype
        self._current_time = int(time())
        self.message_cache = {}  # cache can frames here
        self.cache_lock = threading.Lock()  # lock for thread safety
        self._last_received_time = {}  # track last received time for each arbitration ID
        self._last_cache_clean_time = 0  # last time the cached was cleaned (deleted too old values)
        CanReceiverThread._instances[(channel, bustype)] = self
        self.daemon = True
        self._running = True  # flag to control the running state
        self.can_bus = None
        self.can_initialised = threading.Event()
        self._link_status_cache = {"timestamp": 0, "result": None}
        self.initial_interface_state = self.get_link_status()

    @classmethod
    def get_instance(cls, channel, bustype) -> "CanReceiverThread":
        """
        Get the instance of the CAN receiver thread for the given channel

        :param channel: CAN interface name
        :param bustype: CAN interface type
        :return: instance of the CAN receiver thread
        """
        # check for instance
        if (channel, bustype) not in cls._instances:
            # create new one
            instance = cls(channel, bustype)
            instance.start()
        return cls._instances[(channel, bustype)]

    def run(self) -> None:
        """
        Start the CAN receiver thread

        :return: None
        """
        # setup up the CAN interface, if not already UP
        self.setup_can(self.channel)
        self.can_bus = can.interface.Bus(channel=self.channel, bustype=self.bustype)

        # fetch the bitrate from the current port, for logging only
        bitrate = self.get_bitrate(self.channel)
        logger.info(f"Detected CAN Bus bitrate: {bitrate/1000:.0f} kbps")

        # timestamp of last received message
        last_message_time_stamp = 0
        self.can_initialised.set()

        while self._running:
            self._current_time = int(time())

            link_status = self.get_link_status()
            self.clear_old_cache_entries()

            if link_status:
                try:
                    message = self.can_bus.recv(timeout=1.0)  # wait for max 1 second to receive message

                    if message is not None:
                        last_message_time_stamp = self._current_time
                        with self.cache_lock:

                            # daly hack: cell voltage messages are sent with same id, so use frame id additionally as offset for cmd byte
                            if message.arbitration_id & 0xFFFFFF00 == 0x18954000:
                                message.arbitration_id = message.arbitration_id + 0x100000 + (message.data[0] << 16)
                                # 18954001 -> 18A64001  frame 1
                                # 18954001 -> 18A74001  frame 2...

                            # cache data with arbitration id as key
                            self.message_cache[message.arbitration_id] = message.data
                            self._last_received_time[message.arbitration_id] = last_message_time_stamp  # update last received time

                        logger.debug(f"[{self.channel}] Received: ID={hex(message.arbitration_id)}, Daten={message.data}")

                except can.exceptions.CanOperationError as e:
                    logger.debug(f"CAN Bus {self.channel}: {e}")
                    self.message_cache = {}
                    self._last_received_time = {}
                    sleep(1)
            else:
                logger.error(">>> ERROR: CAN Bus interface is down")
                self.message_cache = {}
                self._last_received_time = {}
                sleep(1)

            if self._current_time - last_message_time_stamp > 2 and self.message_cache:
                logger.debug(f"CAN Bus {self.channel} has not received any messages in the last 2 seconds")
                self.message_cache = {}
                self._last_received_time = {}
                sleep(2)

        self.stop()

    # Clear cache entries for defined arbitration IDs if they have not been received for 5 seconds.
    def clear_old_cache_entries(self) -> None:
        """
        Clear cache entries for defined arbitration IDs if they have not been received for 5 seconds.

        :return: None
        """
        # do this once a second to reduce load
        if self._last_cache_clean_time + 1 > self._current_time:
            return

        # update time
        self._last_cache_clean_time = self._current_time

        with self.cache_lock:
            for arb_id in list(self._last_received_time.keys()):
                if self._current_time - self._last_received_time[arb_id] > 5:
                    del self.message_cache[arb_id]
                    del self._last_received_time[arb_id]
                    logger.debug(f"[{self.channel}] Cleared cache for arbitration ID {hex(arb_id)} due to timeout")

    def stop(self) -> None:
        """
        Stop the CAN receiver thread

        :return: None
        """
        self._running = False
        # shutdown the CAN bus
        if self.can_bus is not None:
            self.can_bus.shutdown()
        self.can_bus = None
        logger.info("CAN receiver stopped")

        if self.initial_interface_state is False:
            # bring down the interface
            logger.info(f"Bringing down CAN interface {self.channel}")
            subprocess.run(["ip", "link", "set", f"{self.channel}", "down"], capture_output=True, text=True, check=True)

    def get_message_cache(self) -> dict:
        """
        Get the current cache of received CAN messages

        :return: dict of received CAN messages
        """
        # lock for thread safety
        with self.cache_lock:
            # return a copy of the current cache
            return dict(self.message_cache)

    def get_link_status(self) -> bool:
        """
        Check if the CAN interface is up. Cache the result for 1 second.

        :param channel: CAN interface name
        :return: True if interface is up, False otherwise
        """

        # Check if cached result is still valid
        if self._link_status_cache["timestamp"] + 1 > self._current_time:
            return self._link_status_cache["result"]

        result = subprocess.run(["ip", "link", "show", self.channel], capture_output=True, text=True, check=True)
        status = "UP" in result.stdout

        # Update the cache
        self._link_status_cache["timestamp"] = self._current_time
        self._link_status_cache["result"] = status

        return status

    @staticmethod
    def get_bitrate(channel: str) -> int:
        """
        Fetch the bitrate of the CAN interface
        :param channel: CAN interface name
        :return: bitrate in bps
        """
        # vcan doesn't support bitrate, so return static value
        if channel.startswith("vcan"):
            return 250000
        try:
            result = subprocess.run(["ip", "-details", "link", "show", channel], capture_output=True, text=True, check=True)
            for line in result.stdout.split("\n"):
                if "bitrate" in line:
                    return int(line.split("bitrate")[1].split()[0])
        except Exception as e:
            logger.error(f"Error fetching bitrate: {e}")
            raise

    @staticmethod
    def setup_can(channel: str, bitrate: int = 250, force: bool = False) -> None:
        """
        Bring up the CAN interface

        :param channel: CAN interface name
        :param bitrate: bitrate in kbps, default is 250 kbps
        :param force: force to bring up/reset the interface, default is False
        """
        try:
            # check if CAN interface exists and is down
            result = subprocess.run(["ip", "link", "show", f"{channel}"], capture_output=True, text=True, check=True)

            if not force and "DOWN" not in result.stdout:
                logger.debug(f"Interface {channel} is already up")
                return True

            if result.returncode != 0:
                logger.error(result.stderr)
                return False

            # bring down the interface
            subprocess.run(["ip", "link", "set", f"{channel}", "down"], capture_output=True, text=True, check=True)

            # bring up the interface with the given bitrate
            result = subprocess.run(
                ["ip", "link", "set", f"{channel}", "type", "can", "bitrate", f"{bitrate * 1000}"],
                capture_output=True,
                text=True,
                check=True,
            )
            result.check_returncode()

            result = subprocess.run(["ip", "link", "set", f"{channel}", "up"], capture_output=True, text=True, check=True)
            result.check_returncode()

            logger.info(f"CAN Bus {channel} is up with bitrate {bitrate} kbps")

        except Exception as e:
            logger.error(f"Error bringing up {channel}: {e}")
            raise
