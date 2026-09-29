# -*- coding: utf-8 -*-
"""Pin the ban on bleak's AcquireNotify opt-out (use_start_notify=False).

On 2026-08-26 a fleet-wide bluetoothd crash storm on a Cerbo GX was traced to
a BlueZ 5.72 use-after-free in gatt-client.c. The freed object, notify_io, is
created ONLY when a client subscribes via the D-Bus "AcquireNotify" method.
Vendored bleak picks AcquireNotify only when a caller passes
bluez={"use_start_notify": False} to start_notify and the characteristic
advertises NotifyAcquired; the default is StartNotify, which never creates a
notify_io. dbus-serialbattery was safe through the storm purely because no
first-party code passes the opt-out — another driver on the same box adopted
it to chase an empty-payload symptom and became the trigger, so the
temptation is proven real. These tests turn that unstated default into an
asserted invariant.

Both directions scan raw file text rather than importing anything: bleak is
not installed on the machines this suite runs on (test_utils_ble.py stubs it
in sys.modules for the same reason), and raw text is deliberate — even a
commented-out opt-out is a hit, because the cheap false positive is worth
never missing a real one. This file is the one exclusion from its own scan:
the docstring has to name the banned key to explain the ban.
"""

import os
import re

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DRIVER_DIR = os.path.join(REPO_ROOT, "dbus-serialbattery")
VENDORED_EXT_DIR = os.path.join(DRIVER_DIR, "ext")
VENDORED_BLUEZ_CLIENT = os.path.join(VENDORED_EXT_DIR, "bleak", "backends", "bluezdbus", "client.py")

NEEDLE = "use_start_notify"
THIS_FILE = os.path.abspath(__file__)

WHY_BANNED = (
    "AcquireNotify creates BlueZ's notify_io, the object double-freed in the bluez 5.72 "
    "use-after-free that produced the 2026-08 bluetoothd crash storm. Use StartNotify (bleak's "
    "default), which never creates a notify_io and delivers real payloads on this hardware."
)


def _first_party_python_files():
    """Every *.py under dbus-serialbattery/ except ext/ (vendored), plus tests/."""
    for top in (DRIVER_DIR, os.path.join(REPO_ROOT, "tests")):
        for dirpath, dirnames, filenames in os.walk(top):
            if os.path.abspath(dirpath).startswith(VENDORED_EXT_DIR):
                dirnames[:] = []
                continue
            for filename in sorted(filenames):
                if filename.endswith(".py"):
                    path = os.path.join(dirpath, filename)
                    if os.path.abspath(path) != THIS_FILE:
                        yield path


def test_no_first_party_code_opts_out_of_start_notify():
    offenders = []
    for path in _first_party_python_files():
        with open(path, encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, start=1):
                if NEEDLE in line:
                    offenders.append("%s:%d: %s" % (os.path.relpath(path, REPO_ROOT), lineno, line.strip()))
    assert not offenders, "Found %d reference(s) to the banned bleak notify opt-out (%s):\n  %s\n%s" % (
        len(offenders),
        NEEDLE,
        "\n  ".join(offenders),
        WHY_BANNED,
    )


def test_vendored_bleak_still_defaults_to_start_notify():
    """A re-vendor of bleak with a flipped default would reintroduce AcquireNotify silently."""
    with open(VENDORED_BLUEZ_CLIENT, encoding="utf-8") as f:
        source = f.read()
    default_pattern = re.compile(r"\.get\(\s*['\"]" + NEEDLE + r"['\"]\s*,\s*(?P<default>[A-Za-z_][A-Za-z0-9_]*)\s*\)")
    match = default_pattern.search(source)
    assert match is not None, (
        "The vendored bleak's notify-method selection (bluez.get(%r, True)) was not found in %s. "
        "The selection logic moved or was rewritten; update this guard so it keeps pinning the "
        "StartNotify default. %s" % (NEEDLE, os.path.relpath(VENDORED_BLUEZ_CLIENT, REPO_ROOT), WHY_BANNED)
    )
    assert (
        match.group("default") == "True"
    ), "The vendored bleak defaults %s to %s instead of True, which makes AcquireNotify the " "default notify method. %s" % (
        NEEDLE,
        match.group("default"),
        WHY_BANNED,
    )
