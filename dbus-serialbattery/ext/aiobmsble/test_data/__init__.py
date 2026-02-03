"""Test advertisements for aiobmsble package.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

from functools import cache
from importlib import resources
import json
from string import hexdigits
from typing import Any

from bleak.backends.scanner import AdvertisementData

type BmsAdvList = list[tuple[AdvertisementData, str, str, list[str]]]


def adv_dict_to_advdata(adv_dict: dict[str, Any]) -> AdvertisementData:
    """Generate an AdvertisementData instance from a JSON dictionary."""
    ADVERTISEMENT_DATA_DEFAULTS: dict[str, Any] = {
        "local_name": None,
        "manufacturer_data": {},
        "service_data": {},
        "service_uuids": [],
        "rssi": -127,
        "platform_data": ((),),
        "tx_power": None,
    }

    if "manufacturer_data" in adv_dict:
        adv_dict["manufacturer_data"] = {
            int(k): bytes.fromhex(v) if isinstance(v, str) else v
            for k, v in adv_dict["manufacturer_data"].items()
        }
    if "service_data" in adv_dict:
        adv_dict["service_data"] = {
            k: bytes.fromhex(v) if isinstance(v, str) else v
            for k, v in adv_dict["service_data"].items()
        }
    if "platform_data" in adv_dict:
        pdata = adv_dict.get("platform_data", [])
        assert isinstance(
            pdata[0], str
        ), "first entry of platform_data needs to be string."
        parts = pdata[0].split(":")
        assert len(parts) == 6 and all(
            len(part) == 2 and all(c in hexdigits for c in part) for part in parts
        ), "first entry of platform_data only accepts MAC addresses"
        adv_dict["platform_data"] = tuple(pdata)

    return AdvertisementData(**(ADVERTISEMENT_DATA_DEFAULTS | adv_dict))


@cache
def bms_advertisements(bms_filter: str | None = None) -> BmsAdvList:
    """Provide all available BMS advertisements from test data directory.

    Load *_bms.json files from the packaged test data directory.
    If no type is given, all available advertisemetns (any type) will be returned.

    Args:
        bms_filter (str|None): BMS type for which the advertisements should be returned.

    Returns:
        BmsAdvList: List of tuples containing advertisement, mac_addr, bms type,
        and a list of comments, i.e. list[tuple[AdvertisementData, str, list[str]]]

    """
    all_data: BmsAdvList = []

    for resource in resources.files(__package__).iterdir():
        if bms_filter and not resource.name.startswith(bms_filter):
            continue
        if not resource.name.endswith("_bms.json"):
            continue
        with resource.open("r", encoding="UTF-8") as f:
            raw_data: Any = json.load(f)
            assert isinstance(raw_data, list)

            for entry in raw_data:
                assert isinstance(entry, dict)
                assert {"advertisement", "type"}.issubset(set(entry.keys()))
                adv: AdvertisementData = adv_dict_to_advdata(entry["advertisement"])
                mac_addr: str = (
                    adv.platform_data[0]
                    if isinstance(adv.platform_data, tuple)
                    and isinstance(adv.platform_data[0], str)
                    else ""
                )
                bms_type: str = entry["type"]
                comments: list[str] = entry["_comments"]

                assert isinstance(adv, AdvertisementData)
                assert isinstance(bms_type, str)
                assert isinstance(comments, list)
                assert all(isinstance(c, str) for c in comments)
                assert resource.name == f"{bms_type}.json"

                all_data.append((adv, mac_addr, bms_type, comments))
    return all_data


def ignore_advertisements() -> BmsAdvList:
    """Provide a list of advertisements that shall not be identified as a valid BMS.

    Load ignore.json files from the packaged test data directory.

    Returns:
        BmsAdvList: List of tuples containing advertisement, reason why not to detect,
        and a list of comments, i.e. list[tuple[AdvertisementData, str, list[str]]]

    """
    data: BmsAdvList = []

    with (
        resources.files(__package__)
        .joinpath("ignore.json")
        .open("r", encoding="UTF-8") as f
    ):
        raw_data: Any = json.load(f)
        assert isinstance(raw_data, list)

        for entry in raw_data:
            assert isinstance(entry, dict)
            assert {"advertisement", "reason"}.issubset(set(entry.keys()))
            adv: AdvertisementData = adv_dict_to_advdata(entry["advertisement"])
            mac_addr: str = adv.platform_data[0] if "platform" in adv else ""
            reason: str = entry["reason"]
            comments: list[str] = entry["_comments"]

            assert isinstance(adv, AdvertisementData)
            assert isinstance(reason, str)
            assert isinstance(comments, list)
            assert all(isinstance(c, str) for c in comments)

            data.append((adv, mac_addr, reason, comments))

    return data
