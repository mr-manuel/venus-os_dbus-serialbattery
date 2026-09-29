import threading
import asyncio
import logging
import os
import re
import subprocess
import sys
import time
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakCharacteristicNotFoundError, BleakError
from time import sleep
from utils import (
    logger,
    BLUETOOTH_ADAPTER_PIN_STRICT,
    BLUETOOTH_ADAPTERS,
    BLUETOOTH_CONNECTION_BACKEND,
    BLUETOOTH_FORCE_RESET_BLE_STACK,
    capture_raw_data,
)

# What the kernel reports for a controller it cannot talk to - a dead onboard
# UART radio answers with this forever, and it must never be written back to
# the config as if it were an identity.
UNKNOWN_ADAPTER_MAC = "00:00:00:00:00:00"


def parse_adapter_entries(entries):
    """
    Split BLUETOOTH_ADAPTERS into pinned devices and the shared pool.

    Entries of the form DEVICE@ADAPTER pin that device to that adapter, with
    no fallback to the shared pool. Repeating a device pins it to several
    adapters in order: the first is used for every connection attempt, the
    rest are tried only when it cannot be resolved there. That keeps a
    battery on a known good radio while leaving it somewhere to go if that
    radio fails, without returning it to a pool shared with other devices.

    ADAPTER may be an hciX name or the adapter's own MAC. Prefer the MAC:
    hciX numbering is assigned in probe order and a reboot or USB reset can
    renumber the dongles, silently re-pointing a pin at different hardware
    while everything still appears to work. The adapter's MAC does not move.

    Entries without an "@" form the pool used by every device that is not
    pinned, and may likewise be hciX names or adapter MACs.
    Returns (pins, pool), with pins keyed by upper case MAC address and each
    value a list of adapters in priority order.
    """
    pins = {}
    pool = []
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        if "@" in entry:
            mac, _, adapter = entry.rpartition("@")
            mac = mac.strip().upper()
            adapter = adapter.strip()
            if mac and adapter:
                adapters = pins.setdefault(mac, [])
                if adapter not in adapters:
                    adapters.append(adapter)
            else:
                logger.warning(f"Ignoring malformed BLUETOOTH_ADAPTERS entry '{entry}'")
        else:
            pool.append(entry)
    return pins, pool


BLUETOOTH_ADAPTER_PINS, BLUETOOTH_ADAPTER_POOL = parse_adapter_entries(BLUETOOTH_ADAPTERS)


def adapters_for(address):
    """Adapters pinned to this device in priority order, or None if unpinned."""
    pins = BLUETOOTH_ADAPTER_PINS.get(str(address).strip().upper())
    return list(pins) if pins else None


MAC_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def is_adapter_mac(entry):
    """Whether a configured adapter entry names a MAC rather than an hciN."""
    return bool(MAC_PATTERN.match(str(entry).strip()))


# Adapter identity is read from the kernel, never over D-Bus, and cached for
# this long. Short enough that a replugged or reset card is noticed, long
# enough that a battery reconnecting in a tight loop does not spawn a
# subprocess per attempt.
ADAPTER_IDENTITY_TTL = 30.0
_adapter_identity_cache = {"at": 0.0, "adapters": {}}


def _adapters_from_sysfs():
    """{hciN: MAC} from /sys/class/bluetooth, or {} if the kernel has no
    address attribute there - which is the case on Venus OS."""
    adapters = {}
    try:
        names = [n for n in os.listdir("/sys/class/bluetooth") if n.startswith("hci")]
    except OSError:
        return {}
    for name in names:
        try:
            with open(f"/sys/class/bluetooth/{name}/address") as f:
                mac = f.read().strip().upper()
        except OSError:
            continue
        if mac:
            adapters[name] = mac
    return adapters


def _adapters_from_hciconfig():
    """{hciN: MAC} by parsing one bare hciconfig call.

    One call returns the whole table, so this spawns a single subprocess
    however many adapters the box has - the production GX device has seven.
    """
    try:
        result = subprocess.run(["hciconfig"], capture_output=True, text=True, timeout=5)
    except Exception as e:
        logger.debug(f"hciconfig unavailable: {repr(e)}")
        return {}
    adapters = {}
    name = None
    for line in result.stdout.splitlines():
        match = re.match(r"^(hci\d+):", line)
        if match:
            name = match.group(1)
            continue
        if name:
            found = re.search(r"BD Address:\s*([0-9A-Fa-f:]{17})", line)
            if found:
                adapters[name] = found.group(1).upper()
                name = None
    return adapters


def bluez_adapters():
    """
    {hciN: MAC} for the adapters the kernel currently exposes, or {} for
    "no answer".

    hciN names are not stable identities: a USB reset or reboot renumbers
    them, and an adapter a battery is configured for can stop existing while
    its number lives on pointing at different hardware. The adapter's own MAC
    is stable, so configuration can name that instead and be resolved here.

    Read from the kernel and NOT over D-Bus, deliberately. This runs on the
    BLE thread - resolve_adapter -> adapters_in_attempt_order ->
    _select_adapter is the connect path - and asking BlueZ from here crashed
    the driver. dbus-python's DBusGMainLoop supports only the DEFAULT GLib
    main context, so a connection opened on this thread still registers its
    watches and dispatch source on the MAIN thread's loop, and closing it
    here frees the connection while that loop is still using it. Two core
    dumps showed the main thread dying inside dbus_connection_dispatch, once
    on a freed hash table and once on a freed mutex, and the same process
    also aborted in malloc; one use-after-free with three presentations.
    dbus-python belongs on the main thread, for velib.

    sysfs first because it is a plain file read; hciconfig as the fallback
    because Venus OS kernels expose no address attribute under
    /sys/class/bluetooth at all, so on the GX devices the fallback is what
    actually runs. An all-zeros address is what a dead or unserved
    controller reports and never identifies anything, so it is dropped
    rather than cached as an identity.
    """
    now = time.monotonic()
    if _adapter_identity_cache["adapters"] and now - _adapter_identity_cache["at"] < ADAPTER_IDENTITY_TTL:
        return dict(_adapter_identity_cache["adapters"])
    adapters = _adapters_from_sysfs() or _adapters_from_hciconfig()
    adapters = {name: mac for name, mac in adapters.items() if mac != UNKNOWN_ADAPTER_MAC}
    if adapters:
        _adapter_identity_cache["at"] = now
        _adapter_identity_cache["adapters"] = dict(adapters)
    return adapters


def bluez_present_adapters():
    """Adapter names BlueZ currently exposes, or an empty set for "no answer"."""
    return set(bluez_adapters())


def resolve_adapter(entry, adapters=None):
    """
    A configured adapter entry as the hciN name to hand to bleak, or None.

    An hciN entry is returned unchanged - it is already what bleak wants, and
    configuration written that way keeps working. A MAC entry is looked up in
    live BlueZ state, which is the whole point of allowing MACs: the dongle
    keeps its address across the renumbering that invalidates its name. A MAC
    that matches nothing present returns None, meaning that radio is gone.
    """
    entry = str(entry).strip()
    if not is_adapter_mac(entry):
        return entry
    if adapters is None:
        adapters = bluez_adapters()
    target = entry.upper()
    for name, mac in adapters.items():
        if mac and mac.upper() == target:
            return name
    return None


