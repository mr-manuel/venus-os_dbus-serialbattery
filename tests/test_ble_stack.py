# -*- coding: utf-8 -*-
"""ble_stack.ensure_ble_stack(): source the shared install from its folder, else vendor ext/ble/.

Three directions, all load-bearing. SHARED: the folder's four import roots go
at sys.path[1:] - ahead of site-packages and PYTHONPATH (a vendored copy ahead
of them would silently shadow the shared stack, which is the whole trap the
box-install change exists to close), behind the script's own directory so no
vendored name can shadow a driver module (the position dbus-serialbattery.py
has always given ext/) - and the connection manager is imported from there
BEFORE bleak.
VENDORED: with no shared install - every upstream deployment - ext/ble/ is the
only BLE stack there is, and it must be inserted whether or not the connection
manager option is on, because importability is not a feature flag (a first
draft gated it behind BLUETOOTH_CONNECTION_MANAGER and would have broken the
shipped default). BROKEN: a shared folder that is present but cannot be
imported must leave nothing of itself behind and must be reported as a fault,
not as "absent".
"""

import importlib
import os
import re
import sys
import types

DRIVER_DIR = os.path.join(os.path.dirname(__file__), "..", "dbus-serialbattery")
sys.path.insert(0, DRIVER_DIR)

import ble_stack  # noqa: E402


def _fresh(monkeypatch):
    monkeypatch.delitem(sys.modules, "bleak_connection_manager", raising=False)
    sys.path[:] = [p for p in sys.path if not p.endswith(os.path.join("ext", "ble"))]
    return importlib.reload(ble_stack)


def _fake_shared_install(tmp_path, body):
    pkg = tmp_path / "src" / "bleak_connection_manager"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(body)
    for sub in ("ext", os.path.join("ext", "upstream", "bleak"), os.path.join("ext", "upstream", "bleak-retry-connector", "src")):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    return str(tmp_path)


def test_an_already_imported_connection_manager_is_left_alone(monkeypatch):
    mod = _fresh(monkeypatch)
    monkeypatch.setitem(sys.modules, "bleak_connection_manager", types.ModuleType("bleak_connection_manager"))
    assert mod.ensure_ble_stack("/nonexistent") == "provided"
    assert mod.EXT_BLE not in sys.path


def test_without_a_shared_install_ext_ble_is_inserted_first(monkeypatch):
    mod = _fresh(monkeypatch)
    assert mod.ensure_ble_stack("/nonexistent") == "vendored"
    assert sys.path[1] == mod.EXT_BLE
    assert sys.path[0] != mod.EXT_BLE, "the script's own directory stays first"
    assert mod.shared_failure is None
    sys.path.remove(mod.EXT_BLE)


def test_an_empty_dir_setting_never_looks_for_a_shared_install(monkeypatch, tmp_path):
    mod = _fresh(monkeypatch)
    _fake_shared_install(tmp_path, "")
    assert mod.ensure_ble_stack("") == "vendored"
    assert not any(p.startswith(str(tmp_path)) for p in sys.path)
    sys.path.remove(mod.EXT_BLE)


def test_a_shared_install_is_imported_from_its_folder_ahead_of_everything(monkeypatch, tmp_path):
    mod = _fresh(monkeypatch)
    root = _fake_shared_install(tmp_path, "MARK = 'shared'\n")
    assert mod.ensure_ble_stack(root) == "shared"
    assert sys.modules["bleak_connection_manager"].MARK == "shared"
    assert sys.path[1:5] == mod.shared_lib_paths(root), "the four roots, in priority order, behind only the script dir"
    assert sys.path[0] not in mod.shared_lib_paths(root)
    assert mod.EXT_BLE not in sys.path, "vendored copies must not be inserted beside a shared stack"
    for p in mod.shared_lib_paths(root):
        sys.path.remove(p)


def test_a_broken_shared_install_is_withdrawn_and_reported_as_a_fault(monkeypatch, tmp_path):
    mod = _fresh(monkeypatch)
    root = _fake_shared_install(tmp_path, "raise RuntimeError('half-installed')\n")
    assert mod.ensure_ble_stack(root) == "vendored"
    assert "half-installed" in mod.shared_failure
    assert not any(p.startswith(root) for p in sys.path), "no path of the broken install may linger"
    assert "bleak_connection_manager" not in sys.modules, "no module of the broken install may linger"
    assert sys.path[1] == mod.EXT_BLE
    assert sys.path[0] != mod.EXT_BLE, "the script's own directory stays first"
    sys.path.remove(mod.EXT_BLE)


def test_a_consumer_without_a_vendored_copy_inserts_nothing(monkeypatch):
    """The module is lifted as-is by consumers that vendor no bleak: absent shared
    install must then leave sys.path alone and let the interpreter's own bleak serve."""
    mod = _fresh(monkeypatch)
    before = list(sys.path)
    assert mod.ensure_ble_stack("/nonexistent", vendored_dir=None) == "vendored"
    assert sys.path == before


