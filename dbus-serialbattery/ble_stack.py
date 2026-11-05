# -*- coding: utf-8 -*-
"""Make the BLE stack importable: a shared install when the box has one, else ext/ble/.

The shared bleak-connection-manager install lives in one folder on the box
(BLUETOOTH_CONNECTION_MANAGER_DIR, /data/bcm by default) and carries ITS OWN
bleak and bleak-retry-connector; a consumer must use those, never shadow them
with vendored copies. With no shared install - every upstream deployment - the
vendored copies under ext/ble/ are the only BLE stack there is, and there is
deliberately no vendored connection manager: absent means plain bleak.

Nothing here depends on how the process was launched: no interpreter shim, no
PYTHONPATH, no environment contract. The folder is looked up, its layout is
the one the connection manager's own installer writes (mirrors
bcm_autowire._lib_paths() in that project), and the connection manager is
imported BEFORE bleak so that its sitewide autowire hook, if planted, stands
down for this process instead of installing a generic catcher with a
cmdline-derived owner and the box-wide config.

Called UNCONDITIONALLY before any module captures bleak.BleakClient at import
time (aiobmsble does so at module scope), and independently of whether the
connection manager is enabled - importability is not a feature flag.

This module is the reference implementation of the consumer contract for
every service on the box that uses the shared install (see the connection
manager's CONSUMERS.md). It imports nothing from this driver: lift
it as-is and pass your own vendored fallback directory, or none.
"""

import os
import sys

DEFAULT_SHARED_DIR = "/data/bcm"
EXT_BLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ext", "ble")

# repr of the exception when a shared install was present but could not be
# imported; None otherwise. Read by utils_ble_manager to tell "no shared
# install" (normal, a warning) from "shared install present but unusable"
# (a fault, an error), which are different operator actions.
shared_failure = None


def shared_lib_paths(root):
    """The shared install's import roots, in import-priority order."""
    return [
        os.path.join(root, "src"),
        os.path.join(root, "ext"),
        os.path.join(root, "ext", "upstream", "bleak"),
        os.path.join(root, "ext", "upstream", "bleak-retry-connector", "src"),
    ]


def shared_install_present(root):
    return bool(root) and os.path.isdir(os.path.join(root, "src", "bleak_connection_manager"))


def _purge_modules_under(root):
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None) or ""
        if f.startswith(root + os.sep):
            del sys.modules[name]


def ensure_ble_stack(shared_dir=DEFAULT_SHARED_DIR, vendored_dir=EXT_BLE):
    """Return "provided", "shared" or "vendored".

    provided: a connection manager is already imported (a launcher put it on
              the path, or a test stubbed it) - nothing is inserted.
    shared:   shared_dir holds an install; its roots were put at sys.path[1:]
              - ahead of every site-packages and PYTHONPATH entry, behind only
              the script's own directory, the position this driver has always
              given its vendored packages - and the connection manager was
              imported from there.
    vendored: vendored_dir (this driver's ext/ble/) was inserted when it
              exists; no connection manager is importable. If a shared install
              was present but broken, shared_failure says why and every path
              and module it contributed has been withdrawn. A consumer with no
              vendored copy passes vendored_dir=None and gets "vendored" with
              nothing inserted: whatever bleak the interpreter has is used.
    """
    global shared_failure
    shared_failure = None
    if "bleak_connection_manager" in sys.modules:
        return "provided"
    if shared_install_present(shared_dir):
        inserted = []
        for p in reversed(shared_lib_paths(shared_dir)):
            if p not in sys.path:
                sys.path.insert(1, p)
                inserted.append(p)
        try:
            import bleak_connection_manager  # noqa: F401  (before bleak: see module docstring)

            return "shared"
        except Exception as e:  # a broken shared install must not take the driver down
            shared_failure = repr(e)
            for p in inserted:
                sys.path.remove(p)
            _purge_modules_under(os.path.abspath(shared_dir))
    if vendored_dir and os.path.isdir(vendored_dir) and vendored_dir not in sys.path:
        sys.path.insert(1, vendored_dir)
    return "vendored"