def adapter_identities(adapters=None):
    """
    {configured hciN entry: its MAC} for every name that resolves right now.

    Only names are reported: an entry already written as a MAC needs no
    translation, and a card whose MAC cannot be read (an all-zeros address
    is the kernel's answer for a dead or unserved controller) is left alone
    rather than pinned to a value that means "unknown".
    """
    if adapters is None:
        adapters = bluez_adapters()
    configured = []
    for pinned in BLUETOOTH_ADAPTER_PINS.values():
        configured.extend(pinned)
    configured.extend(BLUETOOTH_ADAPTER_POOL)
    identities = {}
    for entry in configured:
        entry = str(entry).strip()
        if not entry or is_adapter_mac(entry):
            continue
        mac = adapters.get(entry)
        if mac and mac.upper() != UNKNOWN_ADAPTER_MAC:
            identities[entry] = mac.upper()
    return identities


def pin_adapters_by_mac(path=None, adapters=None):
    """
    Rewrite hciN adapter names in the user config to the MACs they proved to
    be, leaving a comment above each line recording what happened.

    hciN numbering is assigned in probe order, so the name a battery was
    configured for can come back pointing at a different radio after a
    reboot or a USB reset - and because any radio in range can reach the
    battery, it still connects and nothing looks wrong while the
    per-battery separation the config exists to express is gone. Writing
    the MAC back makes the intent durable.

    Line oriented rather than parsed and re-emitted, so comments, spacing
    and every unrelated setting survive untouched. Already-commented lines
    are left alone. Best effort throughout: a config that cannot be read or
    written is not worth failing a connection over, and selection resolves
    the same either way.
    """
    identities = adapter_identities(adapters)
    if not identities:
        return False
    if path is None:
        from utils import custom_config_file_path

        path = custom_config_file_path
    try:
        with open(path) as f:
            lines = f.readlines()
    except OSError as e:
        logger.debug(f"adapter config rewrite: cannot read {path}: {repr(e)}")
        return False
    out = []
    changed = False
    for line in lines:
        stripped = line.strip()
        replaced = line
        hits = []
        if stripped and not stripped.startswith((";", "#")):
            for entry, mac in identities.items():
                # word boundary, so hci1 is never matched inside hci10
                pattern = rf"(?<![0-9A-Za-z]){re.escape(entry)}(?![0-9A-Za-z])"
                if re.search(pattern, replaced):
                    replaced = re.sub(pattern, mac, replaced)
                    hits.append((entry, mac))
        if hits:
            indent = line[: len(line) - len(line.lstrip())]
            for entry, mac in hits:
                out.append(f"{indent}; {entry} was detected as {mac} and written back - adapter numbers move, MACs do not\n")
            changed = True
        out.append(replaced)
    if not changed:
        return False
    try:
        tmp = f"{path}.tmp"
        with open(tmp, "w") as f:
            f.writelines(out)
        os.replace(tmp, path)
    except OSError as e:
        logger.warning(f"Could not write adapter MACs back to {path}: {repr(e)}")
        return False
    for entry, mac in identities.items():
        logger.info(f"Adapter {entry} was detected as {mac} and written back to the config")
    return True


# bleak warns "Failed to cancel connection (<path>): ServiceUnknown" whenever
# it tears down a client while bluetoothd is not on the bus - which is every
# reconnect during a bluetoothd restart, exactly when the log is being read.
# The condition is already handled: the object is gone, so the link is gone,
# which is what the teardown wanted. Filtered by message on the one logger
# that emits it rather than by raising that logger's threshold, because the
# threshold also hides bleak's genuine connect diagnostics from the same
# window.
BLEAK_CLIENT_LOGGER = "bleak.backends.bluezdbus.client"
BLEAK_SILENCED_MESSAGE = "Failed to cancel connection"
BLEAK_SILENCED_REASON = "ServiceUnknown"


class _BluezGoneFilter(logging.Filter):
    """Drop bleak's teardown warning for a BlueZ that has gone away."""

    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:
            return True
        return not (BLEAK_SILENCED_MESSAGE in message and BLEAK_SILENCED_REASON in message)


def silence_bluez_gone_warning(logger_name=BLEAK_CLIENT_LOGGER):
    """Install the filter once; returns it so a caller can remove it again."""
    target = logging.getLogger(logger_name)
    for existing in target.filters:
        if isinstance(existing, _BluezGoneFilter):
            return existing
    installed = _BluezGoneFilter()
    target.addFilter(installed)
    return installed


silence_bluez_gone_warning()


def describe_adapter(name, adapters=None):
    """
    An adapter as "hciN (MAC)", for a log line a human has to act on.

    Both halves earn their place. hciN is what the running system calls it
    right now and what an operator types; the MAC is what the card will
    still be called after the next reboot renumbers it. "(MAC unresolved)"
    is not cosmetic - it means identity could not be read, so MAC pins are
    not being honoured, and it is worth noticing in a log.
    """
    if not name:
        return "unknown"
    if adapters is None:
        adapters = bluez_adapters()
    mac = adapters.get(name)
    return f"{name} ({mac})" if mac else f"{name} (MAC unresolved)"


# Devices currently known to have lost their MAC pins, so the warning is
# emitted on the transition into that state rather than on every attempt: a
# battery reconnecting on the 6 s ramp would otherwise repeat it ten times a
# minute, which is how a real warning stops being read.
_unpinned_devices = set()


def adapters_in_attempt_order(address, present=None):
    """
    Adapters to try for this battery, best first, as hciN names.

    A battery uses its own configured adapters, or the shared pool if it has
    none; either list is walked by index, advancing only after a failed
    connection attempt. Entries are resolved against live BlueZ state, so a
    battery whose radio was renumbered away reaches it again under its new
    name (MAC entries) or moves on to its next adapter (hciN entries) rather
    than asking for a name that no longer resolves.

    When nothing resolves the answer differs by entry kind, deliberately. An
    unresolvable hciN list is returned unfiltered, preserving the long
    standing contract that refusing to attempt a connection is worse than
    trying an adapter that may not be there. An unresolvable MAC list returns
    empty, so the caller falls back to the system default adapter: a MAC is
    not a name bleak can use, and passing one through would fail every
    attempt instead of degrading.
    """
    configured = adapters_for(address) or list(BLUETOOTH_ADAPTER_POOL)
    if not configured:
        return []
    if present is None:
        present = bluez_adapters()
    # a bare set of names is accepted as well as the {name: MAC} mapping, so
    # callers that only know what exists keep working - MAC entries simply
    # cannot resolve against it, which is the honest answer
    adapters = present if isinstance(present, dict) else {name: "" for name in present}
    resolved = _resolve_all(configured, adapters)
    if resolved:
        return resolved
    names = [entry for entry in configured if not is_adapter_mac(entry)]
    if len(names) < len(configured):
        # Nothing the battery named is here. Fall back to every adapter that
        # IS, rather than to nothing - returning an empty list hands the
        # battery to bleak's system default, which is one particular card
        # chosen by BlueZ for reasons unrelated to this driver. On a box
        # whose scanners have their own allowlist, that card may be one the
        # device is never discovered on, so the battery fails not-found
        # forever while a working radio sits unused two entries away.
        # Observed on a swapped dongle: eighteen hours unreachable with a
        # scanned adapter present the whole time.
        names = names or sorted(adapters, key=_adapter_sort_key)
        _warn_pins_dropped(address, configured, names)
    return names