def test_the_module_imports_nothing_from_this_driver():
    with open(os.path.join(DRIVER_DIR, "ble_stack.py")) as f:
        imports = [ln.strip() for ln in f if ln.startswith(("import ", "from "))]
    assert imports == ["import os", "import sys"], imports


def test_shared_layout_mirrors_the_connection_managers_installer():
    """The four roots are the connection manager's own layout (bcm_autowire._lib_paths()).
    Pinned so a drift in either project fails here, not as a silent fallback to ext/ble/."""
    paths = ble_stack.shared_lib_paths("/data/bcm")
    assert paths == [
        "/data/bcm/src",
        "/data/bcm/ext",
        "/data/bcm/ext/upstream/bleak",
        "/data/bcm/ext/upstream/bleak-retry-connector/src",
    ]


def test_ext_ble_holds_the_vendored_stack_and_no_connection_manager():
    present = set(os.listdir(os.path.join(DRIVER_DIR, "ext", "ble")))
    assert {"bleak", "bleak_retry_connector", "bluetooth_adapters", "aiooui"} <= present
    assert "bleak_connection_manager" not in present
    assert not os.path.isdir(os.path.join(DRIVER_DIR, "ext", "bleak_connection_manager")), "no vendored connection manager: absent means plain bleak"


def test_the_vendoring_script_cannot_repopulate_flat_ext_with_the_ble_stack():
    """ext/update.py re-vendors each package to ext/<name>; without a subdir the BLE
    four would land back in flat ext/, ahead of the shared install again, on its
    next run. Parsed, not executed: the script fetches from GitHub at import time
    of __main__ only, but nothing here should ever depend on that."""
    import ast

    with open(os.path.join(DRIVER_DIR, "ext", "update.py")) as f:
        src = f.read()
    tree = ast.parse(src)
    modules = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign) and node.targets[0].id == "modules")
    ble = {m["name"]: m.get("subdir") for m in modules if m["name"] in ("bleak", "bleak_retry_connector", "bluetooth_adapters", "aiooui")}
    assert ble == {"bleak": "ble", "bleak_retry_connector": "ble", "bluetooth_adapters": "ble", "aiooui": "ble"}
    assert all(m.get("subdir") in (None, "") for m in modules if m["name"] not in ble), "only the BLE stack moves"
    assert 'f"{root_dir}/{subdir}/{name}" if subdir else' in src


# --- the ordering control (lifted from feat/bcm-v2-backend 425d813) ---------
#
# The catcher rebinds bleak.BleakClient process-wide, and a module that has
# already run `from bleak import BleakClient` keeps its original binding. So
# ensure_ble_stack and the install have to happen ABOVE every BLE import in
# dbus-serialbattery.py, at BOTH sys.argv[2] sites. Getting this backwards is
# silent: imports still succeed, this suite still passes, and the catcher
# simply never binds. Hence source-order assertions.

DRIVER_MAIN = os.path.join(DRIVER_DIR, "dbus-serialbattery.py")
BLE_IMPORT = r"^\s*from (utils_ble|bms\.[a-z0-9_]*_ble|bms\.generic_aiobmsble) import"


def _line_numbers(pattern):
    with open(DRIVER_MAIN, encoding="utf-8") as handle:
        return [i for i, line in enumerate(handle, 1) if re.search(pattern, line)]


def test_the_ble_stack_is_arranged_before_any_ble_import():
    arranged = _line_numbers(r"\bensure_ble_stack\(")
    ble_imports = _line_numbers(BLE_IMPORT)
    assert arranged, "ensure_ble_stack is never called"
    assert ble_imports, "no BLE imports found - has the file been restructured?"
    assert min(arranged) < min(ble_imports), f"ensure_ble_stack first called at line {min(arranged)}, but a BLE module is imported at line {min(ble_imports)}"


def test_the_connection_manager_is_installed_before_any_ble_import():
    installed = _line_numbers(r"^\s*install_ble_connection_manager\(")
    ble_imports = _line_numbers(BLE_IMPORT)
    assert installed, "install_ble_connection_manager is never called"
    assert min(installed) < min(ble_imports), f"catcher installed at line {min(installed)}, but a BLE module is imported at line {min(ble_imports)}"


def test_every_ble_import_site_is_preceded_by_its_own_arrange_and_install():
    """Both sys.argv[2] branches must arrange and install, not just the first."""
    arranged = _line_numbers(r"\bensure_ble_stack\(")
    installed = _line_numbers(r"^\s*install_ble_connection_manager\(")
    assert len(arranged) == len(installed) == 2, (arranged, installed)
    for line in _line_numbers(BLE_IMPORT):
        assert any(i < line for i in installed), f"BLE import at line {line} has no install above it"
        assert any(i < line for i in arranged), f"BLE import at line {line} has no ensure_ble_stack above it"
