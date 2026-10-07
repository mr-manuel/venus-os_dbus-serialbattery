import sys

import pytest

# generic_aiobmsble annotates function signatures with PEP 604 unions, and so
# does upstream: `def _run_coro(self, coro, timeout: float | None = None)`.
# Signature annotations are evaluated at def time, so the module cannot be
# imported at all before 3.10 - a syntax check does not catch this. CI runs
# 3.12, where the tests below execute rather than skip.
_needs_pep604 = pytest.mark.skipif(
    sys.version_info < (3, 10),
    reason="generic_aiobmsble cannot be imported before Python 3.10 (PEP 604 annotations in signatures)",
)


# --------- the refresh path must not start a discovery ---------
#
# Field failure on a GX device: with the client lost and another
# service already scanning the adapter, a bare find_device_by_address on
# every poll failed with org.bluez.Error.InProgress, blocked the caller for
# the whole coroutine timeout, and starved the GLib main thread so the
# battery service could not answer D-Bus at all.


def test_refresh_resolves_cache_first_and_does_not_scan():
    import ast
    import os

    src = os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery", "bms", "generic_aiobmsble.py")
    tree = ast.parse(open(src).read())

    scanning_calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "find_device_by_address":
            scanning_calls.append(node.lineno)

    resolver = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_resolve_device")
    inside = [ln for ln in scanning_calls if resolver.lineno <= ln <= (resolver.end_lineno or resolver.lineno)]

    # every discovery in this module must live inside _resolve_device, which
    # only reaches it after the BlueZ cache has missed
    assert scanning_calls, "expected the cache-miss fallback to still exist"
    assert scanning_calls == inside, f"find_device_by_address called outside _resolve_device at lines {sorted(set(scanning_calls) - set(inside))}"