def _resolve_all(configured, adapters):
    """Configured entries as the hciN names they name right now, in order."""
    resolved = []
    for entry in configured:
        name = resolve_adapter(entry, adapters)
        if name and (not adapters or name in adapters) and name not in resolved:
            resolved.append(name)
    return resolved


def configured_adapter_present(address, present=None):
    """
    Whether any adapter this battery names is here right now.

    Shares _resolve_all with the selection, so the question "may this battery
    connect" and the answer "over which adapter" can never disagree - the
    whole point of a strict pin is that the two are the same decision.

    A battery that names no adapters is trivially satisfied: it never asked
    for a particular radio, so there is nothing to wait for.
    """
    configured = adapters_for(address) or list(BLUETOOTH_ADAPTER_POOL)
    if not configured:
        return True
    if present is None:
        present = bluez_adapters()
    adapters = present if isinstance(present, dict) else {name: "" for name in present}
    return bool(_resolve_all(configured, adapters))


def _adapter_sort_key(name):
    """hci ordering by number, so hci9 comes before hci10 rather than after."""
    match = re.match(r"^hci(\d+)$", str(name))
    return (0, int(match.group(1))) if match else (1, 0)


def _warn_pins_dropped(address, configured, names):
    """Say so when a battery stops being pinned to the adapters it names.

    Reaching here means no configured entry resolved, and dropping the MAC
    entries is what the caller does about it - correctly, since a MAC is not
    a name bleak can use. But the effect is that an explicit pin silently
    stops being honoured and the battery goes out on the default adapter or
    on some other card, which is exactly the separation the option exists to
    express.

    Two causes, and the message names both because they need different
    repairs. The card may have been REMOVED OR SWAPPED: a MAC pin is only as
    durable as the card that answers to it, so changing a dongle unpins
    whatever named it, silently, and the fix is to repin the config. Or
    adapter identity may be unreadable, which on Venus is one hciconfig call
    away from being the only source, and the fix is to that.

    The fallback is worth saying out loud because it is not necessarily
    benign: with no other configured adapter left, the battery goes out on
    the system default, which may be a card nothing else uses - on a box
    whose scanners have their own allowlist, the device is then never
    discovered there and every attempt fails not-found. Observed on a swapped
    dongle: the pin died with the card, the default was the new card, and the
    battery was unreachable for 18 hours with nothing alarming on it.

    Warned on the transition, not on the condition: this runs once per
    connection attempt.
    """
    if address in _unpinned_devices:
        return
    _unpinned_devices.add(address)
    dropped = [entry for entry in configured if is_adapter_mac(entry)]
    fallback = ", ".join(names) if names else "the system default adapter, which may be a card nothing else scans on"
    logger.warning(
        f"BLE adapter pins for {address} are not being honoured: {', '.join(dropped)} "
        f"{'resolves' if len(dropped) == 1 else 'resolve'} to no adapter present. "
        f"Falling back to {fallback}. Either the pinned card was removed or swapped - a MAC pin "
        "is only as durable as the card that answers to it, so repin the config - or adapter "
        "identity cannot be read at all, in which case check that hciconfig works."
    )


def _note_pins_honoured(address, adapters=None):
    """Re-arm the pin warning, once the battery is connected AND its pins resolve.

    Deliberately NOT re-armed the moment a configured card reappears in the
    BlueZ table. The connection manager warns about the same condition from
    its own layer and re-arms on connect, and a log watch counts both: with
    two triggers on one box, a card flapping in and out of the table makes
    one count climb while the other stays put, and the first person reading
    it files a layer as broken. Both layers now count alike.

    A recurring condition already has a voice - the per-episode still-down
    report - so this line can afford to be once per outage.
    """
    if address not in _unpinned_devices:
        return
    configured = adapters_for(address)
    if not configured:
        _unpinned_devices.discard(address)
        return
    if adapters is None:
        adapters = bluez_adapters()
    if any(resolve_adapter(entry, adapters) in adapters for entry in configured):
        _unpinned_devices.discard(address)


# Hold flag: while the flag file for a device exists, the reconnect loop makes
# no connection attempts for that device at all, giving a degraded BMS radio
# extended quiet. The driver, its dbus service and its published data stay up,
# which is the whole point - killing the driver process instead makes DVCC see
# the service disappear and raises alarms across the bank.
# A flag whose content is "auto" was written by an automatic recovery path and
# expires by itself; any other content is an operator hold and persists until
# the file is removed.
BLE_HOLD_FLAG_DIR = "/data/tmp"
BLE_HOLD_FLAG_PREFIX = "ble-hold-"
BLE_HOLD_AUTO_EXPIRY = 1200.0
BLE_HOLD_POLL_INTERVAL = 5


def ble_hold_flag_path(address):
    """Path of the hold flag file for the given device address."""
    return os.path.join(BLE_HOLD_FLAG_DIR, BLE_HOLD_FLAG_PREFIX + str(address).replace(":", "").lower())


# Outer deadlines for the connection backend. Generous on purpose: they are a
# last resort against a permanently parked await, not a connection timeout.
# How often the supervision wait re-checks the things that have no callback
# (the main thread going away, and a disconnect whose callback never fired).
# The link itself is awaited on an event, so this is a safety net rather than
# a poll: it used to be 0.1s, which cost ten timer wakeups a second per
# battery for the whole life of every connection and showed up as run-queue
# churn on a loaded GX device.
BLE_SUPERVISION_RECHECK = 5.0

# How long an episode - the span between a link dropping and coming back -
# may stay open before it says so, and how often it repeats after that. A
# characterised BMS radio mute lasts 10-20 s and the fallback covers it, so
# the first line lands well past every ordinary one: an outage has to be
# genuinely unusual to say anything at all. In a sustained outage this is 12
# lines an hour per battery, and none otherwise.
# Spacing between connection attempts: the first retry stays quick for an
# ordinary blip, then it settles. The flat 1 s retry this replaced turned a
# real outage into continuous hammering - production logs show single
# recovery episodes of 220 attempts - which wedged the adapter's discovery
# state and made recovery take longer than the outage.
BLE_RECONNECT_BACKOFF = [1, 3, 6]

BLE_EPISODE_REPORT_AFTER = 300.0

BLE_ESTABLISH_TIMEOUT = 300.0
BLE_RELEASE_TIMEOUT = 30.0

# How long the reaper waits for an abandoned BLE generation's thread to finish
# on its own before freeing its D-Bus resources out from under it. Slightly
# above BLE_ESTABLISH_TIMEOUT because an abandoned generation is most often
# parked inside one in-flight establish; a generation still alive after that
# is the truly-hung case, and closing its bus socket makes its pending await
# raise, which helps it exit rather than hurting it.
BLE_GENERATION_REAP_TIMEOUT = 330.0


