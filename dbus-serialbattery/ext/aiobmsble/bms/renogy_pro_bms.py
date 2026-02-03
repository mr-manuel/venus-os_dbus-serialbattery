"""Module to support Renogy Pro BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from aiobmsble import BMSDp, BMSInfo, MatcherPattern
from aiobmsble.bms.renogy_bms import BMS as RenogyBMS


class BMS(RenogyBMS):
    """Renogy Pro battery class implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "Renogy",
        "default_model": "BT battery pro",
    }
    _HEAD: bytes = b"\xff\x03"  # SOP, read fct (x03)
    FIELDS: tuple[BMSDp, ...] = (
        BMSDp("voltage", 5, 2, False, lambda x: x / 10),
        BMSDp("current", 3, 2, True, lambda x: x / 10),
        BMSDp("design_capacity", 11, 4, False, lambda x: x // 1000),
        BMSDp("cycle_charge", 7, 4, False, lambda x: x / 1000),
        BMSDp("cycles", 15, 2, False),
        # RNGC type seems to have cycles in wrong byte order
        # https://github.com/patman15/BMS_BLE-HA/issues/596
    )

    def __init__(self, ble_device: BLEDevice, keep_alive: bool = True) -> None:
        """Initialize private BMS members."""
        super().__init__(ble_device, keep_alive)
        self._char_write_handle: int = -1

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": pattern,
                "manufacturer_id": 0xE14C,
                "connectable": True,
            }
            for pattern in ("RNGRBP*", "RNGC*")
        ]

    async def _init_connection(
        self, char_notify: BleakGATTCharacteristic | int | str | None = None
    ) -> None:
        """Initialize RX/TX characteristics and protocol state."""
        char_notify_handle: int = -1
        self._char_write_handle = -1
        assert char_notify is None, "char_notify not used for Renogy Pro BMS"

        for service in self._client.services:
            self._log.debug(
                "service %s (#%i): %s",
                service.uuid,
                service.handle,
                service.description,
            )
            for char in service.characteristics:
                self._log.debug(
                    "characteristic %s (#%i): %s",
                    char.uuid,
                    char.handle,
                    char.properties,
                )
                if (
                    service.uuid == BMS.uuid_services()[0]
                    and char.uuid == normalize_uuid_str(BMS.uuid_tx())
                    and any(
                        prop in char.properties
                        for prop in ("write", "write-without-response")
                    )
                ):
                    self._char_write_handle = char.handle
                if (
                    service.uuid == BMS.uuid_services()[1]
                    and char.uuid == normalize_uuid_str(BMS.uuid_rx())
                    and "notify" in char.properties
                ):
                    char_notify_handle = char.handle

        if char_notify_handle == -1 or self._char_write_handle == -1:
            self._log.debug("failed to detect characteristics.")
            await self._client.disconnect()
            raise ConnectionError(f"Failed to detect characteristics from {self.name}.")
        self._log.debug(
            "using characteristics handle #%i (notify), #%i (write).",
            char_notify_handle,
            self._char_write_handle,
        )

        await super()._init_connection(char_notify_handle)

    async def _await_msg(
        self,
        data: bytes,
        char: int | str | None = None,
        wait_for_notify: bool = True,
        max_size: int = 0,
    ) -> None:
        """Send data to the BMS and wait for valid reply notification."""

        await super()._await_msg(
            data, self._char_write_handle, wait_for_notify, max_size
        )
