# -*- coding: utf-8 -*-
"""Tests for the BLE connection manager wiring in utils_ble_manager.

The module under test deliberately imports neither bleak nor the vendored
bleak_connection_manager at module scope (the whole point is installing the
catcher before anything imports bleak), so these tests run without either:
the vendored package is replaced by a stub in sys.modules and the config
flags are patched on the utils module the wiring reads at call time.
"""

import os
import sys
import types

import pytest

DRIVER_DIR = os.path.join(os.path.dirname(__file__), "..", "dbus-serialbattery")
sys.path.insert(0, DRIVER_DIR)

import utils  # noqa: E402
import utils_ble_manager  # noqa: E402


class TestParseLinkCaps:
    def test_parses_entries(self):
        assert utils_ble_manager.parse_link_caps(["hci0:5", " hci1 : 7 "]) == {"hci0": 5, "hci1": 7}

    def test_empty_and_blank_entries_are_skipped(self):
        assert utils_ble_manager.parse_link_caps([]) == {}
        assert utils_ble_manager.parse_link_caps(["", "  "]) == {}

    def test_malformed_entries_are_skipped_not_guessed(self):
        # no colon, non-integer, non-positive, missing adapter: a wrong cap
        # silently gates connections, so none of these may survive
        assert utils_ble_manager.parse_link_caps(["hci0"]) == {}
        assert utils_ble_manager.parse_link_caps(["hci0:many"]) == {}
        assert utils_ble_manager.parse_link_caps(["hci0:0", "hci1:-3"]) == {}
        assert utils_ble_manager.parse_link_caps([":5"]) == {}

    def test_malformed_entry_does_not_poison_the_rest(self):
        assert utils_ble_manager.parse_link_caps(["hci0:zz", "hci1:4"]) == {"hci1": 4}

    def test_last_duplicate_wins(self):
        assert utils_ble_manager.parse_link_caps(["hci0:5", "hci0:3"]) == {"hci0": 3}

    def test_adapter_macs_survive_the_split(self):
        # a MAC is full of colons: the split has to be on the last one, or
        # the adapter comes out as "00:1A:7D:DA:71" with a cap of 13
        assert utils_ble_manager.parse_link_caps(["00:1A:7D:DA:71:13:5"]) == {"00:1A:7D:DA:71:13": 5}
        assert utils_ble_manager.parse_link_caps(["00:1A:7D:DA:71:13:5", "hci4:7"]) == {
            "00:1A:7D:DA:71:13": 5,
            "hci4": 7,
        }

    def test_a_mac_without_a_cap_is_still_rejected(self):
        assert utils_ble_manager.parse_link_caps(["00:1A:7D:DA:71:13:x"]) == {}


