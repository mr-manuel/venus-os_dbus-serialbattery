# -*- coding: utf-8 -*-
import threading
import can
import subprocess
from utils import logger
from time import sleep, time


class CanTransportInterface:
    can_message_cache_callback: callable = None
    can_bus = None


class CanReceiverThread(threading.Thread):

    _instances = {}

    def __init__(self, channel, bustype):

        # singleton for tuple
        if (channel, bustype) in CanReceiverThread._instances:
            raise Exception("Instance already exists for this configuration!")

        super().__init__(name=f"CanReceiverThread-{channel}")
        self.channel = channel
        self.bustype = bustype
        self.message_cache = {}  # cache can frames here
        self.cache_lock = threading.Lock()  # lock for thread safety
        CanReceiverThread._instances[(channel, bustype)] = self
        self.daemon = True
        self._running = True  # flag to control the running state
        self.can_bus = None
        self.initial_interface_state = self.get_link_status(self.channel)

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
        """
        # setup up the CAN interface, if not already UP
        self.setup_can(self.channel)
        self.can_bus = can.interface.Bus(channel=self.channel, bustype=self.bustype)

        # fetch the bitrate from the current port, for logging only
        bitrate = self.get_bitrate(self.channel)
        logger.info(f"Detected CAN Bus bitrate: {bitrate/1000:.0f} kbps")

        # timestamp of last received message
        last_message_time_stamp = 0

        while self._running:
            link_status = self.get_link_status(self.channel)
            if link_status:
                try:
                    message = self.can_bus.recv(timeout=1.0)  # wait for max 1 second to receive message

                    if message is not None:
                        last_message_time_stamp = int(time())
                        with self.cache_lock:

                            # daly hack: cell voltage messages are sent with same id, so use frame id additionally
                            if message.arbitration_id == 0x18954001:
                                message.arbitration_id = message.arbitration_id + message.data[0]

                            # cache data with arbitration id as key
                            self.message_cache[message.arbitration_id] = message.data
                            # message_cache_temp[message.arbitration_id] = message.data

                        logger.debug(f"[{self.channel}] Received: ID={hex(message.arbitration_id)}, Daten={message.data}")

                except can.exceptions.CanOperationError as e:
                    logger.debug(f"CAN Bus {self.channel}: {e}")
                    self.message_cache = {}
                    sleep(1)
            else:
                logger.error(">>> ERROR: CAN Bus interface is down")
                self.message_cache = {}
                sleep(1)

            # self.message_cache.update(message_cache_temp)

            if int(time()) - last_message_time_stamp > 2 and self.message_cache:
                logger.debug(f"CAN Bus {self.channel} has not received any messages in the last 2 seconds")
                self.message_cache = {}
                sleep(2)

        self.stop()

    def stop(self) -> None:
        """
        Stop the CAN receiver thread
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

    @staticmethod
    def get_link_status(channel: str) -> bool:
        """
        Check if the CAN interface is up

        :param channel: CAN interface name
        :return: True if interface is up, False otherwise
        """
        result = subprocess.run(["ip", "link", "show", channel], capture_output=True, text=True, check=True)
        if "UP" in result.stdout:
            return True
        else:
            return False

    @staticmethod
    def get_bitrate(channel: str) -> int:
        """
        Fetch the bitrate of the CAN interface

        :param channel: CAN interface name
        :return: bitrate in bps
        """
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
