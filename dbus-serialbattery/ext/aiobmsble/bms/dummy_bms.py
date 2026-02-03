"""Module to support Dummy BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSInfo, BMSSample, MatcherPattern
from aiobmsble.basebms import BaseBMS


class BMS(BaseBMS):
    """Dummy BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Dummy Manufacturer",
        "default_model": "dummy model",
    }  # TODO: fill correct manufacturer/model
    # _HEAD: Final[bytes] = b"\x55"  # beginning of frame
    # _TAIL: Final[bytes] = b"\xAA"  # end of frame
    # _FRAME_LEN: Final[int] = 10  # length of frame, including SOF and checksum

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize BMS."""
        super().__init__(ble_device, keep_alive)

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [{"local_name": "dummy", "connectable": True}]  # TODO: define matcher

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return (normalize_uuid_str("0000"),)  # TODO: change service UUID here!

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "0000"  # TODO: change RX characteristic UUID here!

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "0000"  # TODO: change TX characteristic UUID here!

    async def _fetch_device_info(self) -> BMSInfo:
        """Fetch the device information via BLE."""
        return BMSInfo(
            default_manufacturer="Dummy manufacturer", default_model="Dummy BMS"
        )  # TODO: implement query code or remove function to query service 0x180A

    # @staticmethod
    # def _raw_values() -> frozenset[BMSValue]:
    #     return frozenset({"runtime"})  # never calculate, e.g. runtime

    def _notification_handler(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Handle the RX characteristics notify event (new data arrives)."""
        # self._log.debug("RX BLE data: %s", data)

        # *******************************************************
        # TODO: Do things like checking correctness of frame here
        # and store it into a instance variable, e.g. self._frame
        # in case the frame is fragmented.
        # Below are some examples of how to do it
        # Have a look at the BMS base class for function to use,
        # take a look at other implementations for more  details
        # *******************************************************

        # if not data.startswith(BMS._HEAD):
        #     self._log.debug("incorrect SOF")
        #     return

        # if (crc := crc_sum(self._frame[:-1])) != self._frame[-1]:
        #     self._log.debug("invalid checksum 0x%X != 0x%X", self._frame[-1], crc)
        #     return

        # Do an immutable copy of the assembled (data) frame and notify _await_msg()
        # self._msg = bytes(self._frame)
        # self._msg_event.set()

    async def _async_update(self) -> BMSSample:
        """Update battery status information."""
        self._log.debug("replace with command to UUID %s", BMS.uuid_tx())
        # await self._await_msg(b"<some_command>")

        # TODO: parse data from self._frame here

        return {
            "voltage": 12,
            "current": 1.5,
            "temperature": 27.182,
        }  # TODO: fixed values, replace parsed data
