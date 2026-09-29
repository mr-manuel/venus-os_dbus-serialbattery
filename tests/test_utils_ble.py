# -*- coding: utf-8 -*-
"""Tests for the pure logic in utils_ble: connection backend selection.

utils_ble imports bleak, which is not installed on the machines this suite
runs on (and is Linux/BlueZ specific in practice). A minimal module stub is
registered before the import so the non-BLE logic can be exercised for real.
Everything that actually talks to a radio is left untested here.
"""

import configparser
import importlib.util
import logging
import os
import pytest
import re
import sys
import time
import types

DRIVER_DIR = os.path.join(os.path.dirname(__file__), "..", "dbus-serialbattery")
CONFIG_DEFAULT = os.path.join(DRIVER_DIR, "config.default.ini")
sys.path.insert(0, DRIVER_DIR)

if "bleak" not in sys.modules:
    sys.modules["bleak"] = types.SimpleNamespace(BleakClient=type("BleakClient", (), {"__init__": lambda self, *a, **kw: None}))
    sys.modules["bleak"].BleakScanner = object
    _bleak_error = type("BleakError", (Exception,), {})
    sys.modules["bleak"].exc = types.SimpleNamespace(
        BleakError=_bleak_error,
        BleakCharacteristicNotFoundError=type("BleakCharacteristicNotFoundError", (_bleak_error,), {}),
    )
    sys.modules["bleak.exc"] = sys.modules["bleak"].exc
if "bleak_retry_connector" not in sys.modules:
    # utils_ble only needs these four names; stubbing keeps BleakRetryBackend
    # in supported_ble_backends so the generic backend tests cover it too.
    async def _not_under_test(*args, **kwargs):
        raise NotImplementedError

    sys.modules["bleak_retry_connector"] = types.SimpleNamespace(
        close_stale_connections=_not_under_test,
        establish_connection=_not_under_test,
        get_device=_not_under_test,
        get_device_by_adapter=_not_under_test,
    )


