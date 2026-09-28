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

    bms = _borrow(mod, "refresh_data", "_resolve_device", "_reconnect_on_hold", "_note_connect_failure", "_note_connect_success")
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
    # _poll_update's job and is tested separately
    bms._poll_update = lambda coro: bool(asyncio.run(coro()))
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