# bleak-retry-connector lives in the ext folder, which dbus-serialbattery.py
# adds to sys.path; it is already vendored for the aiobmsble drivers, so this
# backend costs no new vendoring. Guard the import so utils_ble can be
# imported without it, and alias establish_connection: managed backends
# stacked on this branch import a function of the same name from their own
# library further down the module, and an unaliased import would be silently
# shadowed into calling the wrong one.
try:
    from bleak_retry_connector import (
        close_stale_connections,
        establish_connection as retry_establish_connection,
        get_device,
        get_device_by_adapter,
    )

    HAS_BLEAK_RETRY_CONNECTOR = True
except ImportError:
    HAS_BLEAK_RETRY_CONNECTOR = False


# BlueZ can report a device's services as resolved while its own view of the
# GATT tree is still incomplete, and start_notify then raises for a
# characteristic the battery genuinely has - after which the driver drops the
# link and reconnects forever against hardware that is working. Observed on a
# Cerbo GX. Rebuilding the tree from live BlueZ state and trying again clears
# it, so a connection is only given up on once that has failed too.
# Neither number is measured. The last attempt raises without sleeping, so
# three attempts spend two settles: the budget is 1.0s and two rebuilds, not
# 1.5s. The warning below names the attempt it is on, so the field settles
# this without new instrumentation - only ever attempt 1 and the first settle
# is always enough, attempt 2 and it is marginal, exhaustion and 1.0s is too
# short. Raise it on that evidence rather than on argument.
GATT_REDISCOVERY_ATTEMPTS = 3
GATT_REDISCOVERY_SETTLE = 0.5


async def rediscover_services(client, notify_char):
    """
    Rebuild a connected client's GATT tree from what BlueZ holds now.

    bleak has no public call for this: services is read-only, clear_cache is
    not implemented for the BlueZ backend, and the one public route - a
    disconnect - is unusable here because it fires the driver's own
    disconnected callback and tears down the session still being set up. So
    this goes through the backend, and checks for the attributes first: a
    bleak that moves them must fail loudly here rather than quietly stop
    rediscovering and leave the endless reconnect this exists to prevent.
    """
    backend = getattr(client, "_backend", None)
    get_services = getattr(backend, "_get_services", None)
    if get_services is None or not hasattr(backend, "services"):
        raise BleakError(
            f"characteristic {notify_char} is missing from the resolved GATT tree, and this bleak "
            "offers no way to rebuild it (expected _backend._get_services); connection unusable"
        )
    # _get_services returns the tree it already has, so it has to be dropped
    # first for the rebuild to read BlueZ again. The rebuild goes to live
    # BlueZ state rather than any cached collection, so a client that was
    # connected against a cached tree recovers here the same way - which is
    # why the connector's services cache can be left on.
    backend.services = None
    await get_services()


async def start_notify_when_resolved(client, notify_char, notify_callback):
    """Subscribe to notifications, rebuilding the GATT tree if the characteristic is missing."""
    for attempt in range(GATT_REDISCOVERY_ATTEMPTS):
        try:
            await client.start_notify(notify_char, notify_callback)
            return
        except BleakCharacteristicNotFoundError:
            if attempt == GATT_REDISCOVERY_ATTEMPTS - 1:
                raise
            logger.warning(f"characteristic {notify_char} not in the resolved GATT tree, rebuilding it (attempt {attempt + 1})")
            await rediscover_services(client, notify_char)
            # BlueZ fills the tree in asynchronously, so give it a moment
            # before asking again
            await asyncio.sleep(GATT_REDISCOVERY_SETTLE)


def landed_adapter(client):
    """
    The adapter a connected client's link is actually on, as hciN, or None.

    The adapter a backend ASKS for and the one a link ends up on are not the
    same thing. bleak-retry-connector swaps the BLEDevice for BlueZ's
    already-connected copy when one exists on any adapter, so a battery can
    be bound to a card the driver did not select - and every piece of state
    keyed to the request is then describing the wrong radio.

    BlueZ's own object path is the answer: a device lives under the adapter
    holding it, so /org/bluez/hci3/dev_... means hci3 whatever was asked for.
    bleak keeps that path on the backend and prefers it over the requested
    name itself when it needs the adapter. The attribute is private and read
    defensively, because a bleak that moves it should degrade to "unknown"
    rather than silently report the request as though it were the outcome.

    Read it AFTER connect and carry the answer. It is populated at different
    moments on the two backends - at construction from a BLEDevice, only
    during connect() from a bare address - and cleared again on teardown, so
    after-connect is the one moment correct for both.
    """
    path = getattr(getattr(client, "_backend", None), "_device_path", None)
    if not path:
        return None
    for part in str(path).split("/"):
        if re.fullmatch(r"hci\d+", part):
            return part
    return None


class BleConnectionBackend:
    """
    Interface for establishing and releasing BLE connections.

    Separates how a connection is established and torn down (the backend) from
    how Syncron_Ble supervises it and exchanges data with the BMS drivers, so
    alternative connection strategies can be plugged in without touching the
    drivers.
    """

    # Called when a link comes up, the mirror of the disconnected callback
    # the driver already hands to create_client. Both ends of a connection's
    # life are then delivered by the same seam: a driver that replaces the
    # connect path either gets both or neither, and can never open an episode
    # it has no way to close.
    connected_callback = None

    # the adapter this backend asked for, and the one the link came up on;
    # they differ whenever a lingering link elsewhere is adopted
    requested_adapter = None
    landed_adapter_name = None
    # only backends that resolve a device themselves ever scan
    scans_devices = False

    def _record_landed(self, client):
        """Remember which adapter the link actually came up on.

        current_adapter is what the rest of the driver reports and reasons
        about, so it must describe the live link rather than the request that
        started it. The requested name is kept alongside: the two differing
        is the signal that a link elsewhere was adopted.
        """
        self.requested_adapter = self.current_adapter
        landed = landed_adapter(client)
        self.landed_adapter_name = landed
        if landed:
            self.current_adapter = landed
        if self.connected_callback is not None:
            self.connected_callback()
        return landed

    def create_client(self, address, disconnected_callback):
        """
        Create the BleakClient for the given address, or None if the backend
        creates its own client during establish().
        """
        raise NotImplementedError

    async def establish(self, client, address, notify_char, notify_callback):
        """
        Connect and start notifications. Returns the connected client
        (may differ from the one passed in). Raises on failure.
        """
        raise NotImplementedError

    async def release(self, client):
        """Disconnect the client."""
        raise NotImplementedError