def test_refresh_never_blocks_the_main_thread_on_the_bms():
    """refresh_data runs on the GLib main thread, which also answers D-Bus.

    Waiting there for a BMS coroutine stops the driver serving anything:
    an unreachable pack blocked it for the whole coroutine timeout on every
    poll, and the battery service stopped answering /Soc and
    /Mgmt/Connection while still registered. The poll must schedule and
    harvest, never wait.
    """
    import ast
    import os

    src = os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery", "bms", "generic_aiobmsble.py")
    tree = ast.parse(open(src).read())

    refresh = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "refresh_data")
    called = {n.func.attr for n in ast.walk(refresh) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "_poll_update" in called, "refresh_data must drive the update through the non-blocking poller"
    assert "_run_coro" not in called, "refresh_data must not call the blocking runner"

    # and the poller itself must never wait on the future
    poller = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_poll_update")
    for n in ast.walk(poller):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "result":
            # result(0) is a harvest of an already-finished future, not a wait
            assert n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == 0, "harvest must use result(0); anything else waits"


# --------- an unreachable device must be paced, not hammered ---------
#
# refresh_data polls at 1 Hz, and every poll without a client ran a full
# establish_connection (four BlueZ attempts of its own). For a device that
# is off, removed or out of range those retries cannot succeed and only
# cost load.


def _load_driver():
    import importlib
    import os
    import sys

    import types

    root = os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery")
    if root not in sys.path:
        sys.path.insert(0, root)

    # Stub the BLE libraries rather than importing the vendored copies: they
    # use match statements, so on Python 3.9 a real import is a SyntaxError.
    # Same approach as tests/conftest.py, and only ever additive - an already
    # imported real module wins.
    def _stub(name, **attrs):
        if name not in sys.modules:
            mod = types.ModuleType(name)
            for k, v in attrs.items():
                setattr(mod, k, v)
            sys.modules[name] = mod
        return sys.modules[name]

    _stub("bleak", BleakScanner=object)
    _stub("bleak.backends")
    _stub("bleak.backends.device", BLEDevice=object)
    _stub("bleak.exc", BleakError=type("BleakError", (Exception,), {}))
    _stub("aiobmsble", BMSInfo=dict, BMSSample=dict, TempSensor=object)

    return importlib.import_module("bms.generic_aiobmsble")


def _paced_instance(mod):
    """A bare instance carrying only the reconnect-pacing state."""
    # The REAL methods, borrowed onto a stand-in that has no __del__: a bare
    # Generic_AioBmsBle would run the background-loop teardown on collection
    # and bury the assertions in unrelated log noise. The functions under test
    # are the production ones either way.
    driver = mod.Generic_AioBmsBle
    stand_in = type(
        "PacedStandIn",
        (),
        {
            "_reconnect_on_hold": driver._reconnect_on_hold,
            "_note_connect_failure": driver._note_connect_failure,
            "_note_connect_success": driver._note_connect_success,
        },
    )
    obj = stand_in()
    obj.address = "A4:C1:38:33:41:24"
    obj._connect_failures = 0
    obj._reconnect_hold_until = 0.0
    obj._reconnect_warned = False
    return obj


@_needs_pep604
def test_unreachable_device_is_paced_but_never_abandoned():
    mod = _load_driver()
    bms = _paced_instance(mod)

    # a first miss must NOT impose a wait: a pack that slept through one
    # advertising window has to recover on the very next poll
    bms._note_connect_failure("device not found")
    assert not bms._reconnect_on_hold(), "a single miss must not pace the next attempt"

    # a sustained outage must reach the longest step
    for _ in range(len(mod.RECONNECT_BACKOFF_SECONDS) + 3):
        bms._note_connect_failure("device not found")
    assert bms._reconnect_on_hold(), "a sustained outage must pace the next attempt"

    # ...and must still RETRY once the wait elapses. This is the assertion that
    # separates "paced" from "gave up" - a driver that stops trying would also
    # pass a test that only checked the hammering had stopped.
    import time as _t

    bms._reconnect_hold_until = _t.monotonic() - 0.01
    assert not bms._reconnect_on_hold(), "pacing must expire so the device is retried, not abandoned"


@_needs_pep604
def test_sustained_outage_warns_once_and_resets_on_recovery():
    mod = _load_driver()
    bms = _paced_instance(mod)

    warnings = []
    real_logger = mod.logger

    class _Capture:
        def warning(self, msg, *a):
            warnings.append(msg % a if a else msg)

        def debug(self, msg, *a):
            pass

        def error(self, msg, *a):
            pass

        def info(self, msg, *a):
            pass

    mod.logger = _Capture()
    try:
        for _ in range(60):  # a full minute of 1 Hz polling
            bms._note_connect_failure("device not found")
        assert len(warnings) == 1, f"one warning per outage, got {len(warnings)}: {warnings}"

        bms._note_connect_success()
        assert len(warnings) == 2, "recovery must be reported too"
        assert bms._connect_failures == 0 and not bms._reconnect_on_hold(), "success must clear the pacing state"

        # a later outage warns again - the once-per-outage latch must reset
        for _ in range(60):
            bms._note_connect_failure("device not found")
        assert len(warnings) == 3, "a second outage must warn again"
    finally:
        mod.logger = real_logger


# --------- the same properties, driven through the real code paths ---------
#
# The tests above pin the helpers. These run the methods that call them, so
# deleting the wiring - not just breaking a helper - fails a test: removing
# the pacing gate from refresh_data, leaking the update lock after a harvest
# (which stops every later update without logging anything), or skipping the
# BlueZ cache all passed the helper-level tests.


def _borrow(mod, *names):
    """A stand-in carrying the named REAL driver methods and nothing else."""
    driver = mod.Generic_AioBmsBle
    return type("BorrowedStandIn", (), {name: getattr(driver, name) for name in names})()


class _Log:
    """Records the driver's warnings and errors; drops the rest."""

    def __init__(self):
        self.warnings = []
        self.errors = []

    def warning(self, msg, *args):
        self.warnings.append(msg % args if args else msg)

    def error(self, msg, *args, **kwargs):
        self.errors.append(msg % args if args else msg)

    exception = error

    def debug(self, *args, **kwargs):
        pass

    info = debug


class _Clock:
    """Stands in for the driver's time module, so a test can move time on."""

    def __init__(self):
        self.now = 10_000.0

    def monotonic(self):
        return self.now


def _refresh_with_device_gone(mod, monkeypatch):
    """The real refresh_data on a stand-in whose BLE device has gone away.

    refresh_data turns any exception into an ERROR line and a False return,
    which is indistinguishable from a stale device - so a stand-in missing an
    attribute would pass silently. Every caller asserts log.errors is empty.
    """
    import asyncio
    import types

    scans = []

    class _Scanner:
        @staticmethod
        async def find_device_by_address(address):
            scans.append(address)
            return None

    log, clock = _Log(), _Clock()
    monkeypatch.setattr(mod, "BleakScanner", _Scanner)
    # no BlueZ cache either, so every resolve that runs is a scan
    monkeypatch.setitem(sys.modules, "bleak_retry_connector", types.ModuleType("bleak_retry_connector"))
    monkeypatch.setattr(mod, "logger", log)
    monkeypatch.setattr(mod, "time", clock)

    names = ("refresh_data", "_resolve_device", "_ensure_aiobmsble", "_aiobmsble_connect", "_aiobmsble_disconnect")
    bms = _borrow(mod, *names, "_reconnect_on_hold", "_note_connect_failure", "_note_connect_success")
    bms.AIOBMSBLE_CLASS = None  # a test that models recovery sets a client class
    bms.address = "A4:C1:38:33:41:24"
    bms._aiobmsble = None
    bms.aiobmsble_data = {"voltage": 13.2, "current": 0.0, "battery_level": 80}
    bms._last_successful_update = clock.now - 60
    bms._max_data_age = 5
    bms._stale_warning_interval = 60
    bms._stale_warned_at = 0.0
    bms._connect_failures = 0
    bms._reconnect_hold_until = 0.0
    bms._reconnect_warned = False

    # run each poll's coroutine to completion inline: scheduling is
    # _poll_update's job and is tested separately. Like _poll_update, treat an
    # update that raised as "no fresh data" rather than letting it escape.
    def _run_inline(coro):
        try:
            return bool(asyncio.run(coro()))
        except Exception:
            return False

    bms._poll_update = _run_inline
    return bms, scans, log, clock


@_needs_pep604
def test_refresh_does_not_reconnect_while_paced(monkeypatch):
    mod = _load_driver()
    bms, scans, log, clock = _refresh_with_device_gone(mod, monkeypatch)

    for _ in range(120):
        bms.refresh_data()
    assert len(scans) < 12, f"a paced device must not be scanned on every poll ({len(scans)} scans in 120 polls)"

    # ...and it is tried again, not abandoned, once the wait elapses
    before = len(scans)
    clock.now = bms._reconnect_hold_until + 0.01
    bms.refresh_data()
    assert len(scans) == before + 1, "the device must be retried once the pacing expires"
    assert log.errors == [], f"refresh_data swallowed an exception: {log.errors[:1]}"


@_needs_pep604
def test_lost_connection_is_paced(monkeypatch):
    """A battery that was connected and then went away is paced too.

    Once a client exists, the driver never finds or connects the device
    itself again: the aiobmsble client reconnects inside async_update. That
    is the usual way an outage happens, so it is the path that most needs
    the pacing.
    """
    mod = _load_driver()
    bms, scans, log, clock = _refresh_with_device_gone(mod, monkeypatch)
    updates = []

    class _Client:
        """The client from startup; its battery has gone away."""

        async def async_update(self):
            updates.append(clock.now)
            raise RuntimeError("Failed to connect after 4 attempt(s)")

        async def disconnect(self):
            pass

    bms._aiobmsble = _Client()  # it was connected, then the battery went away

    # three minutes at one poll a second
    for _ in range(180):
        bms.refresh_data()
        clock.now += 1
    # the startup client is tried once and then dropped: it is bound to the
    # adapter it was found on, so later attempts resolve the device afresh
    assert len(updates) == 1, f"the startup client must be tried once, then dropped ({len(updates)} tries)"
    assert scans, "after the lost link the device must be resolved afresh"
    attempts = len(updates) + len(scans)
    assert attempts < 12, f"a lost connection must not be retried on every poll ({attempts} tries in 180 polls)"
    assert sum("unreachable after" in w for w in log.warnings) == 1, "a long outage must be reported once"
    unexpected = [e for e in log.errors if "Failed to refresh BMS data" not in e]
    assert unexpected == [], f"refresh_data swallowed an exception: {unexpected[:1]}"

    # the battery comes back, seen by an adapter that is present: the next try
    # builds a new client on it, succeeds, and clears the pacing.
    # (Parsing the data needs the real Battery class, so this one poll logs an
    # error on the stand-in after the pacing has been reset; that is expected.)
    device, built = object(), []

    class _Found:
        @staticmethod
        async def find_device_by_address(address):
            return device

    class _Fresh:
        def __init__(self, ble_device):
            built.append(ble_device)

        async def connect(self):
            pass

        async def async_update(self):
            return {"voltage": 13.3, "current": 0.0, "battery_level": 81}

        async def disconnect(self):
            pass

    monkeypatch.setattr(mod, "BleakScanner", _Found)
    bms.AIOBMSBLE_CLASS = _Fresh
    clock.now = bms._reconnect_hold_until + 0.01
    bms.refresh_data()
    assert built == [device], "recovery must build a new client on the adapter that has the device"
    assert bms._connect_failures == 0, "a successful update must clear the pacing"
    assert any("reachable again after" in w for w in log.warnings), "the recovery must be reported"


@_needs_pep604
def test_lost_connection_rebinds_to_the_adapter_that_has_the_device(monkeypatch):
    """After a lost connection the device is resolved afresh, not reused.

    The client is built from a device object that names the adapter it was
    found on. When that adapter is removed and the battery is reachable
    through another, a client that keeps the old object can never reconnect:
    on the test system the driver retried for the life of the process while
    four working adapters sat idle.
    """
    import asyncio
    import types

    mod = _load_driver()
    log, clock = _Log(), _Clock()
    monkeypatch.setattr(mod, "logger", log)
    monkeypatch.setattr(mod, "time", clock)
    monkeypatch.setitem(sys.modules, "bleak_retry_connector", types.ModuleType("bleak_retry_connector"))

    resolved = []
    new_adapter_device = object()

    class _Scanner:
        @staticmethod
        async def find_device_by_address(address):
            resolved.append(address)
            return new_adapter_device  # the battery, seen by an adapter that is present

    monkeypatch.setattr(mod, "BleakScanner", _Scanner)

    class _StaleClient:
        """Bound to an adapter that no longer exists: every reconnect fails."""

        async def async_update(self):
            raise RuntimeError("Failed to connect after 4 attempt(s): device not found")

        async def disconnect(self):
            pass

    built = []

    class _FreshClient:
        def __init__(self, ble_device):
            built.append(ble_device)

        async def connect(self):
            pass

        async def async_update(self):
            return {"voltage": 13.3, "current": 0.0, "battery_level": 81}

        async def disconnect(self):
            pass

    names = ("refresh_data", "_resolve_device", "_ensure_aiobmsble", "_aiobmsble_connect", "_aiobmsble_disconnect")
    bms = _borrow(mod, *names, "_reconnect_on_hold", "_note_connect_failure", "_note_connect_success")
    bms.address = "A4:C1:38:33:41:24"
    bms.AIOBMSBLE_CLASS = _FreshClient
    bms._aiobmsble = _StaleClient()  # connected at startup through an adapter since removed
    bms._aiobmsble_device = object()
    bms.aiobmsble_data = {"voltage": 13.2, "current": 0.0, "battery_level": 80}
    bms._last_successful_update = clock.now
    bms._max_data_age = 5
    bms._stale_warning_interval = 60
    bms._stale_warned_at = 0.0
    bms._connect_failures = 0
    bms._reconnect_hold_until = 0.0
    bms._reconnect_warned = False

    def _run_inline(coro):
        try:
            return bool(asyncio.run(coro()))
        except Exception:
            return False

    bms._poll_update = _run_inline

    # the link is lost; keep polling through the pacing until an attempt succeeds
    for _ in range(300):
        bms.refresh_data()
        if bms._connect_failures == 0 and built:
            break
        clock.now += 1

    assert resolved, "after a lost connection the device must be resolved afresh"
    assert built == [new_adapter_device], f"a new client must be built on the adapter that has the device, got {built}"
    assert bms.aiobmsble_data["battery_level"] == 81, "data must flow from the new client"
    assert bms._connect_failures == 0, "the successful reconnect must clear the pacing"


@_needs_pep604
def test_stale_data_warning_is_rate_limited(monkeypatch):
    mod = _load_driver()
    bms, _, log, clock = _refresh_with_device_gone(mod, monkeypatch)

    def stale_warnings():
        return [w for w in log.warnings if "treating as failure" in w]

    # 90 s of polling once a second: a warning when the spell starts and one
    # a minute later, not one per poll
    for _ in range(90):
        bms.refresh_data()
        clock.now += 1
    assert len(stale_warnings()) == 2, f"expected a warning at the start and one a minute on, got {len(stale_warnings())} in 90 polls"

    # good data ends the spell; the next one is reported when it starts, not
    # up to a minute late, because its onset is the line worth having
    bms._last_successful_update = clock.now
    clock.now += 10
    bms.refresh_data()
    assert len(stale_warnings()) == 3, "a new stale spell must be reported when it starts"
    assert log.errors == [], f"refresh_data swallowed an exception: {log.errors[:1]}"


@_needs_pep604
def test_poller_keeps_scheduling_updates():
    import threading
    import time

    mod = _load_driver()
    bms = _borrow(mod, "_poll_update", "_release_update_lock", "_ensure_event_loop")
    bms.address = "A4:C1:38:33:41:24"
    bms._loop = None
    bms._loop_thread = None
    bms._loop_ready = None
    bms._coro_lock = threading.Lock()
    bms._current_future = None
    bms._update_lock_held = False
    bms._update_started_at = None
    bms._run_timeout = 10

    async def update():
        return True

    completed = 0
    deadline = time.monotonic() + 5
    try:
        while completed < 5 and time.monotonic() < deadline:
            if bms._poll_update(update):
                completed += 1
            time.sleep(0.01)
    finally:
        if bms._loop is not None:
            bms._loop.call_soon_threadsafe(bms._loop.stop)
            bms._loop_thread.join(timeout=2)
    # a lock left held after a harvest stops every later update and logs
    # nothing, so the only way to see it is to count completed updates
    assert completed >= 5, f"the poller must keep harvesting and rescheduling updates; {completed} completed in 5 s"


@_needs_pep604
def test_resolve_device_prefers_the_bluez_cache(monkeypatch):
    import asyncio
    import types

    mod = _load_driver()
    scans = []
    cached = object()
    found_by_scan = object()
    cache = {"A4:C1:38:33:41:24": cached}

    class _Scanner:
        @staticmethod
        async def find_device_by_address(address):
            scans.append(address)
            return found_by_scan

    async def get_device(address):
        return cache.get(address)

    brc = types.ModuleType("bleak_retry_connector")
    brc.get_device = get_device
    monkeypatch.setitem(sys.modules, "bleak_retry_connector", brc)
    monkeypatch.setattr(mod, "BleakScanner", _Scanner)

    bms = _borrow(mod, "_resolve_device")
    bms.address = "A4:C1:38:33:41:24"

    # a device BlueZ already knows is returned without starting a discovery
    assert asyncio.run(bms._resolve_device()) is cached
    assert scans == [], "a cache hit must not start a discovery"

    # a device BlueZ has never seen still falls back to exactly one scan
    cache.clear()
    assert asyncio.run(bms._resolve_device()) is found_by_scan
    assert len(scans) == 1, "a cache miss must fall back to one scan"


@_needs_pep604
@pytest.mark.parametrize("stuck_in", ["scan", "connect", "update"])
def test_hung_reconnect_is_paced(monkeypatch, stuck_in):
    """An attempt that hangs until the poller cancels it counts as a failure.

    A scan waiting on an adapter another service holds never returns, and
    neither does a connect or a client reconnect stuck the same way; the
    poller cancels each at its timeout. If the cancellation is not counted,
    the pacing never engages and a fresh attempt starts after every timeout.
    """
    import asyncio
    import threading
    import time
    import types

    mod = _load_driver()
    attempts = []

    seen = []  # failures already counted when each attempt started

    async def _hang(stage):
        attempts.append(stage)
        seen.append(bms._connect_failures)
        # Never returns: cancelled by the poller. A nested task, not a bare
        # sleep, because that is how a real BlueZ await chain looks, and with a
        # bare sleep a count made inside the cancelled coroutine happens to land
        # in time - the shape that hid the late count.
        await asyncio.create_task(asyncio.sleep(3600))

    class _Scanner:
        @staticmethod
        async def find_device_by_address(address):
            if stuck_in == "scan":
                await _hang("scan")
            return object()  # found

    class _Client:
        async def connect(self):
            if stuck_in != "update":
                await _hang("connect")

        async def async_update(self):
            await _hang("update")

        async def disconnect(self):
            pass

    log = _Log()
    monkeypatch.setattr(mod, "BleakScanner", _Scanner)
    monkeypatch.setitem(sys.modules, "bleak_retry_connector", types.ModuleType("bleak_retry_connector"))
    monkeypatch.setattr(mod, "logger", log)

    names = ("refresh_data", "_poll_update", "_ensure_event_loop", "_release_update_lock", "_resolve_device")
    names += ("_ensure_aiobmsble", "_aiobmsble_connect", "_aiobmsble_disconnect")
    bms = _borrow(mod, *names, "_reconnect_on_hold", "_note_connect_failure", "_note_connect_success")
    bms.address = "A4:C1:38:33:41:24"
    bms.AIOBMSBLE_CLASS = lambda ble_device: _Client()
    bms._aiobmsble_device = None
    # "update": the battery was connected, so a client already exists
    bms._aiobmsble = _Client() if stuck_in == "update" else None
    bms.aiobmsble_data = {"voltage": 13.2, "current": 0.0, "battery_level": 80}
    bms._last_successful_update = time.monotonic() - 60
    bms._max_data_age = 5
    bms._stale_warning_interval = 60
    bms._stale_warned_at = 0.0
    bms._connect_failures = 0
    bms._reconnect_hold_until = 0.0
    bms._reconnect_warned = False
    bms._loop = None
    bms._loop_thread = None
    bms._loop_ready = None
    bms._coro_lock = threading.Lock()
    bms._current_future = None
    bms._update_lock_held = False
    bms._update_started_at = None
    bms._run_timeout = 0.2  # the real timeout is 10 s; the mechanism is the same

    try:
        # poll until two hung attempts have been counted; the second imposes a wait
        deadline = time.monotonic() + 5
        while bms._connect_failures < 2 and time.monotonic() < deadline:
            bms.refresh_data()
            time.sleep(0.02)
        assert bms._connect_failures >= 2, f"a hung {stuck_in} must count as a connect failure ({len(attempts)} attempts, {bms._connect_failures} counted)"

        # ...so no new attempt may start while that wait runs
        tried = len(attempts)
        end = time.monotonic() + 1.0
        while time.monotonic() < end:
            bms.refresh_data()
            time.sleep(0.02)
        assert len(attempts) == tried, f"a new attempt started while paced ({len(attempts) - tried} extra)"
        # and every hung attempt was counted, not just some of them
        assert bms._connect_failures == len(attempts), f"{len(attempts)} hung attempts ({attempts}) but {bms._connect_failures} counted"
        # ...and counted BEFORE the next attempt started, or the pacing is one
        # attempt late: attempt n must see the n failures before it
        assert seen == list(range(len(seen))), f"attempts started having seen {seen} failures; expected {list(range(len(seen)))}"
    finally:
        if bms._loop is not None:
            bms._loop.call_soon_threadsafe(bms._loop.stop)
            bms._loop_thread.join(timeout=2)

    # the only errors expected are the poller's own timeouts
    unexpected = [e for e in log.errors if "coroutine timed out" not in e]
    assert unexpected == [], f"refresh_data swallowed an exception: {unexpected[:1]}"


@_needs_pep604
def test_failed_scan_is_paced(monkeypatch):
    """A scan that fails outright, e.g. org.bluez.Error.InProgress, counts too.

    Such a failure raises out of the lookup instead of returning "not found".
    Uncounted, it was retried on every poll - the discovery storm the
    cache-first lookup exists to prevent - and silently, at debug level.
    """
    mod = _load_driver()
    bms, _, log, clock = _refresh_with_device_gone(mod, monkeypatch)
    scans = []

    class _BusyScanner:
        @staticmethod
        async def find_device_by_address(address):
            scans.append(address)
            raise RuntimeError("org.bluez.Error.InProgress")

    monkeypatch.setattr(mod, "BleakScanner", _BusyScanner)

    for _ in range(120):
        bms.refresh_data()
    assert bms._connect_failures >= 2, "a scan that raises must count as a connect failure"
    assert len(scans) < 12, f"a failing scan must not be retried on every poll ({len(scans)} scans in 120 polls)"
    assert log.errors == [], f"refresh_data swallowed an exception: {log.errors[:1]}"


@_needs_pep604
def test_first_failure_of_an_outage_is_visible(monkeypatch):
    """The first failed attempt of an outage logs a warning; the rest stay quiet.

    A failed find or connect raises out of the update, and the poller used to
    log that only at debug: an outage of a battery the driver has not yet
    connected showed nothing until the pacing's own warning, minutes later.
    """
    import threading
    import time

    mod = _load_driver()
    log = _Log()
    monkeypatch.setattr(mod, "logger", log)
    bms = _borrow(mod, "_poll_update", "_ensure_event_loop", "_release_update_lock", "_note_connect_failure")
    bms.address = "A4:C1:38:33:41:24"
    bms._loop = None
    bms._loop_thread = None
    bms._loop_ready = None
    bms._coro_lock = threading.Lock()
    bms._current_future = None
    bms._update_lock_held = False
    bms._update_started_at = None
    bms._run_timeout = 10
    bms._connect_failures = 0
    bms._reconnect_hold_until = 0.0
    bms._reconnect_warned = False
    done = []

    async def failing_attempt():
        # what the reconnect branch does: count the failure, then raise
        bms._note_connect_failure("device not found")
        done.append(1)
        raise RuntimeError("device not found")

    try:
        deadline = time.monotonic() + 5
        while len(done) < 5 and time.monotonic() < deadline:
            bms._poll_update(failing_attempt)
            time.sleep(0.02)
        # let the attempt the last poll scheduled run before the loop stops, so
        # no coroutine is left un-awaited
        time.sleep(0.05)
    finally:
        if bms._loop is not None:
            bms._loop.call_soon_threadsafe(bms._loop.stop)
            bms._loop_thread.join(timeout=2)

    shown = [w for w in log.warnings if "background update failed" in w]
    assert len(done) >= 5, f"expected at least 5 attempts, got {len(done)}"
    assert len(shown) == 1, f"one warning for the first failure of an outage, got {len(shown)}"


@_needs_pep604
def test_startup_reading_starts_the_data_age_clock(monkeypatch):
    """The first reading, taken by test_connection, arms the staleness check.

    test_connection reads the battery once, then refresh_data only schedules
    the first background update. If the data-age clock waited for that update,
    a battery that went away right after startup would have its startup
    reading published as current for as long as it stayed away.
    """
    mod = _load_driver()
    log, clock = _Log(), _Clock()
    monkeypatch.setattr(mod, "logger", log)
    monkeypatch.setattr(mod, "time", clock)

    names = ("test_connection", "refresh_data")
    bms = _borrow(mod, *names, "_reconnect_on_hold", "_note_connect_failure", "_note_connect_success")
    bms.address = "A4:C1:38:33:41:24"
    bms.BATTERYTYPE = "test"
    bms._initial_connect_timeout = 40
    bms.aiobmsble_data = {"voltage": 13.2, "current": 0.0, "battery_level": 80}  # the startup reading
    bms._aiobmsble = object()
    bms._last_successful_update = None
    bms._max_data_age = 5
    bms._stale_warning_interval = 60
    bms._stale_warned_at = 0.0
    bms._connect_failures = 0
    bms._reconnect_hold_until = 0.0
    bms._reconnect_warned = False

    # The startup read itself succeeds; what is under test is what follows it.
    timeouts = []
    bms._run_coro = lambda coro, timeout=None: timeouts.append(timeout) or True
    bms.get_settings = lambda: True
    bms.refresh_data = lambda: True  # test_connection's own final refresh is not under test
    bms.disconnect = lambda: None
    assert bms.test_connection() is True
    del bms.refresh_data  # the real refresh_data from here on

    # the first connection gets its own, longer budget than a refresh
    assert timeouts == [bms._initial_connect_timeout], f"the startup read must use the first-connect budget, got {timeouts}"

    # the battery goes away: no background update ever completes
    bms._poll_update = lambda coro: False
    clock.now += bms._max_data_age + 1
    assert bms.refresh_data() is False, "a startup reading past its age limit must not be reported as current"
    assert any("treating as failure" in w for w in log.warnings), "the stale startup reading must be reported"
    assert log.errors == [], f"refresh_data swallowed an exception: {log.errors[:1]}"
