"""Example script for aiobmsble package usage.

Project: aiobmsble, https://pypi.org/p/aiobmsble/
License: Apache-2.0, http://www.apache.org/licenses/
"""

import argparse
import asyncio
import logging
from typing import Final

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError

from aiobmsble import BMSInfo, BMSSample
from aiobmsble.basebms import BaseBMS
from aiobmsble.utils import bms_identify

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
            logger.info("Querying BMS ...")
            try:
                async with bms_inst as bms:
                    info: BMSInfo = await bms.device_info()
                    data: BMSSample = await bms.async_update()
                logger.info("BMS info: %s", repr(info).replace(", '", ",\n\t'"))
                logger.info("BMS data: %s", repr(data).replace(", '", ",\n\t'"))
            except (BleakError, TimeoutError) as exc:
                logger.error("Failed to query BMS: %s", type(exc).__name__)

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


def main() -> None:
    """Entry point for the script to run the BMS detection."""
    parser = argparse.ArgumentParser(
        description="Reference script for 'aiobmsble' to show all recognized BMS in range."
    )
    parser.add_argument("-l", "--logfile", type=str, help="Path to the log file")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )

    setup_logging(parser.parse_args())

    asyncio.run(detect_bms())


if __name__ == "__main__":
    main()  # pragma: no cover
