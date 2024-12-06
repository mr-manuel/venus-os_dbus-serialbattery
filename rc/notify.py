#!/usr/bin/env python3

from os.path import basename
import argparse
import time
import os
import sys
from fcntl import ioctl

import lcddriver

VERSION = 0.1
CLOCK_TICK_RATE = 1193180
KIOCSOUND = 0x4B2F


def beep(console_fd, frequency=440):
    if os.path.exists("/sys/class/gpio/gpio35/value") and os.uname().nodename == "ccgx" and frequency > 0:
        with open("/sys/class/gpio/gpio35/value", "w") as beep_file:
            beep_file.write("1")
        time.sleep(0.2)
        with open("/sys/class/gpio/gpio35/value", "w") as beep_file:
            beep_file.write("0")
    else:
        period = 0 if frequency == 0 else CLOCK_TICK_RATE // frequency
        ioctl(console_fd, KIOCSOUND, period)


def notify(lcd, message, no_beep=False):
    if lcd:
        if len(message) > 16:
            # split_index = message.rfind(" ", 0, 16)
            # if split_index == -1:
            #     split_index = 16
            split_index = 16
            part1 = message[:split_index].strip()
            part2 = message[split_index:].strip()
            lcd.display_string(part1, 1)
            lcd.display_string(part2, 2)
        else:
            lcd.display_string(message, 1)

    if lcd:
        lcd.on = True
    console_fd = os.open("/dev/tty0", os.O_RDONLY | os.O_NOCTTY)

    if not no_beep:
        beep(console_fd, frequency=440)
    time.sleep(1)
    if lcd:
        lcd.on = False
    if not no_beep:
        beep(console_fd, frequency=0)
    time.sleep(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-beep", help="Do not beep, sets count to 1", default=False, action="store_true")
    parser.add_argument("--count", help="Number of notifications (beeps/blinks) to do", default=3)
    parser.add_argument("--lcd", help="Path to lcd device, default /dev/lcd", default="/dev/lcd")
    parser.add_argument("--message", help="Message to show on the lcd, default Victron Energy", default="Victron Energy")
    parser.add_argument("--version", help="Print the version to stdout", default=False, action="store_true")
    args = parser.parse_args()

    if args.version:
        print("{} v{}".format(basename(sys.argv[0]), VERSION))
        return

    if os.path.exists(args.lcd):
        try:
            lcd = lcddriver.Lcd(args.lcd)
        except Exception:
            raise SystemExit(f"Unable to open {args.lcd}")
    else:
        lcd = None

    if lcd:
        lcd.clear()

    if args.no_beep:
        args.count = 1

    for i in range(int(args.count)):
        notify(lcd, args.message or "", args.no_beep)

    if lcd:
        lcd.clear()


if __name__ == "__main__":
    main()