class BleakBackend(BleConnectionBackend):
    """
    Default backend: connects directly with bleak, matching the historical
    behavior of this driver.

    If BLUETOOTH_ADAPTERS is set, connections are made only via the listed
    adapters. A device with its own MAC@hciX entries uses those and never the
    shared pool; every other device uses the pool. Either list is walked in
    order, moving on only after a failed attempt, so a dropped link reconnects
    on the adapter it was using, and adapters BlueZ does not currently expose
    are skipped. An empty list uses the system default adapter.
    """

    def __init__(self):
        self.adapter_index = 0
        self.current_adapter = None

    def _select_adapter(self, address):
        """
        Adapter for the next attempt, or None when nothing is configured.

        The order is recomputed from live BlueZ state each time, so an adapter
        that has gone away is accounted for without the driver having to
        remember anything. The index only advances when an attempt fails, so a
        dropped link reconnects on the adapter it was already using and only a
        failed connect moves on to the next one. It is never reset on success:
        once a battery is talking over an adapter there is no reason to
        re-probe a preferred one that may be gone, and the modulo brings the
        list round to it again if this one later fails.
        """
        adapters = adapters_in_attempt_order(address)
        if not adapters:
            return None
        return adapters[self.adapter_index % len(adapters)]

    def create_client(self, address, disconnected_callback):
        kwargs = {}
        self.current_adapter = self._select_adapter(address)
        if self.current_adapter:
            kwargs["adapter"] = self.current_adapter
        return BleakClient(address, disconnected_callback=disconnected_callback, **kwargs)

    async def establish(self, client, address, notify_char, notify_callback):
        try:
            return await self._establish(client, address, notify_char, notify_callback)
        except Exception:
            # a failed attempt, so the next one goes out on the next adapter
            self.adapter_index += 1
            raise

    async def _establish(self, client, address, notify_char, notify_callback):
        logger.debug("initiating BLE connection to: " + address + (f" (adapter {self.current_adapter})" if self.current_adapter else ""))
        await client.connect()
        self._record_landed(client)
        await start_notify_when_resolved(client, notify_char, notify_callback)
        return client

    async def release(self, client):
        await client.disconnect()


class BleakRetryBackend(BleConnectionBackend):
    """
    Backend based on bleak-retry-connector, which is vendored in the ext
    folder and also used by the aiobmsble drivers. establish_connection()
    retries with error-classified backoff and cleans up stale BlueZ state,
    and the device is resolved from the BlueZ cache first, scanning only when
    that misses - so a reconnect is a single cheap connect call rather than a
    scan, and an idle system runs no scanners at all.

    BLUETOOTH_ADAPTERS is honored the same way as in BleakBackend: a battery
    walks its own adapters, or the shared pool, moving on only after a failed
    attempt.
    """

    scans_devices = True

    def __init__(self):
        self.adapter_index = 0
        self.current_adapter = None
        self.disconnected_callback = None
        # scans performed for the current episode; the driver reads and
        # resets it, so it counts per episode rather than for all time
        self.scans = 0

    def _select_adapter(self, address):
        """Same selection contract as BleakBackend: live order, failure-driven index."""
        adapters = adapters_in_attempt_order(address)
        if not adapters:
            return None
        return adapters[self.adapter_index % len(adapters)]

    def create_client(self, address, disconnected_callback):
        # establish_connection() creates the client itself
        self.disconnected_callback = disconnected_callback
        self.current_adapter = self._select_adapter(address)
        return None

    async def establish(self, client, address, notify_char, notify_callback):
        try:
            return await self._establish(client, address, notify_char, notify_callback)
        except Exception:
            # a failed attempt, so the next one goes out on the next adapter
            self.adapter_index += 1
            raise

    async def _establish(self, client, address, notify_char, notify_callback):
        logger.debug("initiating BLE connection to: " + address + (f" (adapter {self.current_adapter})" if self.current_adapter else ""))
        device = await self._resolve_device(address)
        if device is None:
            raise BleakError(f"bluetooth device {address} not found" + (f" on adapter {self.current_adapter}" if self.current_adapter else ""))
        await close_stale_connections(device)
        kwargs = {"adapter": self.current_adapter} if self.current_adapter else {}
        client = await retry_establish_connection(BleakClient, device, address, disconnected_callback=self.disconnected_callback, **kwargs)
        self._record_landed(client)
        await start_notify_when_resolved(client, notify_char, notify_callback)
        return client

    async def _resolve_device(self, address):
        """BLEDevice for the address from the BlueZ cache, scanning as fallback.

        With an adapter selected, both the cache lookup and the scan are bound
        to that adapter, so a battery can never resolve to a path on an
        adapter it is not configured for.
        """
        if self.current_adapter:
            device = await get_device_by_adapter(address, self.current_adapter)
        else:
            device = await get_device(address)
        if device is None:
            self.scans += 1
            logger.debug(f"bluetooth device {address} not in BlueZ cache, scanning")
            kwargs = {"adapter": self.current_adapter} if self.current_adapter else {}
            device = await BleakScanner.find_device_by_address(address, timeout=10.0, **kwargs)
        return device

    async def release(self, client):
        await client.disconnect()


# Available connection backends, selected by class name via BLUETOOTH_CONNECTION_BACKEND
supported_ble_backends = [BleakBackend]
if HAS_BLEAK_RETRY_CONNECTOR:
    supported_ble_backends.append(BleakRetryBackend)


def get_ble_backend(name=None):
    """Return the connection backend selected by BLUETOOTH_CONNECTION_BACKEND."""
    name = BLUETOOTH_CONNECTION_BACKEND if name is None else name
    for backend in supported_ble_backends:
        if backend.__name__ == name:
            return backend()
    logger.warning(f"Unknown BLUETOOTH_CONNECTION_BACKEND '{name}', using 'BleakBackend'")
    return BleakBackend()


def _reap_abandoned_ble_generation(old_thread, old_loop, address, generation):
    """Free the D-Bus resources of an abandoned BLE thread generation.

    rebuild_ble_thread() abandons the old generation's event loop, but bleak's
    global BlueZ manager for that loop stays pinned in
    bleak.backends.bluezdbus.manager._global_instances: bleak's own sweep only
    runs inside get_global_bluez_manager(), only pops loops that are already
    closed, and the new generation calls it exactly once — within seconds of
    the rebuild, while the old loop is still parked inside an in-flight await
    and not yet closed. Missed once, the entry is never revisited.

    The abandoned manager holds an open system-bus socket with three BlueZ
    match rules (InterfacesAdded/InterfacesRemoved/PropertiesChanged under
    /org/bluez) that nothing will ever read again, so dbus-daemon queues every
    BlueZ signal to it without bound — measured on a Cerbo GX at ~44 MB/h of
    daemon growth, OOM in hours. The daemon's own max_outgoing_bytes eviction
    (127 MB) is sized above the box's free RAM, so nothing upstream saves us.

    Closing the raw socket makes dbus-daemon drop the connection, its match
    rules and its queued messages immediately. Per-client buses need no
    reaping: nothing module-level pins them, so GC closes them once the old
    thread's stack unwinds.
    """
    try:
        if old_thread is not None:
            old_thread.join(BLE_GENERATION_REAP_TIMEOUT)
        if not old_loop:
            return
        from bleak.backends.bluezdbus import manager as bluez_manager

        instances = getattr(bluez_manager, "_global_instances", None)
        if not isinstance(instances, dict):
            logger.warning(f"BLE generation {generation} reaper for {address}: bleak has no _global_instances dict; bleak changed, reaper needs updating")
            return
        abandoned = instances.pop(old_loop, None)
        if abandoned is None:
            # bleak's own closed-loop sweep got there first, or the old
            # generation never created a manager (e.g. it failed to connect)
            return
        sock = getattr(getattr(abandoned, "_bus", None), "_sock", None)
        if sock is not None:
            sock.close()
        logger.warning(
            f"BLE generation reaper for {address}: freed generation {generation}'s abandoned BlueZ manager bus; "
            "its match rules would otherwise make dbus-daemon queue signals to it without bound"
        )
    except Exception as e:
        logger.warning(f"BLE generation {generation} reaper for {address} failed: {repr(e)}")


