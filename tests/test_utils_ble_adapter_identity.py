# -*- coding: utf-8 -*-
"""Adapter identity is read from the kernel, never over D-Bus.

bluez_adapters() runs on the BLE thread - resolve_adapter ->
adapters_in_attempt_order -> _select_adapter is the connect path - and asking
BlueZ from there crashed the driver. dbus-python's DBusGMainLoop supports only
the DEFAULT GLib main context, so a connection opened on that thread still
registered its watches and dispatch source on the MAIN thread's loop, and
closing it here freed the connection while that loop was still using it. Two
core dumps showed the main thread dying inside dbus_connection_dispatch, once
on a freed hash table and once on a freed mutex; the same process also aborted
inside malloc. One use-after-free, three presentations.

The module-loading scaffolding is shared with test_utils_ble so both files
exercise the same instance.
"""

from test_utils_ble import utils_ble

# The real shape of `hciconfig` output on the production GX device, including
# the onboard UART radio that reports the all-zeros address.
HCICONFIG_SAMPLE = """hci6:\tType: Primary  Bus: USB
\tBD Address: 00:1A:7D:DA:71:05  ACL MTU: 310:10  SCO MTU: 64:8
\tUP RUNNING
hci2:\tType: Primary  Bus: UART
\tBD Address: 00:00:00:00:00:00  ACL MTU: 0:0  SCO MTU: 0:0
\tDOWN
hci3:\tType: Primary  Bus: USB
\tBD Address: 00:01:95:CC:2C:53  ACL MTU: 310:10  SCO MTU: 64:8
\tUP RUNNING
"""


class _Result:
    stdout = HCICONFIG_SAMPLE


def _clear_cache():
    utils_ble._adapter_identity_cache["at"] = 0.0
    utils_ble._adapter_identity_cache["adapters"] = {}


def test_no_dbus_is_imported_at_all():
    """The point of the change: this module must not touch dbus-python."""
    import ast
    import os

    src = os.path.join(os.path.dirname(__file__), "..", "dbus-serialbattery", "utils_ble.py")
    tree = ast.parse(open(src).read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "dbus" not in imported, "utils_ble runs on the BLE thread and must not import dbus-python"


def test_hciconfig_table_is_parsed_and_dead_controllers_dropped(monkeypatch):
    _clear_cache()
    monkeypatch.setattr(utils_ble, "_adapters_from_sysfs", lambda: {})
    calls = []

    def _run(cmd, **kwargs):
        calls.append(cmd)
        return _Result()

    monkeypatch.setattr(utils_ble.subprocess, "run", _run)
    adapters = utils_ble.bluez_adapters()

    assert adapters == {"hci6": "00:1A:7D:DA:71:05", "hci3": "00:01:95:CC:2C:53"}
    # all-zeros is what a dead or unserved controller reports; it identifies
    # nothing and must never become a pin target
    assert "hci2" not in adapters
    # one bare call returns the whole table - not one spawn per adapter, which
    # matters on the production box with seven of them
    assert calls == [["hciconfig"]]
    _clear_cache()


def test_sysfs_is_preferred_and_hciconfig_is_not_spawned(monkeypatch):
    _clear_cache()
    monkeypatch.setattr(utils_ble, "_adapters_from_sysfs", lambda: {"hci0": "00:01:95:40:C3:33"})

    def _boom(*args, **kwargs):
        raise AssertionError("hciconfig must not run when sysfs already answered")

    monkeypatch.setattr(utils_ble.subprocess, "run", _boom)
    assert utils_ble.bluez_adapters() == {"hci0": "00:01:95:40:C3:33"}
    _clear_cache()


def test_identity_is_cached_so_a_reconnect_loop_does_not_spawn_per_attempt(monkeypatch):
    _clear_cache()
    monkeypatch.setattr(utils_ble, "_adapters_from_sysfs", lambda: {})
    calls = []

    def _run(cmd, **kwargs):
        calls.append(cmd)
        return _Result()

    monkeypatch.setattr(utils_ble.subprocess, "run", _run)
    for _ in range(5):
        utils_ble.bluez_adapters()
    assert len(calls) == 1, f"expected one subprocess for five lookups, got {len(calls)}"
    _clear_cache()


def test_no_answer_is_not_cached_as_an_answer(monkeypatch):
    """An empty read must not poison the cache: a card that appears later has
    to be seen, so only a real answer is remembered."""
    _clear_cache()
    monkeypatch.setattr(utils_ble, "_adapters_from_sysfs", lambda: {})
    monkeypatch.setattr(utils_ble, "_adapters_from_hciconfig", lambda: {})
    assert utils_ble.bluez_adapters() == {}
    assert utils_ble._adapter_identity_cache["adapters"] == {}
    _clear_cache()


def test_a_mac_pin_still_resolves_through_the_kernel_path(monkeypatch):
    """End to end: the reason the lookup exists at all is that a MAC-pinned
    battery must reach its adapter under whatever number it currently holds."""
    _clear_cache()
    monkeypatch.setattr(utils_ble, "_adapters_from_sysfs", lambda: {})
    monkeypatch.setattr(utils_ble.subprocess, "run", lambda cmd, **kw: _Result())

    original_pins = utils_ble.BLUETOOTH_ADAPTER_PINS
    original_pool = utils_ble.BLUETOOTH_ADAPTER_POOL
    utils_ble.BLUETOOTH_ADAPTER_PINS = {"C8:47:8C:00:00:00": ["00:01:95:CC:2C:53"]}
    utils_ble.BLUETOOTH_ADAPTER_POOL = []
    try:
        assert utils_ble.adapters_in_attempt_order("C8:47:8C:00:00:00") == ["hci3"]
    finally:
        utils_ble.BLUETOOTH_ADAPTER_PINS = original_pins
        utils_ble.BLUETOOTH_ADAPTER_POOL = original_pool
        _clear_cache()