class TestInstallBleConnectionManager:
    @pytest.fixture
    def catcher_stub(self, monkeypatch):
        """A stand-in vendored package that records the install call."""
        calls = []

        def install_bleak_catcher(owner, **kwargs):
            calls.append((owner, kwargs))

        module = types.ModuleType("bleak_connection_manager")
        module.install_bleak_catcher = install_bleak_catcher
        monkeypatch.setitem(sys.modules, "bleak_connection_manager", module)

        # The install path now requires the stack decision to have been made
        # and to be "shared" - in the driver, ensure_ble_stack() always runs
        # first, above the option gate. Arrange that precondition here rather
        # than let the wiring install a catcher onto an unarranged sys.path.
        import ble_stack

        monkeypatch.setattr(ble_stack, "shared_failure", None, raising=False)
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER_DIR", "/data/bcm", raising=False)
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER_FORCE_START_NOTIFY", True, raising=False)

        validators = types.ModuleType("bleak_connection_manager.validators")

        def validate_gatt_services(client):
            raise NotImplementedError

        validators.validate_gatt_services = validate_gatt_services
        validators.tolerate_late_gatt = lambda v: ("late-gatt-wrapped", v)
        module.validators = validators
        monkeypatch.setitem(sys.modules, "bleak_connection_manager.validators", validators)
        return calls

    def test_disabled_by_default_installs_nothing(self, monkeypatch, catcher_stub):
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER", False)
        assert utils_ble_manager.install_ble_connection_manager("C8:47:8C:00:00:00") is False
        assert catcher_stub == []

    def test_installs_with_config_handed_over_verbatim(self, monkeypatch, catcher_stub):
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER", True)
        monkeypatch.setattr(utils, "BLUETOOTH_ADAPTERS", ["C8:47:8C:00:00:00@hci1", "hci2"])
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER_LINK_CAPS", ["hci1:5"])
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER_WRAP_SCANNER", True)

        assert utils_ble_manager.install_ble_connection_manager("C8:47:8C:00:00:00") is True

        assert len(catcher_stub) == 1
        owner, kwargs = catcher_stub[0]
        # the owner names this battery's claims: service plus MAC, no colons
        assert owner == "dbus-serialbattery.c8478c000000"
        # BLUETOOTH_ADAPTERS entries pass through verbatim - the library
        # parses the same MAC@hciX / hciX forms itself
        assert kwargs["adapters"] == ["C8:47:8C:00:00:00@hci1", "hci2"]
        assert kwargs["link_caps"] == {"hci1": 5}
        assert kwargs["wrap_scanner"] is True
        # validation is its own opt-in; not requested here
        assert kwargs["validate_connection"] is None

    def test_validation_opt_in_passes_wrapped_gatt_validator(self, monkeypatch, catcher_stub):
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER", True)
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER_VALIDATION", True)

        assert utils_ble_manager.install_ble_connection_manager("C8:47:8C:00:00:00") is True

        _, kwargs = catcher_stub[0]
        wrapped, inner = kwargs["validate_connection"]
        assert wrapped == "late-gatt-wrapped"
        assert inner.__name__ == "validate_gatt_services"

    def test_failed_install_is_swallowed(self, monkeypatch):
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER", True)

        def explode(owner, **kwargs):
            raise RuntimeError("no /run/bt-claims on this platform")

        module = types.ModuleType("bleak_connection_manager")
        module.install_bleak_catcher = explode
        monkeypatch.setitem(sys.modules, "bleak_connection_manager", module)

        # coordination is an optimization: the driver must still start
        assert utils_ble_manager.install_ble_connection_manager("C8:47:8C:00:00:00") is False

    def test_missing_vendored_package_is_swallowed(self, monkeypatch):
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER", True)
        monkeypatch.setitem(sys.modules, "bleak_connection_manager", None)
        assert utils_ble_manager.install_ble_connection_manager("C8:47:8C:00:00:00") is False


