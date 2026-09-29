# -*- coding: utf-8 -*-
"""Opt-in wiring for the shared bleak-connection-manager (the bleak catcher).

Kept separate from utils_ble on purpose: the catcher rebinds
bleak.BleakClient process wide, and a module only picks the wrapper up
through its own `from bleak import BleakClient` if the install already
happened when it was imported. utils_ble and the BMS modules import bleak at
module scope, so dbus-serialbattery.py calls install_ble_connection_manager()
before importing any of them - which is why this module must not import
bleak, utils_ble or a BMS module at module scope itself.
"""

import inspect
import os

import utils
from utils import logger


def parse_link_caps(entries):
    """
    Split BLUETOOTH_CONNECTION_MANAGER_LINK_CAPS into {adapter: capacity}.

    Entries have the form ADAPTER:N with N a positive integer, the
    established-link capacity of that adapter, and ADAPTER an hciX name or
    the adapter's own MAC (the same identities BLUETOOTH_ADAPTERS accepts).
    The split is on the LAST colon, because a MAC is full of them.
    Malformed entries are logged and skipped rather than guessed at: a wrong
    cap silently gates connections.
    """
    caps = {}
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        adapter, sep, cap = entry.rpartition(":")
        adapter = adapter.strip()
        try:
            cap_value = int(cap.strip()) if sep else 0
        except ValueError:
            cap_value = 0
        if not adapter or cap_value <= 0:
            logger.warning(f"Ignoring malformed BLUETOOTH_CONNECTION_MANAGER_LINK_CAPS entry '{entry}'")
            continue
        caps[adapter] = cap_value
    return caps


def _accepts_kwarg(func, name):
    """Whether func takes `name` as a keyword, or takes **kwargs."""
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False
    if name in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def install_ble_connection_manager(address):
    """
    Install the bleak catcher for this battery's process, when enabled.

    Returns True when the catcher was installed. BLUETOOTH_ADAPTERS entries
    are handed over verbatim - the library understands the same MAC@hciX and
    plain hciX forms, with the same failure-driven walk contract for pinned
    devices - so one config key drives both the catcher and the plain
    backends identically.

    Keyed on the IMPORT OUTCOME, not on ble_stack's return value: whether the
    connection manager is importable right now is the fact, and
    ble_stack.shared_failure says why when a present install could not be.
    Every line here starts with "BLE coordination: " - the fleet's log watch
    anchors on it, so changing a sentence means telling running monitor first.

    A failed install is logged and swallowed: the catcher is coordination,
    and connecting uncoordinated beats not connecting at all.
    """
    import ble_stack

    shared_dir = utils.BLUETOOTH_CONNECTION_MANAGER_DIR

    if not utils.BLUETOOTH_CONNECTION_MANAGER:
        # Silent. A box that never asked for coordination has nothing to
        # report, and "loaded from" is what the fleet's watch reads as
        # coordination ACTIVE - which it is not with the catcher off.
        return False

    try:
        import bleak_connection_manager as _bcm
        from bleak_connection_manager import install_bleak_catcher

        validator = None
        if utils.BLUETOOTH_CONNECTION_MANAGER_VALIDATION:
            # weakest built-in validator, wrapped for chips that register
            # their vendor services after ServicesResolved: an empty GATT
            # table is a phantom link, and rejecting it here makes
            # bleak-retry-connector retry on the next radio instead of
            # handing the driver a client that fails on first read
            from bleak_connection_manager.validators import tolerate_late_gatt, validate_gatt_services

            validator = tolerate_late_gatt(validate_gatt_services)

        kwargs = dict(
            adapters=utils.BLUETOOTH_ADAPTERS,
            link_caps=parse_link_caps(utils.BLUETOOTH_CONNECTION_MANAGER_LINK_CAPS),
            wrap_scanner=utils.BLUETOOTH_CONNECTION_MANAGER_WRAP_SCANNER,
            validate_connection=validator,
        )

        # StartNotify policy. The shared install is whatever is on the box, so
        # check whether this one's install_bleak_catcher takes the parameter
        # before sending it: an older install would raise TypeError and lose
        # the catcher entirely. Older installs read the policy from the
        # environment instead.
        force = utils.BLUETOOTH_CONNECTION_MANAGER_FORCE_START_NOTIFY
        if _accepts_kwarg(install_bleak_catcher, "force_start_notify"):
            kwargs["force_start_notify"] = force
        else:
            os.environ["BCM_FORCE_START_NOTIFY"] = "true" if force else "false"
            logger.warning(
                f"BLE coordination: shared install at {shared_dir} predates the force_start_notify parameter; "
                "StartNotify policy passed through the legacy BCM_FORCE_START_NOTIFY environment"
            )

        install_bleak_catcher(f"dbus-serialbattery.{str(address).strip().lower().replace(':', '')}", **kwargs)

        # The PACKAGE directory, not the configured folder: it proves which
        # tree actually served the import, which is the whole question when a
        # box has both a shared install and this repo's ext/ble copies.
        package_dir = os.path.dirname(getattr(_bcm, "__file__", "") or "") or shared_dir
        logger.info(f"BLE coordination: bleak_connection_manager loaded from {package_dir}")
        # Seventh anchored line (running monitor, 2026-09-06): BCM's own INFO never
        # reaches this log (root stays at WARNING), so the policy that matters on
        # BlueZ 5.72 is stated once per life by the driver itself.
        adapters = list(utils.BLUETOOTH_ADAPTERS)
        pinned = sum(1 for a in adapters if "@" in a)
        logger.info(
            f"BLE coordination: catcher installed (force_start_notify={utils.BLUETOOTH_CONNECTION_MANAGER_FORCE_START_NOTIFY}, "
            f"adapters={len(adapters)} configured, {pinned} pinned)"
        )
        return True
    except ImportError:
        # No connection manager to be had. Three reasons, told apart so the
        # operator is sent to the right place.
        if ble_stack.shared_failure:
            # present, could not be imported - the install itself is the fault
            logger.error(f"BLE coordination: shared install at {shared_dir} is present but unusable, " f"running uncoordinated: {ble_stack.shared_failure}")
        elif not shared_dir:
            logger.warning(
                "BLE coordination: BLUETOOTH_CONNECTION_MANAGER is on but "
                "BLUETOOTH_CONNECTION_MANAGER_DIR is empty; running uncoordinated, no claims, no adapter routing, no card recovery"
            )
        else:
            logger.warning(f"BLE coordination: no shared install at {shared_dir}; " "running uncoordinated, no claims, no adapter routing, no card recovery")
        return False
    except Exception as e:
        # The install imported fine and the catcher refused to install - a bad
        # kwarg, a validator that raised, a bug in the catcher. Saying "the
        # install is unusable" here would send an operator to replace a shared
        # tree that is not the problem.
        logger.error(f"BLE coordination: catcher would not install from {shared_dir}, running uncoordinated: {repr(e)}")
        return False