# Class that enables synchronous writing and reading to a bluetooh device
class Syncron_Ble:

    ble_async_thread_ready = threading.Event()
    ble_connection_ready = threading.Event()
    ble_async_thread_event_loop = False
    client = False
    address = None
    response_event = False
    response_data = False
    main_thread = False
    connected = False

    write_characteristic = None
    read_characteristic = None

    # Episode accounting, defaulted at class level like the rest of this
    # class's state so a partially constructed instance still reports rather
    # than raising from a logging path.
    _attempts = 0
    _scans_base = 0
    _first_link_reported = False
    _episode_started = None
    _episode_dropped_from = None
    _episode_report_due = None
    _pending_drop = None

    def __init__(self, address, read_characteristic, write_characteristic):
        """
        address: the address of the bluetooth device to read and write to
        read_characteristic: the id of bluetooth LE characteristic that will send a
        notification when there is new data to read.
        write_characteristic: the id of the bluetooth LE characteristic that the class writes messages to
        """

        self.write_characteristic = write_characteristic
        self.read_characteristic = read_characteristic
        self.address = address
        self.backend = self._new_backend()
        # Only the BLE thread of the current generation keeps running; see
        # rebuild_ble_thread()
        self._ble_thread_generation = 0
        # set when the link drops, so supervision waits instead of polling
        self._disconnected = None
        self._disconnected_loop = None
        # One line per episode instead of three or four per attempt. An
        # episode is the span between a link dropping and coming back; the
        # counters run from the start of the process until the first
        # connection, then per episode.
        self._attempts = 0
        self._scans_base = 0
        self._first_link_reported = False
        self._episode_started = None
        self._episode_dropped_from = None
        self._episode_report_due = None
        self._pending_drop = None

        # Start a new thread that will run bleak the async bluetooth LE library
        self.main_thread = threading.current_thread()
        # kept so rebuild_ble_thread's reaper can join the generation it abandons
        self._ble_async_thread = None
        ble_async_thread = threading.Thread(name="BMS_bluetooth_async_thread", target=self.initiate_ble_thread_main, daemon=True)
        ble_async_thread.start()
        self._ble_async_thread = ble_async_thread

        thread_start_ok = self.ble_async_thread_ready.wait(2)
        connected_ok = self.ble_connection_ready.wait(10)
        if not thread_start_ok:
            logger.error("bluetooh LE thread took to long to start")
        if not connected_ok:
            logger.error(f"bluetooh LE connection to address: {self.address} took to long to inititate")
        else:
            self.connected = True

    def initiate_ble_thread_main(self, generation=0):
        # Once per generation, unconditionally - before anything can fail.
        # It names the backend, which is what tells a reader whether a missing
        # scan count means "never had to scan" or "cannot scan", and it is the
        # only marker a first generation emits: the rebuild path announces
        # itself, generation 0 otherwise never did.
        logger.info(f"BLE thread for {self.address} generation {generation} started on backend {type(self.backend).__name__}")
        asyncio.run(self.async_main(self.address, generation))

    def rebuild_ble_thread(self):
        """Abandon a wedged BLE thread and start a fresh one in-process.

        The remedy for a deadlocked reconnect loop used to be exiting the
        whole process, which takes the dbus service and the in-RAM state
        down with it and makes the inverter raise 'BMS connection lost'.
        Rebuilding just the BLE thread keeps everything the rest of the
        system depends on alive. The old thread, if merely slow rather than
        hung, exits at its next loop iteration via the generation check; a
        truly hung one is abandoned (it is a daemon thread).
        """
        try:
            self._end_episode("abandoned")
            self._ble_thread_generation += 1
            generation = self._ble_thread_generation
            # Capture the generation being abandoned BEFORE its state is
            # overwritten, and hand it to a reaper: the old loop's BlueZ
            # manager bus stays pinned in bleak's module-level dict with
            # live match rules, and nothing else ever frees it (see
            # _reap_abandoned_ble_generation).
            old_thread = self._ble_async_thread
            old_loop = self.ble_async_thread_event_loop
            threading.Thread(
                name=f"BMS_ble_gen{generation - 1}_reaper",
                target=_reap_abandoned_ble_generation,
                args=(old_thread, old_loop, self.address, generation - 1),
                daemon=True,
            ).start()
            self.ble_async_thread_ready = threading.Event()
            self.ble_connection_ready = threading.Event()
            self.ble_async_thread_event_loop = False
            self.connected = False
            self.backend = self._new_backend()  # fresh backend state
            ble_async_thread = threading.Thread(
                name=f"BMS_bluetooth_async_thread_gen{generation}",
                target=self.initiate_ble_thread_main,
                args=(generation,),
                daemon=True,
            )
            ble_async_thread.start()
            self._ble_async_thread = ble_async_thread
            started = self.ble_async_thread_ready.wait(5)
            logger.error(f"BLE thread rebuild for {self.address}: generation {generation} {'started' if started else 'FAILED TO START'}")
            return started
        except Exception as e:
            logger.error(f"BLE thread rebuild for {self.address} failed: {repr(e)}")
            return False

    async def async_main(self, address, generation=0):
        self.ble_async_thread_event_loop = asyncio.get_event_loop()
        self.ble_async_thread_ready.set()

        # A session that held for over a minute resets the ramp.
        failures = 0
        hold_flag = ble_hold_flag_path(self.address)
        holding = False
        waiting_for_adapter = False
        while self.main_thread.is_alive() and generation == self._ble_thread_generation:
            if os.path.exists(hold_flag):
                try:
                    with open(hold_flag) as f:
                        automatic = f.read().strip() == "auto"
                    if automatic and time.time() - os.path.getmtime(hold_flag) > BLE_HOLD_AUTO_EXPIRY:
                        os.remove(hold_flag)
                        logger.info(f"BLE hold for {self.address} auto-expired, resuming connection attempts")
                        continue
                except Exception as e:
                    if not holding:
                        logger.warning(f"BLE hold flag {hold_flag} could not be read: {repr(e)}")
                if not holding:
                    holding = True
                    self._end_episode("paused")
                    logger.warning(f"BLE hold flag {hold_flag} present, pausing connection attempts for {self.address}")
                await asyncio.sleep(BLE_HOLD_POLL_INTERVAL)
                continue
            if holding:
                holding = False
                logger.info(f"BLE hold for {self.address} released, resuming connection attempts")
            # A strict pin means the named adapter is protecting something -
            # keeping two batteries off one radio, or off a card another
            # service owns - so connecting over a different one is worse than
            # not connecting. Wait rather than fall back, and say so once.
            if BLUETOOTH_ADAPTER_PIN_STRICT and not configured_adapter_present(self.address):
                if not waiting_for_adapter:
                    waiting_for_adapter = True
                    logger.warning(
                        f"BLE adapter pins for {self.address} are not being honoured: none of "
                        f"{', '.join(adapters_for(self.address) or BLUETOOTH_ADAPTER_POOL)} is present. "
                        "Waiting for one of them rather than falling back (BLUETOOTH_ADAPTER_PIN_STRICT is on). "
                        "Either the pinned card was removed or swapped - a MAC pin is only as durable as the "
                        "card that answers to it, so repin the config - or adapter identity cannot be read at "
                        "all, in which case check that hciconfig works."
                    )
                await asyncio.sleep(BLE_HOLD_POLL_INTERVAL)
                continue
            if waiting_for_adapter:
                waiting_for_adapter = False
                logger.info(f"BLE adapter for {self.address} is present again, resuming connection attempts")
            self._begin_pending_episode()
            self._report_episode_still_open()
            self._attempts += 1
            attempt_started = time.time()
            await self.connect_to_bms(self.address)
            if time.time() - attempt_started > 60.0:
                failures = 0
            else:
                failures = min(failures + 1, len(BLE_RECONNECT_BACKOFF) - 1)
            await asyncio.sleep(BLE_RECONNECT_BACKOFF[failures])

    def _new_backend(self):
        """A backend wired to report both ends of a connection's life.

        Obtained here rather than at each construction site so the wiring
        cannot be forgotten by one of them - the reason the link-up report
        was skippable in the first place was that it lived on a path a
        subclass could replace.
        """
        backend = get_ble_backend()
        backend.connected_callback = self._report_link_up
        return backend

    def _scans(self):
        """Scans since the counters were last reset, or None if this backend cannot scan.

        None and zero are different answers: a backend that resolves devices
        itself and never had to scan hit the BlueZ cache every time, which is
        the healthy case worth reporting, while a backend with no scan path
        at all has nothing to say. Reporting both as 0 would make the number
        unreadable.
        """
        if not getattr(self.backend, "scans_devices", False):
            return None
        return getattr(self.backend, "scans", 0) - self._scans_base

    def _counters(self):
        """The "N attempts, M scans" tail, with the scans token omitted where it means nothing."""
        scans = self._scans()
        tail = f"{self._attempts} attempts"
        return tail if scans is None else f"{tail}, {scans} scans"

    def _reset_counters(self):
        self._attempts = 0
        self._scans_base = getattr(self.backend, "scans", 0)

    def _note_drop(self):
        """Record a link dropping. Called from the disconnect callback.

        The callback can arrive at any moment, including part-way through the
        connect that is about to succeed - a link left behind by a previous
        process is delivered to its successor, so this happens on every
        restart where the old link outlives the new registration. Resetting
        the counters here rewrote an in-flight attempt's history and reported
        a connection that took one attempt as having taken none. The drop is
        recorded instead and applied by the loop, which is the only place
        that knows no attempt is in flight.

        A drop before this life has ever had a link is not an episode: there
        was nothing to lose, and counting it would open one that the first
        connection then closes without ever having been an outage.

        The FIRST callback of an outage is the one that counts. BlueZ
        delivers two or three for a single outage - a re-drop during a
        reconnect attempt, or the same drop more than once - and taking the
        latest would date the outage from its last callback rather than its
        start, under-reporting how long the link was down by the whole gap
        between them. Measured on a production pack: up to about 5 s, on
        exactly the outages someone is reading the number for.
        """
        if not self._first_link_reported:
            return
        if self._pending_drop is not None:
            return
        landed = getattr(self.backend, "landed_adapter_name", None) or getattr(self.backend, "current_adapter", None)
        self._pending_drop = (time.time(), landed)

    def _begin_pending_episode(self):
        """Open the episode a recorded drop started, between attempts."""
        if self._pending_drop is None or self._episode_started is not None:
            return
        started, landed = self._pending_drop
        self._pending_drop = None
        self._episode_dropped_from = landed
        self._episode_started = started
        self._episode_report_due = started + BLE_EPISODE_REPORT_AFTER
        self._reset_counters()

    def _end_episode(self, terminator):
        """Emit one line for an episode that ended without the link coming back.

        The reconnect loop has no give-up, so these are the only two ways an
        episode ends other than recovery: the generation is abandoned by a
        thread rebuild, or a hold flag stops the attempts. Both are cases
        where the driver stops trying and the counters are the whole story.
        """
        if self._episode_started is None:
            return
        down = time.time() - self._episode_started
        requested = describe_adapter(getattr(self.backend, "current_adapter", None))
        dropped = describe_adapter(self._episode_dropped_from)
        logger.info(
            f"BLE link {terminator} for {self.address} after {down:.1f} s; "
            f"dropped from adapter {dropped}; requested adapter {requested}; {self._counters()}"
        )
        self._episode_started = None
        self._episode_report_due = None
        self._pending_drop = None

    def _report_episode_still_open(self):
        """One line every BLE_EPISODE_REPORT_AFTER seconds while a link stays down.

        The watch reads logs, not the bus: the connection state is published
        on D-Bus, but reading it there costs real CPU on a GX device and has
        set off load alarms. And "still down" is not the useful part - the
        attempt and scan counts, and which adapter is being asked for, are
        what separate a systematically failing lookup from a silent battery.
        """
        if self._episode_started is None or self._episode_report_due is None:
            return
        now = time.time()
        if now < self._episode_report_due:
            return
        self._episode_report_due = now + BLE_EPISODE_REPORT_AFTER
        requested = describe_adapter(getattr(self.backend, "current_adapter", None))
        dropped = describe_adapter(self._episode_dropped_from)
        logger.info(
            f"still reconnecting to {self.address} after {now - self._episode_started:.0f} s: "
            f"{self._counters()}, requested adapter {requested}; dropped from adapter {dropped}"
        )

    def _report_link_up(self):
        """The one INFO line a healthy life emits, and the one an episode ends with."""
        landed = describe_adapter(getattr(self.backend, "landed_adapter_name", None) or getattr(self.backend, "current_adapter", None))
        # a drop recorded but never opened belongs to the link that just came
        # back, so it must not open an episode after the fact
        self._pending_drop = None
        _note_pins_honoured(self.address)
        if not self._first_link_reported:
            self._first_link_reported = True
            self._episode_started = None
            self._episode_report_due = None
            logger.info(f"connected to bluetooth device {self.address} on adapter {landed}; {self._counters()}")
            return
        if self._episode_started is None:
            return
        down = time.time() - self._episode_started
        dropped = describe_adapter(self._episode_dropped_from)
        logger.info(f"BLE link recovered for {self.address} after {down:.1f} s on adapter {landed}; " f"dropped from adapter {dropped}; {self._counters()}")
        self._episode_started = None
        self._episode_report_due = None

    def client_disconnected(self, client):
        # A 10-20 s BMS radio mute that the fallback covers is not an error,
        # and logging it as one taught everyone to ignore the word. The
        # message text is unchanged: it is the event a log watch keys on to
        # find episode boundaries.
        logger.info(f"bluetooh device with address: {self.address} disconnected")
        self._note_drop()
        self.signal_disconnected()

    def signal_disconnected(self):
        """Wake the supervision wait from wherever the callback reaches us.

        call_soon_threadsafe rather than a bare set(): bleak invokes the
        callback on the loop that owns the client, but the backends wrap it
        and a wrapped callback is not guaranteed to keep that property.
        Scheduling onto the captured loop is correct from either side.
        """
        event, loop = self._disconnected, self._disconnected_loop
        if event is None or loop is None:
            return
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:
            # loop already closed - the connection is over either way
            pass

    async def supervise_connection(self):
        """Wait for the link to end, without polling for it.

        Two things end it and only one has a callback. The disconnect does,
        so it is awaited on an event. The main thread going away does not,
        and neither does a disconnect whose callback never fires - a real
        failure mode here, which is why is_connected is still consulted - so
        both are re-checked on a coarse timeout rather than at 10 Hz.
        """
        while True:
            try:
                await asyncio.wait_for(self._disconnected.wait(), timeout=BLE_SUPERVISION_RECHECK)
                return
            except asyncio.TimeoutError:
                pass
            if not self.main_thread.is_alive():
                return
            if not self.client.is_connected:
                return

    async def connect_to_bms(self, address):
        # one event per connection: a stale set() from the previous link must
        # not end this one's supervision immediately
        self._disconnected = asyncio.Event()
        self._disconnected_loop = asyncio.get_running_loop()
        self.client = self.backend.create_client(address, self.client_disconnected)
        try:
            # Belt-and-braces deadline: a backend's own timeouts should always
            # fire first, but no single stalled await may park the reconnect
            # loop permanently. One unguarded D-Bus await once silenced
            # reconnection for four hours without a single log line.
            self.client = await asyncio.wait_for(
                self.backend.establish(self.client, address, self.read_characteristic, self.notify_read_callback),
                timeout=BLE_ESTABLISH_TIMEOUT,
            )

        except Exception as e:
            logger.debug(f"Failed when trying to connect: {repr(e)}")
            return False
        finally:
            self.ble_connection_ready.set()
            if self.client:
                await self.supervise_connection()
                try:
                    await asyncio.wait_for(self.backend.release(self.client), timeout=BLE_RELEASE_TIMEOUT)
                except Exception as e:
                    # a disconnect that never completes must not prevent the
                    # next connection attempt
                    logger.warning(f"BLE [{address}] disconnect did not complete: {repr(e)}")

    # saves response and tells the command sender that the response has arived
    def notify_read_callback(self, sender, data: bytearray):
        capture_raw_data(self.address, "rx", data)
        self.response_data = data
        self.response_event.set()

    async def ble_thread_send_com(self, command):
        self.response_event = asyncio.Event()
        self.response_data = False
        capture_raw_data(self.address, "tx", command)
        await self.client.write_gatt_char(self.write_characteristic, command, True)
        await asyncio.wait_for(self.response_event.wait(), timeout=1)  # Wait for the response notification
        self.response_event = False
        return self.response_data

    def send_data(self, data):
        # Schedule the write on the BLE thread's existing event loop and wait
        # for the result directly. The previous implementation wrapped this in
        # asyncio.run(), constructing and tearing down a whole event loop for
        # every command sent — measurable CPU overhead on GX hardware for
        # drivers that poll several commands every few seconds.
        future = asyncio.run_coroutine_threadsafe(self.ble_thread_send_com(data), self.ble_async_thread_event_loop)
        try:
            return future.result(timeout=1.5)
        except Exception:
            future.cancel()
            raise


