# -*- coding: utf-8 -*-
"""Every way into this driver can still import bleak, and a broken shared install leaves nothing behind.

Kept apart from test_ble_stack.py on purpose: that file is identical to the
deploy overlay's, and these two checks were added afterwards by an internal
review of the PR that moved the BLE stack into ext/ble.

The move emptied the flat ext/ of bleak. dbus-serialbattery.py arranges its
path through ble_stack.ensure_ble_stack(), which test_ble_stack.py already
pins by source order. The scripts below run on their own, set up their own
sys.path, and were missed: each one imported bleak from the flat ext/ and
failed with ModuleNotFoundError after the move, while every other test
passed. Nothing else imports them, so only a test aimed at them can see it.
"""

import ast
import importlib
import os
import subprocess
import sys

import pytest

DRIVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dbus-serialbattery"))
if DRIVER_DIR not in sys.path:
    sys.path.insert(0, DRIVER_DIR)

import ble_stack  # noqa: E402

# Scripts that run on their own and reach bleak, directly or through a BLE driver.
ENTRY_POINTS = [
    "aiobmsble_scan_batteries.py",
    "standalone_serialbattery.py",
]


def _module_level_path_setup(script):
    """The sys.path.insert/append calls a script makes at module level, as source."""
    with open(script, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    calls = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Attribute) and func.attr in ("insert", "append") and ast.unparse(func.value) == "sys.path":
                calls.append(ast.unparse(node))
    return calls


@pytest.mark.skipif(sys.version_info < (3, 10), reason="the vendored bleak uses match statements and needs Python 3.10+")
@pytest.mark.parametrize("name", ENTRY_POINTS)
def test_an_entry_point_can_import_bleak_from_its_own_path_setup(name):
    script = os.path.join(DRIVER_DIR, name)
    calls = _module_level_path_setup(script)
    assert calls, f"{name} sets up no sys.path entries - has it been restructured?"

    # Run the script's own path setup and nothing else, in a clean interpreter,
    # so neither this process's sys.path nor a stubbed bleak can mask the result.
    code = f"import os, sys\n__file__ = {script!r}\n" + "\n".join(calls) + "\nimport bleak\nprint(bleak.__file__)\n"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=DRIVER_DIR)

    assert result.returncode == 0, f"{name}: its own sys.path setup cannot import bleak\n{result.stderr}"
    assert os.path.join(DRIVER_DIR, "ext", "ble") in result.stdout, result.stdout


def test_a_broken_install_leaves_none_of_its_submodules_behind(monkeypatch, tmp_path):
    """The case the module cleanup exists for.

    When a package's own __init__.py raises, Python removes that module by
    itself, so a fixture built that way cannot tell whether ble_stack cleaned
    up. What Python does NOT remove is a submodule that imported successfully
    before __init__.py failed - left in sys.modules, a later import could
    resolve half against the broken shared tree and half against ext/ble.
    """
    pkg = tmp_path / "src" / "bleak_connection_manager"
    pkg.mkdir(parents=True)
    (pkg / "helper.py").write_text("X = 1\n")
    (pkg / "__init__.py").write_text("from . import helper  # noqa: F401\nraise RuntimeError('boom')\n")
    for sub in ("ext", os.path.join("ext", "upstream", "bleak"), os.path.join("ext", "upstream", "bleak-retry-connector", "src")):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(sys, "path", list(sys.path))
    for name in [n for n in sys.modules if n.startswith("bleak_connection_manager")]:
        monkeypatch.delitem(sys.modules, name)
    mod = importlib.reload(ble_stack)

    assert mod.ensure_ble_stack(str(tmp_path), vendored_dir=None) == "vendored"
    assert "boom" in mod.shared_failure

    leftovers = sorted(n for n in sys.modules if n.startswith("bleak_connection_manager"))
    assert leftovers == [], f"a broken shared install left modules importable: {leftovers}"
    for root in mod.shared_lib_paths(str(tmp_path)):
        assert root not in sys.path