def _load_utils_ble():
    """Load the real utils_ble under a private module name.

    tests/bms/test_litime_ble.py registers a stub under "utils_ble" in
    sys.modules and is collected first, so a plain import would pick up that
    stub. Load the module from disk under a different name instead, leaving
    sys.modules["utils_ble"] alone in both directions.
    """
    spec = importlib.util.spec_from_file_location("utils_ble_under_test", os.path.join(DRIVER_DIR, "utils_ble.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


utils_ble = _load_utils_ble()


def _config_default():
    parser = configparser.ConfigParser()
    with open(CONFIG_DEFAULT) as f:
        parser.read_file(f)
    return parser["DEFAULT"]


def test_backend_lookup_returns_requested_backend():
    backend = utils_ble.get_ble_backend("BleakBackend")
    assert isinstance(backend, utils_ble.BleakBackend)


def test_backend_lookup_falls_back_to_bleak_for_unknown_name():
    backend = utils_ble.get_ble_backend("NoSuchBackend")
    assert isinstance(backend, utils_ble.BleakBackend)


def test_every_supported_backend_is_selectable_by_its_class_name():
    """The registry is keyed by class name, so every entry must resolve to itself."""
    for cls in utils_ble.supported_ble_backends:
        assert type(utils_ble.get_ble_backend(cls.__name__)) is cls


def test_config_default_backend_name_resolves_without_falling_back():
    """The shipped default must name a real backend, not silently fall back."""
    configured = _config_default()["BLUETOOTH_CONNECTION_BACKEND"].strip()
    assert configured in [cls.__name__ for cls in utils_ble.supported_ble_backends]
    assert type(utils_ble.get_ble_backend(configured)).__name__ == configured


def test_plain_entries_form_the_pool_and_pin_nothing():
    pins, pool = utils_ble.parse_adapter_entries(["hci1", "hci2"])
    assert pins == {}
    assert pool == ["hci1", "hci2"]


def test_pool_order_is_preserved():
    """Rotation walks the pool in configured order, so order must survive parsing."""
    _, pool = utils_ble.parse_adapter_entries(["hci2", "hci0", "hci1"])
    assert pool == ["hci2", "hci0", "hci1"]


def test_mac_at_adapter_entries_pin_and_stay_out_of_the_pool():
    pins, pool = utils_ble.parse_adapter_entries(["C8:47:8C:00:00:00@hci1", "C8:47:8C:00:00:11@hci2"])
    assert pins == {"C8:47:8C:00:00:00": ["hci1"], "C8:47:8C:00:00:11": ["hci2"]}
    # a pinned MAC is not an adapter name and must never be handed to bleak
    assert pool == []


def test_pins_and_pool_can_be_mixed():
    pins, pool = utils_ble.parse_adapter_entries(["hci0", "C8:47:8C:00:00:00@hci1"])
    assert pins == {"C8:47:8C:00:00:00": ["hci1"]}
    assert pool == ["hci0"]


def test_entries_are_whitespace_and_case_normalized():
    pins, pool = utils_ble.parse_adapter_entries([" c8:47:8c:00:00:00 @ hci1 ", " hci0 "])
    assert pins == {"C8:47:8C:00:00:00": ["hci1"]}
    assert pool == ["hci0"]


def test_malformed_entries_are_dropped_rather_than_pinned():
    pins, pool = utils_ble.parse_adapter_entries(["@hci1", "C8:47:8C:00:00:00@", "", "  ", "hci3"])
    assert pins == {}
    assert pool == ["hci3"]


def test_empty_config_pins_and_pools_nothing():
    pins, pool = utils_ble.parse_adapter_entries([])
    assert pins == {}
    assert pool == []


def test_config_default_adapters_is_empty_so_the_default_adapter_is_used():
    assert _config_default()["BLUETOOTH_ADAPTERS"].strip() == ""
    pins, pool = utils_ble.parse_adapter_entries([])
    assert not pins and not pool


def test_adapters_for_matches_a_pinned_device_regardless_of_case():
    original = utils_ble.BLUETOOTH_ADAPTER_PINS
    utils_ble.BLUETOOTH_ADAPTER_PINS = {"C8:47:8C:00:00:00": ["hci1"]}
    try:
        assert utils_ble.adapters_for("c8:47:8c:00:00:00") == ["hci1"]
        assert utils_ble.adapters_for("C8:47:8C:00:00:00") == ["hci1"]
        # an unpinned device falls through to the shared pool
        assert utils_ble.adapters_for("C8:47:8C:00:00:11") is None
    finally:
        utils_ble.BLUETOOTH_ADAPTER_PINS = original


def test_hold_flag_path_normalizes_the_mac_address():
    """One battery, one flag file — regardless of how the MAC was written."""
    lower = utils_ble.ble_hold_flag_path("c8:47:8c:00:00:00")
    upper = utils_ble.ble_hold_flag_path("C8:47:8C:00:00:00")
    assert lower == upper
    assert os.path.basename(lower) == "ble-hold-c8478c000000"
    assert os.path.dirname(lower) == utils_ble.BLE_HOLD_FLAG_DIR


def test_hold_flag_paths_differ_per_device():
    assert utils_ble.ble_hold_flag_path("C8:47:8C:00:00:00") != utils_ble.ble_hold_flag_path("C8:47:8C:00:00:11")


def test_backends_implement_the_connection_interface():
    """Every backend must be usable through the seam Syncron_Ble drives."""
    for cls in utils_ble.supported_ble_backends:
        assert issubclass(cls, utils_ble.BleConnectionBackend)
        for method in ("create_client", "establish", "release"):
            assert getattr(cls, method) is not getattr(utils_ble.BleConnectionBackend, method)


def test_a_mac_repeated_pins_several_adapters_in_priority_order():
    # first entry is the primary, the rest are only tried if it cannot resolve
    pins, pool = utils_ble.parse_adapter_entries(["AA:BB@hci4", "CC:DD@hci5", "AA:BB@hci2"])

    assert pins == {"AA:BB": ["hci4", "hci2"], "CC:DD": ["hci5"]}
    assert pool == []


def test_a_repeated_pin_to_the_same_adapter_is_not_duplicated():
    pins, _ = utils_ble.parse_adapter_entries(["AA:BB@hci4", "AA:BB@hci4"])

    assert pins == {"AA:BB": ["hci4"]}


def _configure(devices, pool):
    utils_ble.BLUETOOTH_ADAPTER_PINS = devices
    utils_ble.BLUETOOTH_ADAPTER_POOL = pool


def test_an_adapter_bluez_does_not_expose_is_skipped():
    """
    The failure this exists for: a USB reset renumbers the radios, the adapter
    a battery is configured for stops existing, and asking BlueZ for it by
    name fails forever. The battery has to reach its next adapter instead.
    """
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({"C8:47:8C:00:00:00": ["hci5", "hci6"]}, [])
    try:
        assert utils_ble.adapters_in_attempt_order("C8:47:8C:00:00:00", present={"hci6"}) == ["hci6"]
    finally:
        _configure(original_pins, original_pool)


def test_a_battery_is_never_stranded_when_bluez_knows_none_of_its_adapters():
    """
    An empty or odd answer from BlueZ must degrade to the configured order,
    not to an empty list - refusing to attempt a connection is worse than
    trying an adapter that may not be there.
    """
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({"C8:47:8C:00:00:00": ["hci5", "hci6"]}, [])
    try:
        assert utils_ble.adapters_in_attempt_order("C8:47:8C:00:00:00", present=set()) == ["hci5", "hci6"]
        assert utils_ble.adapters_in_attempt_order("C8:47:8C:00:00:00", present={"hci9"}) == ["hci5", "hci6"]
    finally:
        _configure(original_pins, original_pool)


def test_a_battery_advances_to_its_next_adapter_after_a_failed_attempt():
    """
    Why multi-adapter entries exist: the preferred radio can vanish, and the
    battery has to reach its second one or the driver blocks charging for a
    bank that is perfectly healthy.
    """
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({"C8:47:8C:00:00:00": ["hci5", "hci6"]}, [])
    try:
        backend = utils_ble.get_ble_backend("BleakBackend")
        monkey = lambda address, present=None: ["hci5", "hci6"]  # noqa: E731
        original = utils_ble.adapters_in_attempt_order
        utils_ble.adapters_in_attempt_order = monkey
        try:
            assert backend._select_adapter("C8:47:8C:00:00:00") == "hci5"
            backend.adapter_index += 1
            assert backend._select_adapter("C8:47:8C:00:00:00") == "hci6"
            # and round again, so a radio that comes back is reachable
            backend.adapter_index += 1
            assert backend._select_adapter("C8:47:8C:00:00:00") == "hci5"
        finally:
            utils_ble.adapters_in_attempt_order = original
    finally:
        _configure(original_pins, original_pool)


def test_a_failed_connect_is_what_advances_the_adapter():
    import asyncio

    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({"C8:47:8C:00:00:00": ["hci5", "hci6"]}, [])
    original = utils_ble.adapters_in_attempt_order
    utils_ble.adapters_in_attempt_order = lambda address, present=None: ["hci5", "hci6"]
    try:
        backend = utils_ble.get_ble_backend("BleakBackend")
        backend.create_client("C8:47:8C:00:00:00", None)
        assert backend.current_adapter == "hci5"
        try:
            asyncio.run(backend.establish(None, "C8:47:8C:00:00:00", "char", None))
        except Exception:
            pass
        backend.create_client("C8:47:8C:00:00:00", None)
        assert backend.current_adapter == "hci6"
    finally:
        utils_ble.adapters_in_attempt_order = original
        _configure(original_pins, original_pool)


def test_a_dropped_link_reconnects_on_the_same_adapter():
    """
    A disconnect is not a failed attempt: the reconnect loop calls
    create_client again without establish() having raised, and that must not
    move the battery off a radio that is working.
    """
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({"C8:47:8C:00:00:00": ["hci5", "hci6"]}, [])
    original = utils_ble.adapters_in_attempt_order
    utils_ble.adapters_in_attempt_order = lambda address, present=None: ["hci5", "hci6"]
    try:
        backend = utils_ble.get_ble_backend("BleakBackend")
        for _ in range(5):
            backend.create_client("C8:47:8C:00:00:00", None)
            assert backend.current_adapter == "hci5"
    finally:
        utils_ble.adapters_in_attempt_order = original
        _configure(original_pins, original_pool)


def test_a_battery_with_its_own_adapters_never_uses_the_default_pool():
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({"C8:47:8C:00:00:00": ["hci5"]}, ["hci0", "hci1"])
    try:
        assert utils_ble.adapters_in_attempt_order("C8:47:8C:00:00:00", present={"hci5", "hci0", "hci1"}) == ["hci5"]
    finally:
        _configure(original_pins, original_pool)


def test_bluez_state_is_unavailable_rather_than_raising_without_dbus():
    """utils_ble must stay importable and usable where python-dbus is absent."""
    assert utils_ble.bluez_present_adapters() == set()


def test_bleak_retry_backend_registers_when_the_connector_is_importable():
    assert utils_ble.HAS_BLEAK_RETRY_CONNECTOR
    assert utils_ble.BleakRetryBackend in utils_ble.supported_ble_backends


def test_bleak_retry_backend_defers_client_creation_to_establish():
    backend = utils_ble.get_ble_backend("BleakRetryBackend")
    sentinel = object()
    assert backend.create_client("C8:47:8C:00:00:00", sentinel) is None
    assert backend.disconnected_callback is sentinel


def test_bleak_retry_backend_rotates_after_a_failed_attempt():
    import asyncio

    original = utils_ble.adapters_in_attempt_order
    utils_ble.adapters_in_attempt_order = lambda address, present=None: ["hci5", "hci6"]
    try:
        backend = utils_ble.get_ble_backend("BleakRetryBackend")
        backend.create_client("C8:47:8C:00:00:00", None)
        assert backend.current_adapter == "hci5"
        try:
            asyncio.run(backend.establish(None, "C8:47:8C:00:00:00", "char", None))
        except Exception:
            pass
        backend.create_client("C8:47:8C:00:00:00", None)
        assert backend.current_adapter == "hci6"
    finally:
        utils_ble.adapters_in_attempt_order = original


def test_the_retry_connector_establish_is_aliased_against_shadowing():
    """
    Managed backends stacked on this branch import establish_connection from
    their own library later in the module; the alias is what keeps this
    backend calling the right one, and no other test reaches the connect path.
    """
    assert utils_ble.retry_establish_connection is sys.modules["bleak_retry_connector"].establish_connection


# --------- subscribing before BlueZ has the whole GATT tree ---------
#
# BlueZ can report a device's services as resolved while its own view of the
# tree is still incomplete, so start_notify raises for a characteristic the
# battery genuinely has and the driver reconnects forever against working
# hardware. Observed on a Cerbo GX with the same vendored bleak this branch
# ships, so reading the connect path as safe is not enough.


class _GattClient:
    """A client whose characteristic only appears after N tree rebuilds."""

    def __init__(self, appears_after=0, backend=None):
        self.appears_after = appears_after
        self.rebuilds = 0
        self.subscribed = None
        self.dropped_before_rebuild = None
        if backend is not None:
            self._backend = backend
        else:
            self._backend = types.SimpleNamespace(services=object(), _get_services=self._rebuild)

    async def _rebuild(self):
        self.dropped_before_rebuild = self._backend.services is None
        self.rebuilds += 1
        self._backend.services = object()

    async def start_notify(self, char, callback):
        if self.rebuilds < self.appears_after:
            raise _CharacteristicNotFound(char)
        self.subscribed = (char, callback)


_CharacteristicNotFound = sys.modules["bleak.exc"].BleakCharacteristicNotFoundError


def test_a_resolved_characteristic_is_subscribed_without_rebuilding_anything():
    """The common case must not pay for the recovery: no rebuild, no sleep."""
    import asyncio

    client = _GattClient(appears_after=0)
    asyncio.run(utils_ble.start_notify_when_resolved(client, "char", "callback"))
    assert client.subscribed == ("char", "callback")
    assert client.rebuilds == 0


def test_a_missing_characteristic_rebuilds_the_tree_and_subscribes():
    import asyncio

    original = utils_ble.GATT_REDISCOVERY_SETTLE
    utils_ble.GATT_REDISCOVERY_SETTLE = 0
    try:
        client = _GattClient(appears_after=1)
        asyncio.run(utils_ble.start_notify_when_resolved(client, "char", "callback"))
    finally:
        utils_ble.GATT_REDISCOVERY_SETTLE = original
    assert client.subscribed == ("char", "callback")
    assert client.rebuilds == 1


def test_the_rebuild_drops_the_stale_tree_first():
    """
    _get_services returns the collection it already holds, so a rebuild that
    does not drop it first is a no-op that looks like a retry.
    """
    import asyncio

    client = _GattClient()
    asyncio.run(utils_ble.rediscover_services(client, "char"))
    assert client.dropped_before_rebuild is True


def test_a_characteristic_that_never_appears_gives_up_instead_of_looping():
    import asyncio

    original = utils_ble.GATT_REDISCOVERY_SETTLE
    utils_ble.GATT_REDISCOVERY_SETTLE = 0
    try:
        client = _GattClient(appears_after=99)
        try:
            asyncio.run(utils_ble.start_notify_when_resolved(client, "char", "callback"))
            raise AssertionError("a characteristic that is really absent must surface")
        except _CharacteristicNotFound:
            pass
    finally:
        utils_ble.GATT_REDISCOVERY_SETTLE = original
    assert client.rebuilds == utils_ble.GATT_REDISCOVERY_ATTEMPTS - 1


def test_a_bleak_that_moves_the_rebuild_call_fails_loudly():
    """
    The rebuild reaches into bleak's backend because bleak exposes no public
    way to discard a resolved tree. A bleak that renames it must raise here,
    not quietly stop rediscovering and restore the endless reconnect.
    """
    import asyncio

    client = _GattClient(appears_after=99, backend=types.SimpleNamespace())
    try:
        asyncio.run(utils_ble.rediscover_services(client, "char"))
        raise AssertionError("a missing backend call must be reported, not ignored")
    except utils_ble.BleakError as e:
        assert "_get_services" in str(e)


def test_neither_backend_subscribes_without_the_rebuild_guard():
    """
    Both backends reach start_notify by the same route, so a fix applied to
    one of them ships a half fix that looks repaired and fails on the other.
    """
    import inspect

    for backend in (utils_ble.BleakBackend, utils_ble.BleakRetryBackend):
        source = inspect.getsource(backend._establish)
        assert "start_notify_when_resolved(" in source
        assert "client.start_notify(" not in source


# --------- which adapter the link actually landed on ---------
#
# The adapter a backend asks for and the one the link comes up on are not the
# same thing: bleak-retry-connector swaps in BlueZ's already-connected copy
# when a link lingers on another card, so state keyed to the request then
# describes the wrong radio.


def _client_on(path):
    return types.SimpleNamespace(_backend=types.SimpleNamespace(_device_path=path))


def test_the_landed_adapter_comes_from_bluez_s_own_object_path():
    assert utils_ble.landed_adapter(_client_on("/org/bluez/hci3/dev_C8_47_8C_00_00_00")) == "hci3"


def test_a_two_digit_adapter_is_not_truncated():
    """hci1 must never be read out of hci10 - the box has ten radios."""
    assert utils_ble.landed_adapter(_client_on("/org/bluez/hci10/dev_C8_47_8C_00_00_00")) == "hci10"


def test_an_unreadable_path_is_unknown_rather_than_the_requested_name():
    """
    A bleak that moves the attribute must degrade to "we cannot tell", never
    to "it landed where we asked" - the second is a lie the log would repeat.
    """
    assert utils_ble.landed_adapter(_client_on(None)) is None
    assert utils_ble.landed_adapter(types.SimpleNamespace()) is None
    assert utils_ble.landed_adapter(_client_on("/org/bluez/dev_C8_47_8C_00_00_00")) is None


def test_the_landed_adapter_replaces_the_requested_one_in_backend_state():
    backend = utils_ble.get_ble_backend("BleakBackend")
    backend.current_adapter = "hci5"
    landed = backend._record_landed(_client_on("/org/bluez/hci3/dev_C8_47_8C_00_00_00"))
    assert landed == "hci3"
    assert backend.current_adapter == "hci3"
    # the request is kept, because the two differing is the signal
    assert backend.requested_adapter == "hci5"


def test_an_unknown_landing_leaves_the_requested_adapter_alone():
    backend = utils_ble.get_ble_backend("BleakBackend")
    backend.current_adapter = "hci5"
    assert backend._record_landed(types.SimpleNamespace()) is None
    assert backend.current_adapter == "hci5"
    assert backend.landed_adapter_name is None


def test_only_the_scanning_backend_reports_that_it_scans():
    """
    A scan count of zero means "cache hit every time" on a backend that can
    scan, and nothing at all on one that cannot; the two must be tellable
    apart or the count is unreadable.
    """
    assert utils_ble.get_ble_backend("BleakRetryBackend").scans_devices is True
    assert utils_ble.get_ble_backend("BleakBackend").scans_devices is False


def test_a_link_coming_up_is_reported_through_the_seam_not_the_connect_path():
    """
    The disconnect is delivered by a callback the backend invokes, so a driver
    that replaces connect_to_bms still opens episodes. The link-up used to be
    reported from inside connect_to_bms, so that same driver never closed
    them and a watch saw episodes that ran forever. Both ends now arrive by
    the same route: either a driver gets both or it gets neither.
    """
    reported = []
    backend = utils_ble.get_ble_backend("BleakBackend")
    backend.connected_callback = lambda: reported.append(True)
    backend.current_adapter = "hci5"
    backend._record_landed(_client_on("/org/bluez/hci3/dev_C8_47_8C_00_00_00"))
    assert reported == [True]


def test_the_driver_wires_the_seam_at_every_place_it_takes_a_backend():
    """A second construction site that forgets the wiring is the same defect again."""
    battery = utils_ble.Syncron_Ble.__new__(utils_ble.Syncron_Ble)
    battery.address = "C8:47:8C:00:00:00"
    backend = battery._new_backend()
    assert backend.connected_callback == battery._report_link_up
    source = _utils_ble_source()
    # the driver must not obtain a backend any other way
    assert source.count("get_ble_backend()") == 1


def test_a_drop_landing_mid_attempt_does_not_rewrite_that_attempt(caplog, monkeypatch):
    """
    The disconnect callback arrives at any moment, including part-way through
    the connect that is about to succeed - a link left by a previous process
    is delivered to its successor on restart. Resetting the counters there
    reported a connection that took one attempt as having taken none.
    """
    monkeypatch.setattr(utils_ble, "bluez_adapters", _adapters_named)
    battery = _EpisodeBattery(_scanning_backend())
    battery._first_link_reported = True
    battery._attempts = 1
    # the stale link's callback lands while this attempt is still in flight
    battery.client_disconnected(None)
    assert battery._attempts == 1
    battery._report_link_up()
    # and the drop it recorded belongs to the link that just came back, so it
    # must not open an episode on the next pass through the loop
    battery._begin_pending_episode()
    assert battery._episode_started is None


def test_a_drop_before_a_life_has_a_link_is_not_an_episode(caplog, monkeypatch):
    """
    A callback for a link this process never had opens an outage that never
    happened: the first connection then closes it without a recovery line,
    and anything counting openings against recoveries is off by one for the
    life of the driver.
    """
    monkeypatch.setattr(utils_ble, "bluez_adapters", _adapters_named)
    battery = _EpisodeBattery(_scanning_backend())
    with caplog.at_level("INFO", logger="SerialBattery"):
        battery.client_disconnected(None)
    battery._begin_pending_episode()
    assert battery._episode_started is None
    # the event itself is still reported - it happened, and a watch keys on it
    assert "disconnected" in caplog.messages[-1]


def test_an_outage_is_dated_from_its_first_callback_not_its_last(monkeypatch, caplog):
    """
    BlueZ delivers two or three disconnect callbacks for one outage. Dating
    the episode from the latest one measures from the last callback rather
    than from when the link went down, and under-reports the outage by the
    gap between them - measured at up to ~5 s on a production pack.
    """
    monkeypatch.setattr(utils_ble, "bluez_adapters", _adapters_named)
    battery = _EpisodeBattery(_scanning_backend())
    battery._first_link_reported = True

    clock = [1000.0]
    monkeypatch.setattr(utils_ble.time, "time", lambda: clock[0])
    battery.client_disconnected(None)
    clock[0] = 1005.0
    battery.client_disconnected(None)  # the same outage, delivered again
    battery._begin_pending_episode()
    assert battery._episode_started == 1000.0

    # a further callback while the episode is already open must not re-stamp it
    clock[0] = 1007.0
    battery.client_disconnected(None)
    battery._begin_pending_episode()
    assert battery._episode_started == 1000.0

    clock[0] = 1010.0
    with caplog.at_level("INFO", logger="SerialBattery"):
        battery._report_link_up()
    assert "after 10.0 s" in caplog.messages[-1]


# --------- a pin that stops being honoured says so ---------
#
# Dropping unresolvable MAC entries is correct - a MAC is not a name bleak
# can use - but the effect is that an explicit pin quietly stops applying and
# the battery goes out on whatever radio is left. That is the failure the
# option exists to prevent, arriving by a different route.

PINNED = "C8:47:8C:00:00:00"


def _pin(mac_entries, pool=None):
    utils_ble._unpinned_devices.discard(PINNED)
    _configure({PINNED: list(mac_entries)}, list(pool or []))


def test_a_pin_that_resolves_to_nothing_is_warned_about(caplog):
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _pin(["00:1A:7D:DA:71:13"])
    try:
        with caplog.at_level("WARNING", logger="SerialBattery"):
            # falls back to the adapter that is present, not to bleak's default
            assert utils_ble.adapters_in_attempt_order(PINNED, present={"hci9"}) == ["hci9"]
        assert "adapter pins for C8:47:8C:00:00:00 are not being honoured" in caplog.messages[0]
        assert "00:1A:7D:DA:71:13" in caplog.messages[0]
        # both causes, because they need different repairs: a swapped card is
        # repinned, an unreadable identity is fixed at hciconfig. Naming only
        # one sends the reader to the wrong check - a swapped dongle on dev
        # cost 18 h of unreachability with hciconfig working perfectly.
        assert "removed or swapped" in caplog.messages[0]
        assert "hciconfig" in caplog.messages[0]
        # and what the fallback actually is, since it is not necessarily benign
        assert "Falling back to hci9" in caplog.messages[0]
    finally:
        _configure(original_pins, original_pool)
        utils_ble._unpinned_devices.discard(PINNED)


def test_with_no_adapters_present_at_all_the_warning_names_the_system_default(caplog):
    """
    The one case that still reaches bleak's default: nothing is present to
    fall back TO. Worth naming, because the default is a card chosen by
    BlueZ for reasons unrelated to this driver.
    """
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _pin(["00:1A:7D:DA:71:13"])
    try:
        with caplog.at_level("WARNING", logger="SerialBattery"):
            assert utils_ble.adapters_in_attempt_order(PINNED, present={}) == []
        assert "system default adapter" in caplog.messages[0]
    finally:
        _configure(original_pins, original_pool)
        utils_ble._unpinned_devices.discard(PINNED)


def test_the_warning_is_not_repeated_on_every_attempt(caplog):
    """A battery on the 6 s ramp would repeat it ten times a minute."""
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _pin(["00:1A:7D:DA:71:13"])
    try:
        with caplog.at_level("WARNING", logger="SerialBattery"):
            for _ in range(10):
                utils_ble.adapters_in_attempt_order(PINNED, present={"hci9"})
        assert len(caplog.messages) == 1
    finally:
        _configure(original_pins, original_pool)
        utils_ble._unpinned_devices.discard(PINNED)


def test_a_card_reappearing_does_not_by_itself_re_arm_the_warning(caplog):
    """
    Re-armed on a CONNECTION with resolving pins, not on the card merely
    reappearing in the BlueZ table. The connection manager warns about the
    same condition and re-arms on connect; a watch counts both, so a card
    flapping in and out would make one count climb while the other stood
    still and the first reader would file a layer as broken.
    """
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _pin(["00:1A:7D:DA:71:13"])
    try:
        with caplog.at_level("WARNING", logger="SerialBattery"):
            utils_ble.adapters_in_attempt_order(PINNED, present={"hci9"})
            for _ in range(3):
                # the card comes back and goes again, with no connection between
                utils_ble.adapters_in_attempt_order(PINNED, present={"hci3": "00:1A:7D:DA:71:13"})
                utils_ble.adapters_in_attempt_order(PINNED, present={"hci9"})
        assert len(caplog.messages) == 1
    finally:
        _configure(original_pins, original_pool)
        utils_ble._unpinned_devices.discard(PINNED)


def test_a_connection_with_the_pins_resolving_re_arms_the_warning(caplog):
    """A second genuine loss, after the pins were honoured again, is reported."""
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _pin(["00:1A:7D:DA:71:13"])
    try:
        with caplog.at_level("WARNING", logger="SerialBattery"):
            utils_ble.adapters_in_attempt_order(PINNED, present={"hci9"})
            utils_ble._note_pins_honoured(PINNED, adapters={"hci3": "00:1A:7D:DA:71:13"})
            utils_ble.adapters_in_attempt_order(PINNED, present={"hci9"})
        assert len(caplog.messages) == 2
    finally:
        _configure(original_pins, original_pool)
        utils_ble._unpinned_devices.discard(PINNED)


def test_a_connection_while_the_pins_still_fail_does_not_re_arm(caplog):
    """
    Connecting on a FALLBACK card is not the pins being honoured - that is
    the condition still holding, and re-arming there would warn again on the
    next attempt with nothing having changed.
    """
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _pin(["00:1A:7D:DA:71:13"])
    try:
        with caplog.at_level("WARNING", logger="SerialBattery"):
            utils_ble.adapters_in_attempt_order(PINNED, present={"hci9"})
            utils_ble._note_pins_honoured(PINNED, adapters={"hci9": "00:01:95:00:00:09"})
            utils_ble.adapters_in_attempt_order(PINNED, present={"hci9"})
        assert len(caplog.messages) == 1
    finally:
        _configure(original_pins, original_pool)
        utils_ble._unpinned_devices.discard(PINNED)


def test_an_unresolvable_hci_name_is_not_a_dropped_pin(caplog):
    """
    hciN entries are returned unfiltered when nothing resolves - that is the
    deliberate no-strand fallback, not a pin being lost, and warning about it
    would fire on every box whose adapters are simply not enumerable.
    """
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _pin(["hci7"])
    try:
        with caplog.at_level("WARNING", logger="SerialBattery"):
            assert utils_ble.adapters_in_attempt_order(PINNED, present=set()) == ["hci7"]
        assert caplog.messages == []
    finally:
        _configure(original_pins, original_pool)
        utils_ble._unpinned_devices.discard(PINNED)


# --------- a strict pin waits rather than falling back ---------
#
# The default is to warn and connect over whatever is present: a battery
# working on the wrong radio beats a battery not working. A strict pin says
# the opposite, for the case where the pin is protecting something.


def test_a_configured_adapter_that_is_present_satisfies_the_pin():
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({PINNED: ["00:1A:7D:DA:71:13"]}, [])
    try:
        assert utils_ble.configured_adapter_present(PINNED, present={"hci3": "00:1A:7D:DA:71:13"}) is True
        assert utils_ble.configured_adapter_present(PINNED, present={"hci9": "00:01:95:00:00:09"}) is False
    finally:
        _configure(original_pins, original_pool)


def test_a_battery_naming_no_adapters_is_never_waiting_for_one():
    """It never asked for a particular radio, so there is nothing to wait for."""
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({}, [])
    try:
        assert utils_ble.configured_adapter_present(PINNED, present={}) is True
    finally:
        _configure(original_pins, original_pool)


def test_the_pin_question_and_the_adapter_choice_are_one_decision():
    """
    Whether a battery may connect and which adapter it connects over must
    come from the same resolution: if they disagree, a strict pin either
    blocks a battery whose card is present or admits one whose card is not.
    """
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({PINNED: ["00:1A:7D:DA:71:13", "hci4"]}, [])
    utils_ble._unpinned_devices.discard(PINNED)
    try:
        for present in ({"hci3": "00:1A:7D:DA:71:13"}, {"hci4": "00:01:95:00:00:04"}, {"hci9": "00:01:95:00:00:09"}, {}):
            resolved = utils_ble.adapters_in_attempt_order(PINNED, present=present)
            satisfied = utils_ble.configured_adapter_present(PINNED, present=present)
            # a battery is satisfied exactly when the selection resolved a
            # configured entry rather than falling back
            assert satisfied == (resolved == utils_ble._resolve_all(["00:1A:7D:DA:71:13", "hci4"], present or {}))
    finally:
        _configure(original_pins, original_pool)
        utils_ble._unpinned_devices.discard(PINNED)


def _loop_battery(monkeypatch, present, iterations=3):
    """A Syncron_Ble with the threads left out, so async_main can be run for a few passes."""
    import asyncio

    battery = utils_ble.Syncron_Ble.__new__(utils_ble.Syncron_Ble)
    battery.address = PINNED
    battery._ble_thread_generation = 0
    battery.backend = _plain_backend()
    battery._reset_counters()

    remaining = [iterations]

    def is_alive():
        remaining[0] -= 1
        return remaining[0] > 0

    battery.main_thread = types.SimpleNamespace(is_alive=is_alive)

    attempts = []

    async def fake_connect(address):
        attempts.append(address)

    battery.connect_to_bms = fake_connect
    monkeypatch.setattr(utils_ble, "BLE_HOLD_POLL_INTERVAL", 0)
    monkeypatch.setattr(utils_ble, "BLE_RECONNECT_BACKOFF", [0, 0, 0])
    monkeypatch.setattr(utils_ble, "bluez_adapters", lambda: present)
    monkeypatch.setattr(utils_ble, "ble_hold_flag_path", lambda address: os.path.join(DRIVER_DIR, "no-such-hold-flag"))
    return battery, attempts, asyncio


def test_a_strict_pin_makes_no_attempt_while_its_adapter_is_absent(monkeypatch, caplog):
    """
    The point of strict is that the named adapter is protecting something, so
    connecting over a different one is worse than not connecting. A test that
    only checked the predicate would pass with the loop ignoring it entirely.
    """
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({PINNED: ["00:1A:7D:DA:71:13"]}, [])
    monkeypatch.setattr(utils_ble, "BLUETOOTH_ADAPTER_PIN_STRICT", True)
    battery, attempts, asyncio_mod = _loop_battery(monkeypatch, {"hci9": "00:01:95:00:00:09"})
    try:
        with caplog.at_level("WARNING", logger="SerialBattery"):
            asyncio_mod.run(battery.async_main(PINNED, 0))
        assert attempts == []
        # said once, not once per pass
        assert len([m for m in caplog.messages if "Waiting for one of them" in m]) == 1
    finally:
        _configure(original_pins, original_pool)


def test_a_strict_pin_connects_as_soon_as_its_adapter_is_there(monkeypatch):
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({PINNED: ["00:1A:7D:DA:71:13"]}, [])
    monkeypatch.setattr(utils_ble, "BLUETOOTH_ADAPTER_PIN_STRICT", True)
    battery, attempts, asyncio_mod = _loop_battery(monkeypatch, {"hci3": "00:1A:7D:DA:71:13"})
    try:
        asyncio_mod.run(battery.async_main(PINNED, 0))
        assert attempts == [PINNED, PINNED]
    finally:
        _configure(original_pins, original_pool)


def test_without_strict_an_absent_pin_still_attempts(monkeypatch):
    """The default is unchanged: warn, and connect over whatever is present."""
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({PINNED: ["00:1A:7D:DA:71:13"]}, [])
    monkeypatch.setattr(utils_ble, "BLUETOOTH_ADAPTER_PIN_STRICT", False)
    battery, attempts, asyncio_mod = _loop_battery(monkeypatch, {"hci9": "00:01:95:00:00:09"})
    try:
        asyncio_mod.run(battery.async_main(PINNED, 0))
        assert attempts == [PINNED, PINNED]
    finally:
        _configure(original_pins, original_pool)


# --------- one line per episode, not three per attempt ---------
#
# A characterised BMS radio mute lasts 10-20 s, happens a few times an hour
# per battery, and the fallback covers it. Narrating every attempt made those
# three lines the bulk of the log and taught readers to skip the word ERROR.


class _EpisodeBattery(utils_ble.Syncron_Ble):
    """A Syncron_Ble with the threads left out, so the accounting can be driven directly."""

    def __init__(self, backend):
        self.address = "C8:47:8C:00:00:00"
        self.backend = backend
        # no supervision wait to wake in a test, so signalling is a no-op
        self._disconnected = None
        self._disconnected_loop = None
        self._reset_counters()


def _scanning_backend(scans=0):
    return types.SimpleNamespace(scans_devices=True, scans=scans, current_adapter="hci5", landed_adapter_name="hci3")


def _plain_backend():
    return types.SimpleNamespace(scans_devices=False, current_adapter="hci5", landed_adapter_name="hci5")


def _adapters_named():
    return {"hci3": "00:01:95:C9:B4:C6", "hci5": "00:01:95:C9:B2:EA"}


def test_an_adapter_is_described_by_both_names_it_answers_to():
    assert utils_ble.describe_adapter("hci3", _adapters_named()) == "hci3 (00:01:95:C9:B4:C6)"


def test_an_adapter_whose_identity_cannot_be_read_says_so():
    """
    Silence here would mean pins are not being honoured and nothing said so;
    the string is the signal, not a cosmetic fallback.
    """
    assert utils_ble.describe_adapter("hci7", _adapters_named()) == "hci7 (MAC unresolved)"


def test_the_scans_token_is_absent_when_the_backend_cannot_scan():
    """Absent means "not applicable"; a printed 0 would mean "never needed to"."""
    assert "scans" not in _EpisodeBattery(_plain_backend())._counters()
    assert "0 scans" in _EpisodeBattery(_scanning_backend())._counters()


def test_the_counters_are_the_episode_s_not_the_process_s(monkeypatch):
    backend = _scanning_backend(scans=40)
    battery = _EpisodeBattery(backend)
    battery._attempts = 7
    battery._first_link_reported = True
    battery._note_drop()
    battery._begin_pending_episode()
    backend.scans = 43
    battery._attempts = 2
    assert battery._counters() == "2 attempts, 3 scans"


def test_a_recovered_link_reports_the_episode_once(monkeypatch, caplog):
    monkeypatch.setattr(utils_ble, "bluez_adapters", _adapters_named)
    backend = _scanning_backend(scans=5)
    battery = _EpisodeBattery(backend)
    battery._first_link_reported = True
    battery._first_link_reported = True
    battery._note_drop()
    battery._begin_pending_episode()
    battery._attempts = 3
    backend.scans = 8
    with caplog.at_level("INFO", logger="SerialBattery"):
        battery._report_link_up()
    line = "\n".join(caplog.messages)
    assert "BLE link recovered for C8:47:8C:00:00:00" in line
    assert "on adapter hci3 (00:01:95:C9:B4:C6)" in line
    # the link dropped from the adapter it was actually on, not the one requested
    assert "dropped from adapter hci3 (00:01:95:C9:B4:C6)" in line
    assert "3 attempts, 3 scans" in line
    # and the episode is closed, so nothing repeats it
    assert battery._episode_started is None


def test_the_first_link_of_a_life_is_reported_and_is_not_a_recovery(caplog, monkeypatch):
    monkeypatch.setattr(utils_ble, "bluez_adapters", _adapters_named)
    battery = _EpisodeBattery(_scanning_backend())
    with caplog.at_level("INFO", logger="SerialBattery"):
        battery._report_link_up()
    assert "connected to bluetooth device C8:47:8C:00:00:00" in caplog.messages[0]
    assert "recovered" not in caplog.messages[0]


def test_an_episode_that_ends_without_recovery_still_reports(caplog, monkeypatch):
    """
    The reconnect loop never gives up, so these two are the only non-recovery
    endings there are: a rebuild abandons the generation, or a hold stops it.
    """
    monkeypatch.setattr(utils_ble, "bluez_adapters", _adapters_named)
    battery = _EpisodeBattery(_scanning_backend())
    battery._first_link_reported = True
    battery._note_drop()
    battery._begin_pending_episode()
    battery._attempts = 12
    with caplog.at_level("INFO", logger="SerialBattery"):
        battery._end_episode("abandoned")
    assert "BLE link abandoned for C8:47:8C:00:00:00" in caplog.messages[0]
    assert "12 attempts" in caplog.messages[0]
    assert battery._episode_started is None


def test_a_short_outage_says_nothing_while_it_is_open(caplog, monkeypatch):
    """Every ordinary mute must pass in silence, or the directive achieved nothing."""
    monkeypatch.setattr(utils_ble, "bluez_adapters", _adapters_named)
    battery = _EpisodeBattery(_scanning_backend())
    battery._first_link_reported = True
    battery._note_drop()
    battery._begin_pending_episode()
    with caplog.at_level("INFO", logger="SerialBattery"):
        for _ in range(50):
            battery._report_episode_still_open()
    assert caplog.messages == []


def test_a_long_outage_reports_on_a_cadence(caplog, monkeypatch):
    monkeypatch.setattr(utils_ble, "bluez_adapters", _adapters_named)
    battery = _EpisodeBattery(_scanning_backend())
    battery._first_link_reported = True
    battery._note_drop()
    battery._begin_pending_episode()
    battery._attempts = 60
    battery._episode_report_due = time.time() - 1
    with caplog.at_level("INFO", logger="SerialBattery"):
        battery._report_episode_still_open()
        # immediately again: the cadence must have re-armed, not re-fired
        battery._report_episode_still_open()
    assert len(caplog.messages) == 1
    assert "still reconnecting to C8:47:8C:00:00:00" in caplog.messages[0]
    assert "60 attempts" in caplog.messages[0]
    assert "requested adapter hci5 (00:01:95:C9:B2:EA)" in caplog.messages[0]


def test_bleak_s_bluez_gone_warning_is_filtered_and_nothing_else_is():
    filt = utils_ble.silence_bluez_gone_warning()

    def record(msg):
        return logging.LogRecord("bleak.backends.bluezdbus.client", logging.WARNING, __file__, 1, msg, None, None)

    assert filt.filter(record("Failed to cancel connection (/org/bluez/hci3/dev_X): ServiceUnknown")) is False
    # a real teardown failure, and an unrelated warning, both survive
    assert filt.filter(record("Failed to cancel connection (/org/bluez/hci3/dev_X): TimedOut")) is True
    assert filt.filter(record("ServiceUnknown while connecting")) is True


def test_installing_the_filter_twice_does_not_stack_it():
    first = utils_ble.silence_bluez_gone_warning()
    assert utils_ble.silence_bluez_gone_warning() is first


# --------- log lines a watch depends on ---------
#
# These strings are matched by scripts outside this repo. A level demotion
# deletes a line from a watch running at INFO just as surely as a reword
# does, and it is invisible to every other test in this file - which is why
# it needs one of its own.

WATCHED_LINES = (
    # the disconnect event: episode boundaries are counted from it. Upstream's
    # spelling, deliberately unfixed - the watch matches this text.
    "bluetooh device with address",
    # the episode summary that replaced the per-attempt narration
    "BLE link recovered for",
    # the still-down report during a long outage
    "still reconnecting to",
    # the once-per-life line that says the link came up at all
    "connected to bluetooth device",
    # the once-per-generation line naming the backend, which is what makes an
    # absent scan count readable
    "BLE thread for",
)


def _utils_ble_source():
    with open(os.path.join(DRIVER_DIR, "utils_ble.py"), encoding="utf-8") as f:
        return f.read()


def _emitting_methods(source, watched):
    """The logger method enclosing every occurrence of a watched string.

    Scans back from the string to the logger call that contains it, rather
    than looking for both on one line: the formatter wraps a long call across
    lines, and a line-by-line scan would find no logger call at all and pass
    by finding nothing.
    """
    methods = []
    start = 0
    while True:
        found = source.find(watched, start)
        if found == -1:
            return methods
        start = found + 1
        call = source.rfind("logger.", 0, found)
        if call != -1:
            methods.append(source[call:].split("(", 1)[0])


def test_watched_lines_are_emitted_at_info_or_above():
    source = _utils_ble_source()
    for watched in WATCHED_LINES:
        methods = _emitting_methods(source, watched)
        assert methods, f"watched string {watched!r} is no longer logged anywhere"
        for method in methods:
            assert method != "logger.debug", (
                f"{watched!r} is logged at DEBUG, which deletes it from a watch running at INFO. " "Re-key the watch before demoting it."
            )


def test_no_watched_line_spans_more_than_one_record():
    """
    The consumer treats one line as one event, so an embedded newline splits
    a single event into two and corrupts every count derived from it.
    """
    source = _utils_ble_source()
    for watched in WATCHED_LINES:
        for match in re.finditer(re.escape(watched), source):
            statement = source[source.rfind("logger.", 0, match.start()) : match.end()]
            assert "\\n" not in statement, f"watched log line {watched!r} contains an embedded newline"


# --------- adapter pinning by MAC ---------
#
# hciN numbering is assigned in probe order: a reboot or USB reset can renumber
# the dongles, silently re-pointing every pin at different hardware while the
# batteries still connect and nothing looks wrong. An adapter's MAC does not
# move, so configuration may name that instead and be resolved against live
# BlueZ state.

ADAPTERS = {"hci3": "00:1A:7D:DA:71:13", "hci4": "00:1A:7D:DA:71:14"}


def test_a_mac_entry_resolves_to_the_adapters_current_name():
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({"C8:47:8C:00:00:00": ["00:1A:7D:DA:71:14"]}, [])
    try:
        assert utils_ble.adapters_in_attempt_order("C8:47:8C:00:00:00", present=ADAPTERS) == ["hci4"]
    finally:
        _configure(original_pins, original_pool)


def test_a_mac_pin_follows_its_adapter_across_renumbering():
    """The whole point: the same config resolves to whatever number the
    dongle currently answers to."""
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({"C8:47:8C:00:00:00": ["00:1A:7D:DA:71:13"]}, [])
    try:
        before = utils_ble.adapters_in_attempt_order("C8:47:8C:00:00:00", present={"hci3": "00:1A:7D:DA:71:13"})
        after = utils_ble.adapters_in_attempt_order("C8:47:8C:00:00:00", present={"hci0": "00:1A:7D:DA:71:13"})
        assert before == ["hci3"]
        assert after == ["hci0"]
    finally:
        _configure(original_pins, original_pool)


def test_mac_matching_ignores_case():
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({"C8:47:8C:00:00:00": ["00:1a:7d:da:71:13"]}, [])
    try:
        assert utils_ble.adapters_in_attempt_order("C8:47:8C:00:00:00", present=ADAPTERS) == ["hci3"]
    finally:
        _configure(original_pins, original_pool)


def test_hci_and_mac_entries_mix_and_keep_their_order():
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({"C8:47:8C:00:00:00": ["00:1A:7D:DA:71:14", "hci3"]}, [])
    try:
        assert utils_ble.adapters_in_attempt_order("C8:47:8C:00:00:00", present=ADAPTERS) == ["hci4", "hci3"]
    finally:
        _configure(original_pins, original_pool)


def test_a_mac_whose_adapter_is_gone_is_dropped():
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({"C8:47:8C:00:00:00": ["00:1A:7D:DA:71:99", "hci3"]}, [])
    try:
        assert utils_ble.adapters_in_attempt_order("C8:47:8C:00:00:00", present=ADAPTERS) == ["hci3"]
    finally:
        _configure(original_pins, original_pool)


def test_unresolvable_macs_fall_back_to_the_adapters_that_are_present():
    """
    A MAC is not a name bleak can use, so an unresolvable MAC list cannot be
    passed through. It falls back to every adapter that IS present rather
    than to nothing: an empty list hands the battery to bleak's system
    default, which is one card chosen by BlueZ for reasons unrelated to this
    driver and may be one the device is never discovered on.
    """
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({"C8:47:8C:00:00:00": ["00:1A:7D:DA:71:99"]}, [])
    utils_ble._unpinned_devices.discard("C8:47:8C:00:00:00")
    try:
        chosen = utils_ble.adapters_in_attempt_order("C8:47:8C:00:00:00", present=ADAPTERS)
        assert chosen == ["hci3", "hci4"]
        # and never the MAC itself, which bleak cannot use
        assert not any(utils_ble.is_adapter_mac(name) for name in chosen)
    finally:
        _configure(original_pins, original_pool)
        utils_ble._unpinned_devices.discard("C8:47:8C:00:00:00")


def test_the_present_fallback_is_ordered_by_adapter_number():
    """hci9 before hci10: string order puts a ten-adapter box's cards backwards."""
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({"C8:47:8C:00:00:00": ["00:1A:7D:DA:71:99"]}, [])
    utils_ble._unpinned_devices.discard("C8:47:8C:00:00:00")
    try:
        present = {"hci10": "00:01:95:00:00:10", "hci9": "00:01:95:00:00:09", "hci2": "00:01:95:00:00:02"}
        assert utils_ble.adapters_in_attempt_order("C8:47:8C:00:00:00", present=present) == ["hci2", "hci9", "hci10"]
    finally:
        _configure(original_pins, original_pool)
        utils_ble._unpinned_devices.discard("C8:47:8C:00:00:00")


def test_the_pool_accepts_macs_too():
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({}, ["00:1A:7D:DA:71:14"])
    try:
        assert utils_ble.adapters_in_attempt_order("C8:47:8C:00:00:11", present=ADAPTERS) == ["hci4"]
    finally:
        _configure(original_pins, original_pool)


def test_is_adapter_mac_distinguishes_the_two_forms():
    assert utils_ble.is_adapter_mac("00:1A:7D:DA:71:13")
    assert utils_ble.is_adapter_mac(" 00:1a:7d:da:71:13 ")
    assert not utils_ble.is_adapter_mac("hci0")
    assert not utils_ble.is_adapter_mac("00:1A:7D:DA:71")
    assert not utils_ble.is_adapter_mac("")


# --------- writing adapter MACs back to the config ---------


def _write_config(tmp_path, body):
    p = tmp_path / "config.ini"
    p.write_text(body)
    return str(p)


def test_hci_names_are_rewritten_to_macs_with_a_comment(tmp_path):
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({"C8:47:8C:00:00:00": ["hci3"]}, [])
    cfg = _write_config(tmp_path, "[DEFAULT]\nBLUETOOTH_ADAPTERS = C8:47:8C:00:00:00@hci3\n")
    try:
        assert utils_ble.pin_adapters_by_mac(cfg, adapters=ADAPTERS) is True
        text = open(cfg).read()
        assert "C8:47:8C:00:00:00@00:1A:7D:DA:71:13" in text
        assert "hci3 was detected as 00:1A:7D:DA:71:13" in text
        # the comment must be a comment, above the line it explains
        lines = text.splitlines()
        note = next(i for i, ln in enumerate(lines) if "was detected as" in ln)
        assert lines[note].lstrip().startswith(";")
        assert lines[note + 1].startswith("BLUETOOTH_ADAPTERS")
    finally:
        _configure(original_pins, original_pool)


def test_rewriting_leaves_every_other_line_alone(tmp_path):
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({}, ["hci3"])
    body = "[DEFAULT]\n; a comment about hci3 that must not change\nMAX_BATTERY_CHARGE_CURRENT = 50.0\nBLUETOOTH_ADAPTERS = hci3\n"
    cfg = _write_config(tmp_path, body)
    try:
        utils_ble.pin_adapters_by_mac(cfg, adapters=ADAPTERS)
        text = open(cfg).read()
        assert "; a comment about hci3 that must not change" in text
        assert "MAX_BATTERY_CHARGE_CURRENT = 50.0" in text
    finally:
        _configure(original_pins, original_pool)


def test_hci1_is_not_matched_inside_hci10(tmp_path):
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({}, ["hci1"])
    cfg = _write_config(tmp_path, "[DEFAULT]\nBLUETOOTH_ADAPTERS = hci10, hci1\n")
    try:
        utils_ble.pin_adapters_by_mac(cfg, adapters={"hci1": "00:1A:7D:DA:71:13", "hci10": "00:1A:7D:DA:71:99"})
        text = open(cfg).read()
        assert "hci10, 00:1A:7D:DA:71:13" in text
    finally:
        _configure(original_pins, original_pool)


def test_a_dead_controller_is_never_written_back(tmp_path):
    """All-zeros is the kernel's answer for a card it cannot talk to. Pinning
    a battery to that would be worse than leaving the name in place."""
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({}, ["hci9"])
    cfg = _write_config(tmp_path, "[DEFAULT]\nBLUETOOTH_ADAPTERS = hci9\n")
    try:
        assert utils_ble.pin_adapters_by_mac(cfg, adapters={"hci9": "00:00:00:00:00:00"}) is False
        assert "hci9" in open(cfg).read()
    finally:
        _configure(original_pins, original_pool)


def test_entries_already_written_as_macs_are_left_alone(tmp_path):
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({}, ["00:1A:7D:DA:71:13"])
    cfg = _write_config(tmp_path, "[DEFAULT]\nBLUETOOTH_ADAPTERS = 00:1A:7D:DA:71:13\n")
    try:
        assert utils_ble.pin_adapters_by_mac(cfg, adapters=ADAPTERS) is False
        assert "was detected as" not in open(cfg).read()
    finally:
        _configure(original_pins, original_pool)


def test_a_commented_out_line_is_not_rewritten(tmp_path):
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({}, ["hci3"])
    cfg = _write_config(tmp_path, "[DEFAULT]\n; BLUETOOTH_ADAPTERS = hci3\nBLUETOOTH_ADAPTERS = hci3\n")
    try:
        utils_ble.pin_adapters_by_mac(cfg, adapters=ADAPTERS)
        lines = open(cfg).read().splitlines()
        assert "; BLUETOOTH_ADAPTERS = hci3" in lines
    finally:
        _configure(original_pins, original_pool)


def test_an_unwritable_config_is_not_worth_failing_over(tmp_path):
    original_pins, original_pool = utils_ble.BLUETOOTH_ADAPTER_PINS, utils_ble.BLUETOOTH_ADAPTER_POOL
    _configure({}, ["hci3"])
    try:
        assert utils_ble.pin_adapters_by_mac(str(tmp_path / "nope.ini"), adapters=ADAPTERS) is False
    finally:
        _configure(original_pins, original_pool)


# --------- supervision waits instead of polling ---------
#
# The link used to be watched with `while is_connected: await sleep(0.1)`,
# which cost ten timer wakeups a second per battery for the whole life of
# every connection. On a GX device already short of headroom that is pure
# run-queue churn: no work is done per iteration.


class _FakeClient:
    def __init__(self, connected=True):
        self.is_connected = connected


def _supervisor(connected=True, main_alive=True):
    """A Syncron_Ble-shaped object with only what supervise_connection uses."""
    import types

    s = types.SimpleNamespace()
    s.client = _FakeClient(connected)
    s.main_thread = types.SimpleNamespace(is_alive=lambda: main_alive)
    s._disconnected = None
    s._disconnected_loop = None
    s.supervise_connection = utils_ble.Syncron_Ble.supervise_connection.__get__(s)
    s.signal_disconnected = utils_ble.Syncron_Ble.signal_disconnected.__get__(s)
    return s


def test_supervision_returns_as_soon_as_the_link_drops():
    """The whole point: the event wakes it, not the timeout."""
    import asyncio as aio

    async def run():
        s = _supervisor()
        s._disconnected = aio.Event()
        s._disconnected_loop = aio.get_running_loop()
        loop = aio.get_running_loop()
        started = loop.time()
        loop.call_later(0.05, s.signal_disconnected)
        await aio.wait_for(s.supervise_connection(), timeout=2.0)
        # returned on the event, far inside the recheck interval
        assert loop.time() - started < utils_ble.BLE_SUPERVISION_RECHECK

    aio.run(run())


def test_supervision_still_notices_a_disconnect_whose_callback_never_fired():
    """Missed callbacks are a real failure mode, so is_connected stays a
    backstop - it is just consulted on the recheck, not at 10 Hz."""
    import asyncio as aio

    async def run():
        s = _supervisor(connected=False)
        s._disconnected = aio.Event()
        s._disconnected_loop = aio.get_running_loop()
        await aio.wait_for(s.supervise_connection(), timeout=2.0)

    original = utils_ble.BLE_SUPERVISION_RECHECK
    utils_ble.BLE_SUPERVISION_RECHECK = 0.02
    try:
        aio.run(run())
    finally:
        utils_ble.BLE_SUPERVISION_RECHECK = original


def test_supervision_returns_when_the_main_thread_is_gone():
    import asyncio as aio

    async def run():
        s = _supervisor(main_alive=False)
        s._disconnected = aio.Event()
        s._disconnected_loop = aio.get_running_loop()
        await aio.wait_for(s.supervise_connection(), timeout=2.0)

    original = utils_ble.BLE_SUPERVISION_RECHECK
    utils_ble.BLE_SUPERVISION_RECHECK = 0.02
    try:
        aio.run(run())
    finally:
        utils_ble.BLE_SUPERVISION_RECHECK = original


def test_signalling_without_a_connection_is_harmless():
    s = _supervisor()
    s.signal_disconnected()  # no event yet - must not raise


# ---------------------------------------------------------------------------
# The abandoned-generation reaper.
#
# rebuild_ble_thread() abandons an event loop whose BlueZ manager bus stays
# pinned in bleak's module-level dict with live match rules; dbus-daemon then
# queues every BlueZ signal to a socket nobody reads (measured at ~44 MB/h of
# daemon growth on a Cerbo GX). These tests assert the reaper's side effects
# — the dict entry removed, the socket actually closed, the sibling entry
# untouched — rather than exception types, per the recovery-helper standard:
# a reaper that does nothing raises nothing.
# ---------------------------------------------------------------------------


@pytest.fixture
def bluez_manager_stub():
    """Install bleak.backends.bluezdbus.manager as a stub carrying the dict.

    Guarded and restored: other test files stub bleak differently and
    collection order decides who wins (see the module docstring), so this
    fixture saves whatever is there and puts it back.
    """
    saved = {name: sys.modules.get(name) for name in ("bleak.backends", "bleak.backends.bluezdbus", "bleak.backends.bluezdbus.manager")}
    backends = sys.modules.get("bleak.backends") or types.ModuleType("bleak.backends")
    bluezdbus = sys.modules.get("bleak.backends.bluezdbus") or types.ModuleType("bleak.backends.bluezdbus")
    manager = types.ModuleType("bleak.backends.bluezdbus.manager")
    manager._global_instances = {}
    bluezdbus.manager = manager
    backends.bluezdbus = bluezdbus
    sys.modules["bleak"].backends = backends
    sys.modules["bleak.backends"] = backends
    sys.modules["bleak.backends.bluezdbus"] = bluezdbus
    sys.modules["bleak.backends.bluezdbus.manager"] = manager
    yield manager
    for name, mod in saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod


def _fake_manager_with_socket():
    import socket as socket_module

    left, right = socket_module.socketpair()
    manager = types.SimpleNamespace(_bus=types.SimpleNamespace(_sock=left))
    return manager, left, right


def test_a_reaped_generation_loses_its_manager_and_its_socket_is_closed(bluez_manager_stub):
    abandoned_loop = object()
    live_loop = object()
    abandoned_mgr, abandoned_sock, _peer_a = _fake_manager_with_socket()
    live_mgr, live_sock, _peer_b = _fake_manager_with_socket()
    bluez_manager_stub._global_instances[abandoned_loop] = abandoned_mgr
    bluez_manager_stub._global_instances[live_loop] = live_mgr

    utils_ble._reap_abandoned_ble_generation(None, abandoned_loop, "AA:BB:CC:DD:EE:FF", 0)

    # the abandoned entry is gone and ONLY that entry: a reaper degenerated
    # into dict.clear() fails on the count and on the sibling
    assert abandoned_loop not in bluez_manager_stub._global_instances
    assert len(bluez_manager_stub._global_instances) == 1
    assert bluez_manager_stub._global_instances[live_loop] is live_mgr
    # the socket is actually closed, not merely dereferenced — fileno() is -1
    # after close(); a reaper that only pops the dict fails here
    assert abandoned_sock.fileno() == -1
    assert live_sock.fileno() != -1
    live_sock.close()
    _peer_a.close()
    _peer_b.close()


def test_the_reaper_tolerates_an_already_reaped_generation(bluez_manager_stub):
    live_loop = object()
    live_mgr, live_sock, _peer = _fake_manager_with_socket()
    bluez_manager_stub._global_instances[live_loop] = live_mgr

    # bleak's own closed-loop sweep may win the race; reaping a loop with no
    # entry must be a no-op, not an error, and must not touch the survivor
    utils_ble._reap_abandoned_ble_generation(None, object(), "AA:BB:CC:DD:EE:FF", 1)

    assert bluez_manager_stub._global_instances == {live_loop: live_mgr}
    assert live_sock.fileno() != -1
    live_sock.close()
    _peer.close()


def test_the_reaper_waits_for_the_old_thread_before_touching_its_state(bluez_manager_stub):
    joins = []
    old_thread = types.SimpleNamespace(join=lambda timeout: joins.append(timeout))
    abandoned_loop = object()
    mgr, sock, _peer = _fake_manager_with_socket()
    bluez_manager_stub._global_instances[abandoned_loop] = mgr

    utils_ble._reap_abandoned_ble_generation(old_thread, abandoned_loop, "AA:BB:CC:DD:EE:FF", 0)

    # joined exactly once, with the bounded timeout — an unbounded join would
    # hang the reaper forever on a truly wedged generation
    assert joins == [utils_ble.BLE_GENERATION_REAP_TIMEOUT]
    assert sock.fileno() == -1
    _peer.close()


def test_a_rebuild_hands_the_reaper_the_abandoned_generation_not_the_new_one(monkeypatch):
    reaped = []
    monkeypatch.setattr(utils_ble, "_reap_abandoned_ble_generation", lambda *args: reaped.append(args))

    sb = object.__new__(utils_ble.Syncron_Ble)
    sb.address = "AA:BB:CC:DD:EE:FF"
    sb._ble_thread_generation = 0
    old_thread = object()
    old_loop = object()
    sb._ble_async_thread = old_thread
    sb.ble_async_thread_event_loop = old_loop

    def fake_thread_main(generation=0):
        sb.ble_async_thread_ready.set()

    sb.initiate_ble_thread_main = fake_thread_main

    assert sb.rebuild_ble_thread() is True

    # the reaper got the OLD generation's thread and loop, captured before
    # the rebuild overwrote them — capturing after the reset hands it False
    # and reaps nothing, which is exactly the defect this wiring fixes
    assert reaped == [(old_thread, old_loop, "AA:BB:CC:DD:EE:FF", 0)]
    # and the NEW thread handle was stored for the next generation's reaper
    assert sb._ble_async_thread is not old_thread
    assert sb._ble_async_thread.name == "BMS_bluetooth_async_thread_gen1"
