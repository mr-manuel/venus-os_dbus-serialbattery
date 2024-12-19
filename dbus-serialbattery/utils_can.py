# -*- coding: utf-8 -*-
import threading
import can
import subprocess
from utils import logger


class CanTransportInterface:
    can_message_cache_callback: callable = None
    can_bus = None


class CanReceiverThread(threading.Thread):

    _instances = {}

    def __init__(self, channel, bustype):

        # singleton for tuple
        if (channel, bustype) in CanReceiverThread._instances:
            raise Exception("Instance already exists for this configuration!")

        super().__init__()
        self.channel = channel
        self.bustype = bustype
        self.message_cache = {}  # cache can frames here
        self.cache_lock = threading.Lock()  # lock for thread safety
        CanReceiverThread._instances[(channel, bustype)] = self
        self.daemon = True
        self._running = True  # flag to control the running state
        self.bus = None

    @classmethod
    def get_instance(cls, channel, bustype):
        # check for instance
        if (channel, bustype) not in cls._instances:
            # create new one
            instance = cls(channel, bustype)
            instance.start()
        return cls._instances[(channel, bustype)]

    def run(self):
        self.bus = can.interface.Bus(channel=self.channel, bustype=self.bustype)

        # fetch the bitrate from the current port, for logging only
        bitrate = self.get_bitrate(self.channel)
        logger.info(f"Detected CAN Bus bitrate: {bitrate/1000:.0f} kbps")

        while self._running:
            message = self.bus.recv(timeout=1.0)  # timeout 1 sec

            if message is not None:
                with self.cache_lock:
                    # cache data with arbitration id as key
                    self.message_cache[message.arbitration_id] = message.data
                # print(f"[{self.channel}] Empfangen: ID={hex(message.arbitration_id)}, Daten={message.data}")
        self.bus = None

    def stop(self):
        self._running = False
        logger.info("CAN receiver stopped")

    def get_message_cache(self):
        # lock for thread safety
        with self.cache_lock:
            # return a copy of the current cache
            return dict(self.message_cache)

    @staticmethod
    def get_bitrate(channel):
        try:
            result = subprocess.run(["ip", "-details", "link", "show", channel], capture_output=True, text=True, check=True)
            for line in result.stdout.split("\n"):
                if "bitrate" in line:
                    return int(line.split("bitrate")[1].split()[0])
        except Exception as e:
            logger.error(f"Error fetching bitrate: {e}")
            raise
