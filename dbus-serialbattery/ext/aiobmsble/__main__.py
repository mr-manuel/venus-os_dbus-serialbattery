"""Example script for aiobmsble package usage.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import argparse
import asyncio
import getpass
import json
import logging
from typing import Any, Final

import aiooui
from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError

from aiobmsble import BMSInfo, BMSSample, __version__
from aiobmsble.basebms import BaseBMS
from aiobmsble.test_data import adv_dict_to_advdata
from aiobmsble.utils import bms_identify

_MIN_RSSI: Final[int] = -75

logging.basicConfig(
    format="%(levelname)s: %(message)s",
    level=logging.INFO,
)
logger: logging.Logger = logging.getLogger(__package__)


async def scan_devices() -> dict[str, tuple[BLEDevice, AdvertisementData]]:
    """Scan for BLE devices and return results."""
    logger.info("starting scan ...")
    try:
        scan_result: dict[str, tuple[BLEDevice, AdvertisementData]] = (
            await BleakScanner.discover(return_adv=True)
        )
    except BleakError as exc:
        logger.error("Could not scan for BT devices: %s", exc)
        return {}

    logger.debug(scan_result)
    logger.info("%i BT device(s) in range.", len(scan_result))
    return scan_result


async def _try_query(
    bms_cls: type[BaseBMS], ble_dev: BLEDevice, secret: str = ""
) -> bool:
    """Attempt to query the BMS once. Returns True on success, False on failure."""
    bms_inst: BaseBMS = (
        bms_cls(ble_device=ble_dev, secret=secret)
        if secret
        else bms_cls(ble_device=ble_dev)
    )
    logger.info("Querying BMS%s...", " with secret" if secret else "")

    try:
        async with bms_inst as bms:
            info: BMSInfo = await bms.device_info()
            data: BMSSample = await bms.async_update()
        logger.info("BMS info: %s", repr(info).replace(", '", ",\n\t'"))
        logger.info("BMS data: %s", repr(data).replace(", '", ",\n\t'"))
    except (BleakError, TimeoutError) as exc:
        logger.error(
            "Failed to query BMS%s: %s",
            " with secret" if secret else "",
            type(exc).__name__,
        )
        return False
    return True


async def log_advertisement_issues(adv_dict: dict[str, Any]) -> None:
    """Log potential issues with the advertisement data that may affect BMS detection.

    Args:
        adv_dict: Dictionary containing advertisement data fields.
    """

    if adv_dict.get("connectable", False) is False:
        logger.error(
            "Advertisement reports device is not actively connectable. This blocks communication with the device."
        )

    if adv_dict.get("rssi", -127) < _MIN_RSSI:
        logger.warning(
            "Advertisement RSSI %d dBm is below recommended level of %d dBm. Reduce distance to the device.",
            adv_dict.get("rssi", -127),
            _MIN_RSSI,
        )

    await aiooui.async_load()
    vendor: str | None = aiooui.get_vendor(adv_dict.get("source", ""))
    if vendor and vendor.startswith("Raspberry Pi"):
        logger.warning(
            "Advertisement is received via a Raspberry Pi device. This is likely to cause reception issues. "
            "See https://www.home-assistant.io/integrations/bluetooth/#cypress-based-adapters"
        )


async def identify_bms_from_json(json_str: str) -> None:
    """Identify BMS type from advertisement data provided as JSON string.

    Args:
        json_str: JSON string containing advertisement data with 'address' field.
    """
    try:
        adv_dict: dict[str, Any] = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse JSON: %s", exc)
        return

    # Map 'name' to 'local_name' if present
    if "name" in adv_dict and "local_name" not in adv_dict:
        adv_dict["local_name"] = adv_dict.pop("name")

    # Remove fields not used by AdvertisementData
    filtered_dict: dict[str, Any] = {
        k: v for k, v in adv_dict.items() if k in AdvertisementData._fields
    }

    try:
        # Convert dictionary to AdvertisementData
        adv_data: AdvertisementData = adv_dict_to_advdata(filtered_dict)
    except (AssertionError, IndexError, ValueError) as exc:
        logger.error("Failed to convert advertisement data: %s", exc)
        return

    await log_advertisement_issues(adv_dict)  # Log any potential issues

    # Identify BMS
    if (
        bms_cls_result := await bms_identify(adv_data, adv_dict.get("address", ""))
    ) is not None:
        logger.info("Detected BMS type: %s", bms_cls_result.bms_id())
        return

    logger.info("No matching BMS type found for the given advertisement data")


async def detect_bms() -> None:
    """Query a Bluetooth device based on the provided arguments."""

    scan_result: dict[str, tuple[BLEDevice, AdvertisementData]] = await scan_devices()
    for ble_dev, advertisement in scan_result.values():
        logger.info(
            "%s\nBT device '%s' (%s)\n\t%s",
            "-" * 72,
            ble_dev.name,
            ble_dev.address,
            repr(advertisement).replace(", ", ",\n\t"),
        )

        if bms_cls := await bms_identify(advertisement, ble_dev.address):
            bms_inst: BaseBMS = bms_cls(ble_device=ble_dev)
            logger.info("Found matching BMS type: %s", bms_inst.bms_id())

            if not await _try_query(bms_cls, ble_dev):
                if bms_cls.accept_secret:
                    secret: str = getpass.getpass(
                        f"Enter secret for {bms_cls.__name__}: "
                    )
                    await _try_query(bms_cls, ble_dev, secret)

    logger.info("done.")


def setup_logging(args: argparse.Namespace) -> None:
    """Configure logging based on command line arguments."""
    loglevel: Final[int] = logging.DEBUG if args.verbose else logging.INFO

    if args.logfile:
        file_handler = logging.FileHandler(args.logfile)
        file_handler.setLevel(loglevel)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s: %(message)s")
        )
        logger.addHandler(file_handler)

    logger.setLevel(loglevel)
    logger.info("%s version %s", __package__, __version__)


def main() -> None:
    """Entry point for the script to run the BMS detection."""
    parser = argparse.ArgumentParser(
        description="Reference script for 'aiobmsble' to show all recognized BMS in range or identify BMS from JSON advertisement."
    )
    parser.add_argument(
        "-j",
        "--json",
        type=str,
        help="JSON string containing advertisement data to identify BMS type",
    )
    parser.add_argument("-l", "--logfile", type=str, help="Path to the log file")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )

    args: argparse.Namespace = parser.parse_args()
    setup_logging(args)

    if args.json:
        asyncio.run(identify_bms_from_json(args.json))
    else:
        asyncio.run(detect_bms())


if __name__ == "__main__":
    main()  # pragma: no cover