class TestCoordinationReport:
    """One line per process about which BLE stack the driver ended up on.

    The wording below is the FLEET CONTRACT (CONSUMERS.md) and is
    pinned verbatim: running monitor's log watches anchor on it, and the other
    consumers emit the same sentences. Changing any of these strings means
    telling running monitor first, not after.
    """

    TAIL = "running uncoordinated, no claims, no adapter routing, no card recovery"

    @pytest.fixture(autouse=True)
    def _stack(self, monkeypatch):
        import ble_stack

        monkeypatch.setattr(ble_stack, "shared_failure", None, raising=False)
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER_DIR", "/data/bcm", raising=False)
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER", True, raising=False)
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER_FORCE_START_NOTIFY", True, raising=False)
        # None in sys.modules makes `import bleak_connection_manager` raise
        # ImportError deterministically - the absent path, whatever sys.path holds
        monkeypatch.setitem(sys.modules, "bleak_connection_manager", None)
        return ble_stack

    def test_a_loaded_shared_install_reports_the_package_directory(self, _stack, monkeypatch, caplog):
        """The PACKAGE dir, not the configured folder: it proves which tree served."""
        module = types.ModuleType("bleak_connection_manager")
        module.__file__ = "/data/bcm/src/bleak_connection_manager/__init__.py"
        module.install_bleak_catcher = lambda *a, **k: None
        monkeypatch.setitem(sys.modules, "bleak_connection_manager", module)
        with caplog.at_level("INFO"):
            utils_ble_manager.install_ble_connection_manager("C8:47:8C:00:00:00")
        assert ("BLE coordination: bleak_connection_manager loaded from /data/bcm/src/bleak_connection_manager") in caplog.text

    def test_a_successful_install_states_the_policy_once(self, _stack, monkeypatch, caplog):
        """Seventh anchored line: BCM's own INFO never reaches this log (root stays at
        WARNING), so the StartNotify policy and the adapter shape are stated by the
        driver, once per life, right after the catcher installs."""
        module = types.ModuleType("bleak_connection_manager")
        module.__file__ = "/data/bcm/src/bleak_connection_manager/__init__.py"
        module.install_bleak_catcher = lambda *a, **k: None
        monkeypatch.setitem(sys.modules, "bleak_connection_manager", module)
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER_FORCE_START_NOTIFY", True, raising=False)
        monkeypatch.setattr(utils, "BLUETOOTH_ADAPTERS", ["C8:47:8C:00:00:00@00:1A:7D:DA:71:13", "hci1"], raising=False)
        with caplog.at_level("INFO"):
            assert utils_ble_manager.install_ble_connection_manager("C8:47:8C:00:00:00") is True
        line = "BLE coordination: catcher installed (force_start_notify=True, adapters=2 configured, 1 pinned)"
        assert caplog.text.count(line) == 1, caplog.text
        assert caplog.text.index("loaded from") < caplog.text.index("catcher installed"), "loaded first, then the policy"

    def test_an_absent_install_is_a_warning_not_an_error(self, _stack, monkeypatch, caplog):
        with caplog.at_level("DEBUG"):
            assert utils_ble_manager.install_ble_connection_manager("C8:47:8C:00:00:00") is False
        assert f"BLE coordination: no shared install at /data/bcm; {self.TAIL}" in caplog.text
        assert not [r for r in caplog.records if r.levelname == "ERROR"]

    def test_a_present_but_unusable_install_is_an_error(self, _stack, monkeypatch, caplog):
        monkeypatch.setattr(_stack, "shared_failure", "RuntimeError('boom')", raising=False)
        with caplog.at_level("DEBUG"):
            assert utils_ble_manager.install_ble_connection_manager("C8:47:8C:00:00:00") is False
        assert ("BLE coordination: shared install at /data/bcm is present but unusable, " "running uncoordinated: RuntimeError('boom')") in caplog.text
        assert [r for r in caplog.records if r.levelname == "ERROR"]

    def test_coordination_on_with_no_folder_configured_is_reported(self, _stack, monkeypatch, caplog):
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER_DIR", "", raising=False)
        with caplog.at_level("DEBUG"):
            assert utils_ble_manager.install_ble_connection_manager("C8:47:8C:00:00:00") is False
        assert ("BLE coordination: BLUETOOTH_CONNECTION_MANAGER is on but " f"BLUETOOTH_CONNECTION_MANAGER_DIR is empty; {self.TAIL}") in caplog.text

    def test_a_box_that_never_asked_for_coordination_says_nothing(self, _stack, monkeypatch, caplog):
        """The upstream default - option off, no shared install - is silent. Pinned."""
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER", False, raising=False)
        with caplog.at_level("DEBUG"):
            assert utils_ble_manager.install_ble_connection_manager("C8:47:8C:00:00:00") is False
        assert "BLE coordination:" not in caplog.text

    def test_every_line_carries_the_stable_anchor(self):
        """The watch matches the class on this prefix, not on the sentence: EVERY
        logger call inside install_ble_connection_manager must start with it, and
        the count is whatever the function emits (a magic number pins a layout,
        not the property). parse_link_caps' own warning is outside the function."""
        import ast

        with open(os.path.join(DRIVER_DIR, "utils_ble_manager.py"), encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "install_ble_connection_manager")
        emitted = []
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and getattr(node.func.value, "id", None) == "logger":
                arg = node.args[0]
                first = arg.values[0] if isinstance(arg, ast.JoinedStr) else arg
                emitted.append((node.func.attr, first.value if isinstance(first, ast.Constant) else None))
        assert len(emitted) >= 6, emitted
        for level, text in emitted:
            assert isinstance(text, str) and text.startswith("BLE coordination: "), (level, text)
        assert "Failed to install the BLE connection manager" not in source

    def test_a_catcher_that_will_not_install_is_not_blamed_on_the_shared_tree(self, _stack, monkeypatch, caplog):
        """An install failure and an unusable install are different faults.

        Reporting a bad kwarg or a raising validator as "the shared install is
        present but unusable" sends an operator to replace a tree that is fine.
        Caught by serialbattery-bcmv2 in the symbol diff of 425d813.
        """
        module = types.ModuleType("bleak_connection_manager")
        module.__file__ = "/data/bcm/src/bleak_connection_manager/__init__.py"

        def install_bleak_catcher(owner, **kwargs):
            raise TypeError("unexpected keyword argument")

        module.install_bleak_catcher = install_bleak_catcher
        monkeypatch.setitem(sys.modules, "bleak_connection_manager", module)
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER_VALIDATION", False, raising=False)

        with caplog.at_level("DEBUG"):
            assert utils_ble_manager.install_ble_connection_manager("C8:47:8C:00:00:00") is False

        assert "catcher would not install from /data/bcm" in caplog.text
        assert "is present but unusable" not in caplog.text

    def test_a_current_install_receives_the_start_notify_policy_as_a_kwarg(self, _stack, monkeypatch, caplog):
        calls = []
        module = types.ModuleType("bleak_connection_manager")
        module.__file__ = "/data/bcm/src/bleak_connection_manager/__init__.py"
        module.install_bleak_catcher = lambda owner, force_start_notify=None, **kw: calls.append(force_start_notify)
        monkeypatch.setitem(sys.modules, "bleak_connection_manager", module)
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER_VALIDATION", False, raising=False)
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER_FORCE_START_NOTIFY", True, raising=False)
        monkeypatch.delenv("BCM_FORCE_START_NOTIFY", raising=False)
        with caplog.at_level("DEBUG"):
            assert utils_ble_manager.install_ble_connection_manager("C8:47:8C:00:00:00") is True
        assert calls == [True]
        assert "BCM_FORCE_START_NOTIFY" not in os.environ
        assert "predates the force_start_notify parameter" not in caplog.text

    def test_an_older_install_keeps_the_catcher_and_gets_the_policy_by_environment(self, _stack, monkeypatch, caplog):
        """A shared install is whatever is on the box; an unknown kwarg must not cost the catcher."""
        calls = []
        module = types.ModuleType("bleak_connection_manager")
        module.__file__ = "/data/bcm/src/bleak_connection_manager/__init__.py"

        def install_bleak_catcher(owner, adapters, link_caps, wrap_scanner, validate_connection):
            calls.append(owner)  # signature deliberately lacks force_start_notify and **kwargs

        module.install_bleak_catcher = install_bleak_catcher
        monkeypatch.setitem(sys.modules, "bleak_connection_manager", module)
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER_VALIDATION", False, raising=False)
        monkeypatch.setattr(utils, "BLUETOOTH_CONNECTION_MANAGER_FORCE_START_NOTIFY", True, raising=False)
        monkeypatch.delenv("BCM_FORCE_START_NOTIFY", raising=False)
        with caplog.at_level("DEBUG"):
            assert utils_ble_manager.install_ble_connection_manager("C8:47:8C:00:00:00") is True
        assert len(calls) == 1, "the catcher must still install"
        assert os.environ.get("BCM_FORCE_START_NOTIFY") == "true"
        assert (
            "BLE coordination: shared install at /data/bcm predates the force_start_notify parameter; "
            "StartNotify policy passed through the legacy BCM_FORCE_START_NOTIFY environment"
        ) in caplog.text
        assert "catcher would not install" not in caplog.text
        monkeypatch.delenv("BCM_FORCE_START_NOTIFY", raising=False)