def restart_ble_hardware_and_bluez_driver():
    if not BLUETOOTH_FORCE_RESET_BLE_STACK:
        return

    logger.info("*** Restarting BLE hardware and Bluez driver ***")

    # list bluetooth controllers
    result = subprocess.run(["hciconfig"], capture_output=True, text=True)
    logger.info(f"hciconfig exit code: {result.returncode}")
    logger.info(f"hciconfig output: {result.stdout}")

    # bluetoothctl list
    result = subprocess.run(["bluetoothctl", "list"], capture_output=True, text=True)
    logger.info(f"bluetoothctl list exit code: {result.returncode}")
    logger.info(f"bluetoothctl list output: {result.stdout}")

    # stop will not work, if service/bluetooth driver is stuck
    result = subprocess.run(["/etc/init.d/bluetooth", "stop"], capture_output=True, text=True)
    logger.info(f"bluetooth stop exit code: {result.returncode}")
    logger.info(f"bluetooth stop output: {result.stdout}")

    # process kill is needed, since the service/bluetooth driver is probably freezed
    result = subprocess.run(["pkill", "-f", "bluetoothd"], capture_output=True, text=True)
    logger.info(f"pkill exit code: {result.returncode}")
    logger.info(f"pkill output: {result.stdout}")

    # rfkill block bluetooth
    result = subprocess.run(["rfkill", "block", "bluetooth"], capture_output=True, text=True)
    logger.info(f"rfkill block exit code: {result.returncode}")
    logger.info(f"rfkill block output: {result.stdout}")

    # kill hdciattach
    result = subprocess.run(["pkill", "-f", "hciattach"], capture_output=True, text=True)
    logger.info(f"pkill hciattach exit code: {result.returncode}")
    logger.info(f"pkill hciattach output: {result.stdout}")
    sleep(0.5)

    # kill hci_uart
    result = subprocess.run(["rmmod", "hci_uart"], capture_output=True, text=True)
    logger.info(f"rmmod hci_uart exit code: {result.returncode}")
    logger.info(f"rmmod hci_uart output: {result.stdout}")

    # kill btbcm
    result = subprocess.run(["rmmod", "btbcm"], capture_output=True, text=True)
    logger.info(f"rmmod btbcm exit code: {result.returncode}")
    logger.info(f"rmmod btbcm output: {result.stdout}")

    # load hci_uart
    result = subprocess.run(["modprobe", "hci_uart"], capture_output=True, text=True)
    logger.info(f"modprobe hci_uart exit code: {result.returncode}")
    logger.info(f"modprobe hci_uart output: {result.stdout}")

    # load btbcm
    result = subprocess.run(["modprobe", "btbcm"], capture_output=True, text=True)
    logger.info(f"modprobe btbcm exit code: {result.returncode}")
    logger.info(f"modprobe btbcm output: {result.stdout}")

    sleep(2)

    result = subprocess.run(["rfkill", "unblock", "bluetooth"], capture_output=True, text=True)
    logger.info(f"rfkill unblock exit code: {result.returncode}")
    logger.info(f"rfkill unblock output: {result.stdout}")

    result = subprocess.run(["/etc/init.d/bluetooth", "start"], capture_output=True, text=True)
    logger.info(f"bluetooth start exit code: {result.returncode}")
    logger.info(f"bluetooth start output: {result.stdout}")

    logger.info("System Bluetooth daemon should have been restarted")
    logger.info("Exit driver for clean restart")

    sys.exit(1)
