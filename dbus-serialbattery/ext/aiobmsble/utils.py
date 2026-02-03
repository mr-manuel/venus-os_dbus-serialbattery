"""Utility/Support functions for aiobmsble.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import asyncio
from fnmatch import translate
from functools import cache
import importlib
import pkgutil
import re
from types import ModuleType
from typing import Final, cast

from bleak.backends.scanner import AdvertisementData

from aiobmsble import MatcherPattern
from aiobmsble.basebms import BaseBMS
import aiobmsble.bms

_MODULE_POSTFIX: Final[str] = "_bms"


def _advertisement_matches(
    matcher: MatcherPattern, adv_data: AdvertisementData, mac_addr: str
) -> bool:
    """Determine whether the given advertisement data matches the specified pattern.

    Args:
        matcher (MatcherPattern): A dictionary containing the matching criteria.
            Possible keys include:
            - "local_name" (str): A pattern supporting Unix shell-style wildcards to match
            - "manufacturer_data_start" (bytes): A byte sequence that the data should start with.
            - "manufacturer_id" (int): A manufacturer ID to match.
            - "oui" (str): Organizationally Unique Identifier of BD_ADDR (first 3 bytes)
            - "service_data_uuid" (str): A specific service data UUID to match.
            - "service_uuid" (str): A specific service 128-bit UUID to match.

        adv_data (AdvertisementData): An object containing the advertisement data to be checked.
        mac_addr (str): Bluetooth device address in the format: "00:11:22:aa:bb:cc"

    Returns:
        bool: True if the advertisement data matches the specified pattern, False otherwise.

    """
    if (
        service_uuid := matcher.get("service_uuid")
    ) and service_uuid not in adv_data.service_uuids:
        return False

    if (
        service_data_uuid := matcher.get("service_data_uuid")
    ) and service_data_uuid not in adv_data.service_data:
        return False

    if (oui := matcher.get("oui")) and not mac_addr.lower().startswith(oui.lower()[:8]):
        return False

    if (manufacturer_id := matcher.get("manufacturer_id")) is not None:
        if manufacturer_id not in adv_data.manufacturer_data:
            return False

        if manufacturer_data_start := matcher.get("manufacturer_data_start"):
            if not adv_data.manufacturer_data[manufacturer_id].startswith(
                bytes(manufacturer_data_start)
            ):
                return False

    return not (
        (local_name := matcher.get("local_name"))
        and not re.compile(translate(local_name)).match(adv_data.local_name or "")
    )


@cache
def load_bms_plugins() -> set[ModuleType]:
    """Discover and load all available Battery Management System (BMS) plugin modules.

    This function scans the 'aiobmsble/bms' directory for all Python modules,
    dynamically imports each discovered module, and returns a set containing
    the imported module objects required to end with "_bms".

    Returns:
        set[ModuleType]: A set of imported BMS plugin modules.

    Raises:
        ImportError: If a module cannot be imported.
        OSError: If the plugin directory cannot be accessed.

    """
    return {
        importlib.import_module(f"aiobmsble.bms.{module_name}")
        for _, module_name, _ in pkgutil.iter_modules(aiobmsble.bms.__path__)
        if module_name.endswith(_MODULE_POSTFIX)
    }


async def bms_cls(name: str) -> type[BaseBMS] | None:
    """Return the BMS class that is defined by the name argument.

    Args:
        name (str): The name of the BMS type (filename of the module)

    Returns:
        type[BaseBMS] | None: If the BMS class defined by name is found, None otherwise.

    """
    if not name.endswith(_MODULE_POSTFIX):
        return None
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    try:
        bms_module: ModuleType = await loop.run_in_executor(
            None, importlib.import_module, f"aiobmsble.bms.{name}"
        )
    except ModuleNotFoundError:
        return None

    return cast(type[BaseBMS], bms_module.BMS)


async def bms_matching(
    adv_data: AdvertisementData, mac_addr: str
) -> list[type[BaseBMS]]:
    """Return the BMS classes that match the given advertisement data.

    Currently the function returns at most one match, but this behaviour might change
    in the future to multiple entries, if BMSs cannot be distinguished uniquely using
    their Bluetooth advertisement / OUI (Organizationally Unique Identifier)

    Args:
        adv_data (AdvertisementData): The advertisement data to match against available BMS plugins.
        mac_addr (str): Bluetooth device address to check OUI against, format: "00:11:22:aa:bb:cc"

    Returns:
        list[type[BaseBMS]]: A list of matching BMS class(es) if found, an empty list otherwise.

    """
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    bms_plugins: set[ModuleType] = await loop.run_in_executor(None, load_bms_plugins)

    for bms_module in bms_plugins:
        if bms_supported(bms_module.BMS, adv_data, mac_addr):
            return [bms_module.BMS]
    return []


async def bms_identify(
    adv_data: AdvertisementData, mac_addr: str
) -> type[BaseBMS] | None:
    """Return the BMS classes that best matches the given advertisement data.

    Args:
        adv_data (AdvertisementData): The advertisement data to match against available BMS plugins.
        mac_addr (str): Bluetooth device address to check OUI against, format: "00:11:22:aa:bb:cc"

    Returns:
        type[BaseBMS] | None: The identified BMS class if a match is found, None otherwise

    """

    matching_bms: list[type[BaseBMS]] = await bms_matching(adv_data, mac_addr)
    return matching_bms[0] if matching_bms else None


def bms_supported(bms: BaseBMS, adv_data: AdvertisementData, mac_addr: str) -> bool:
    """Determine if the given BMS is supported based on advertisement data.

    Args:
        bms (BaseBMS): The BMS class to check.
        adv_data (AdvertisementData): The advertisement data to match against.
        mac_addr (str): Bluetooth device address to check OUI against, format: "00:11:22:aa:bb:cc"

    Returns:
        bool: True if the BMS is supported, False otherwise.

    """
    for matcher in bms.matcher_dict_list():
        if _advertisement_matches(matcher, adv_data, mac_addr):
            return True
    return False
