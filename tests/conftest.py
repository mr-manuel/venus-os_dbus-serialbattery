"""Shared test fixtures and module stubs for platforms without D-Bus.

dbushelper.py (and its transitive imports) depend on Linux-only C extensions
(``dbus``, ``gi``) and Victron's ``velib_python`` helpers that are only
available on Venus OS.  This conftest injects lightweight stubs *before*
any test module triggers the real import chain, so the test suite works on
macOS, Windows, and headless CI runners.
"""

import sys
import types
from unittest.mock import MagicMock


def _stub(name, **attrs):
    """Register a stub module if the real one isn't installed."""
    if name not in sys.modules:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    return sys.modules[name]


_BusConnection = type("BusConnection", (), {
    "TYPE_SYSTEM": 0,
    "TYPE_SESSION": 1,
    "__new__": lambda cls, *a, **kw: object.__new__(cls),
})

_dbus_bus = _stub("dbus.bus", BusConnection=_BusConnection)
_dbus_svc = _stub("dbus.service")
_dbus = _stub("dbus", bus=_dbus_bus, service=_dbus_svc)
_stub("dbus.mainloop")
_stub("dbus.mainloop.glib")

_gi_repo = _stub("gi.repository", GLib=MagicMock())
_stub("gi", repository=_gi_repo)

_stub("vedbus", VeDbusService=MagicMock)
_stub("ve_utils", get_vrm_portal_id=lambda: "stub")
_stub("settingsdevice", SettingsDevice=MagicMock)
