import threading
import can
from typing import Dict


class CanReceiverThread(threading.Thread):

    _instances = {}

    def __init__(self, channel, bustype, bitrate):

        # singleton for tupel
        if (channel, bustype, bitrate) in CanReceiverThread._instances:
            raise Exception("Instance already exists for this configuration!")

        super().__init__()
        self.channel = channel
        self.bustype = bustype
        self.bitrate = bitrate
        self.message_cache = {}  # cache can frames here
        self.cache_lock = threading.Lock()  # lock for thread safety
        CanReceiverThread._instances[(channel, bustype, bitrate)] = self
        self.daemon = True

    @classmethod
    def get_instance(cls, channel, bustype, bitrate):
        # check for instance
        if (channel, bustype, bitrate) not in cls._instances:
            # create new one
            instance = cls(channel, bustype, bitrate)
            instance.start()
        return cls._instances[(channel, bustype, bitrate)]

    def run(self):
        bus = can.interface.Bus(channel=self.channel, bustype=self.bustype, bitrate=self.bitrate)

        while True:
            message = bus.recv(timeout=1.0)  # timeout 1 sec

            if message is not None:
                with self.cache_lock:
                    # cache data with arbitration id as key
                    self.message_cache[message.arbitration_id] = message.data
                # print(f"[{self.channel}] Empfangen: ID={hex(message.arbitration_id)}, Daten={message.data}")

    def get_message_cache(self):
        # lock for thread safety
        with self.cache_lock:
            # return a copy of the current cache
            return dict(self.message_cache)
