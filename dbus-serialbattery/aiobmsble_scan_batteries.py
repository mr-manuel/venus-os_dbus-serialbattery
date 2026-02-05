import argparse
import asyncio
import logging
from typing import Final

import sys
import os

sys.path.insert(1, os.path.join(os.path.dirname(__file__), "ext"))
# export PYTHONPATH="/data/apps/dbus-serialbattery/ext:$PYTHONPATH"

from bleak import BleakScanner  # noqa: E402
from bleak.backends.device import BLEDevice  # noqa: E402
from bleak.backends.scanner import AdvertisementData  # noqa: E402
from bleak.exc import BleakError  # noqa: E402

from aiobmsble import BMSInfo, BMSSample  # noqa: E402
from aiobmsble.basebms import BaseBMS  # noqa: E402
from aiobmsble.utils import bms_identify  # noqa: E402

logging.basicConfig(
    format="%(levelname)s: %(message)s",
    level=logging.INFO,
)
logger: logging.Logger = logging.getLogger(__package__)


async def scan_devices() -> dict[str, tuple[BLEDevice, AdvertisementData]]:
    """Scan for BLE devices and return results."""
    logger.info("Starting BLE device scan ...")
    try:
        scan_result: dict[str, tuple[BLEDevice, AdvertisementData]] = await BleakScanner.discover(return_adv=True)
    except BleakError as exc:
        logger.error("Could not scan for BT devices: %s", exc)
        return {}

    logger.debug(scan_result)
    logger.info("%i BT device(s) in range.", len(scan_result))
    return scan_result


async def detect_bms() -> None:
    """Query a Bluetooth device based on the provided arguments."""

    scan_result: dict[str, tuple[BLEDevice, AdvertisementData]] = await scan_devices()
    battery_list: list[dict[str, str, str]] = []

    for ble_dev, advertisement in scan_result.values():
        logger.info("%s", "-" * 72)
        logger.info("BLE device found:")
        logger.info(f"|- Name: {ble_dev.name}")
        logger.info(f"|- Address: {ble_dev.address}")

        if bms_cls := await bms_identify(advertisement, ble_dev.address):
            bms_module = bms_cls.__module__  # e.g., 'aiobmsble.bms.jikong_bms'
            bms_type = bms_module.split(".")[-1]  # 'jikong_bms'

            bms_inst: BaseBMS = bms_cls(ble_device=ble_dev)
            battery_list.append({"name": ble_dev.name, "address": ble_dev.address, "bms_name": bms_inst.bms_id(), "bms_class": bms_type})

            logger.info(">>> Found matching BMS type: %s", bms_inst.bms_id())
            logger.debug("Querying BMS ...")
            try:
                async with bms_inst as bms:
                    info: BMSInfo = await bms.device_info()
                    data: BMSSample = await bms.async_update()

                logger.info(
                    "BMS info: %s",
                    (
                        repr(dict(sorted(info.items()))).replace("{", "\n\t").replace("}", "").replace("'", '"').replace(', "', ',\n\t"')
                        if info
                        else "Nothing received from BMS"
                    ),
                )
                logger.info(
                    "BMS data: %s",
                    (
                        repr(dict(sorted(data.items()))).replace("{", "\n\t").replace("}", "").replace("'", '"').replace(', "', ',\n\t"')
                        if data
                        else "Nothing received from BMS"
                    ),
                )

            except (BleakError, TimeoutError) as exc:
                logger.error("Failed to query BMS: %s", type(exc).__name__)
        else:
            logger.info(">>> No matching BMS type found for this device.")

    logger.debug("done.")

    if battery_list:
        print("\nAdd this to your /data/apps/dbus-serialbattery/config.ini:\n")
        print("BLUETOOTH_BMS = " + ", ".join([f"aiobmsble_{b['bms_class']} {b['address']}" for b in battery_list]) + "\n")
    else:
        print("\nNo supportedBMS devices found in range.\n")


def setup_logging(args: argparse.Namespace) -> None:
    """Configure logging based on command line arguments."""
    loglevel: Final[int] = logging.DEBUG if args.verbose else logging.INFO

    if args.logfile:
        file_handler = logging.FileHandler(args.logfile)
        file_handler.setLevel(loglevel)
        file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s: %(message)s"))
        logger.addHandler(file_handler)

    logger.setLevel(loglevel)


def main() -> None:
    """Entry point for the script to run the BMS detection."""
    parser = argparse.ArgumentParser(description="Reference script for 'aiobmsble' to show all recognized BMS in range.")
    parser.add_argument("-l", "--logfile", type=str, help="Path to the log file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")

    setup_logging(parser.parse_args())

    asyncio.run(detect_bms())


if __name__ == "__main__":
    main()  # pragma: no cover
