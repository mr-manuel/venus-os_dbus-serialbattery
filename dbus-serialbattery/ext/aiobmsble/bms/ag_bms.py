"""Module to support AG Automotive (E&J) BMS.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from aiobmsble import BMSInfo, MatcherPattern
from aiobmsble.bms.ej_bms import BMS as EJBMS


class BMS(EJBMS):
    """AG Automotive (E&J) BMS implementation."""

    INFO: BMSInfo = {
        "default_manufacturer": "AG Automotive",
        "default_model": "AG Power Lithium",
    }

    @staticmethod
    def matcher_dict_list() -> list[MatcherPattern]:
        """Provide BluetoothMatcher definition."""
        return [
            MatcherPattern(
                local_name="AG???L*",
                manufacturer_id=21320,
                connectable=True,
            )
        ]

    @staticmethod
    def uuid_services() -> tuple[str, ...]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return ("00008000-0000-1000-8000-57616c6b697a",)

    @staticmethod
    def uuid_rx() -> str:
        """Return 128-bit UUID of characteristic that provides notification/read property."""
        return "00008002-0000-1000-8000-57616c6b697a"

    @staticmethod
    def uuid_tx() -> str:
        """Return 128-bit UUID of characteristic that provides write property."""
        return "00008001-0000-1000-8000-57616c6b697a"
