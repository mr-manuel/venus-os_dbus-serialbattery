# -*- coding: utf-8 -*-
"""Tests for the hciattach lookup of the LLT/JBD BLE BMS.

The lookup replaces "ps -ww | grep hciattach | grep -v grep", so it must find the
real process and, more importantly, must not mistake something else for it. Its
result is written to /tmp/dbus-blebattery-hciattach and later passed to os.system(),
so a wrong answer is executed rather than merely reported.
"""

import os
import sys
import types
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "dbus-serialbattery", "ext", "velib_python"))

sys.modules.setdefault("bleak", types.SimpleNamespace(BleakClient=MagicMock, BleakScanner=MagicMock, BLEDevice=MagicMock))
sys.modules.setdefault("bleak.exc", types.SimpleNamespace(BleakDBusError=type("BleakDBusError", (Exception,), {})))
# another test module may have registered a thinner utils_ble stub already, so complete it
# instead of relying on setdefault(), which would silently keep the incomplete one
utils_ble_stub = sys.modules.setdefault("utils_ble", types.SimpleNamespace())
for attribute, value in (("Syncron_Ble", None), ("restart_ble_hardware_and_bluez_driver", lambda: None)):
    if not hasattr(utils_ble_stub, attribute):
        setattr(utils_ble_stub, attribute, value)

from bms import lltjbd_ble  # noqa: E402
from bms.lltjbd_ble import get_hciattach_cmdline  # noqa: E402

HCIATTACH_ARGUMENTS = ["/usr/bin/hciattach", "/dev/ttyS0", "bcm43xx", "921600", "noflow", "-"]
HCIATTACH_CMDLINE = " ".join(HCIATTACH_ARGUMENTS)

# None of these is hciattach, but every one of them mentions it. A command line match,
# which is what the replaced shell pipeline did, would accept one of them.
DECOYS = (
    ("100", ["/bin/sh", "-c", "while :; do pgrep hciattach; sleep 5; done"], "sh"),
    ("101", ["grep", "hciattach"], "grep"),
    ("102", ["/usr/local/bin/check-hciattach.sh"], "check-hciattach"),
    ("103", ["python3", "/opt/hciattach_monitor.py"], "python3"),
)


def _write_process(proc_path, pid, arguments, comm):
    """Create a /proc/PID directory with a cmdline and a comm file."""
    process_path = os.path.join(proc_path, pid)
    os.makedirs(process_path)

    with open(os.path.join(process_path, "cmdline"), "wb") as cmdline_file:
        cmdline_file.write(b"\0".join(argument.encode() for argument in arguments) + (b"\0" if arguments else b""))

    with open(os.path.join(process_path, "comm"), "w") as comm_file:
        comm_file.write(comm + "\n")


def _build_proc(tmp_path, processes):
    proc_path = str(tmp_path / "proc")
    os.makedirs(proc_path)
    for pid, arguments, comm in processes:
        _write_process(proc_path, pid, arguments, comm)
    return proc_path


def test_returns_full_command_line_of_hciattach(tmp_path):
    """The stored value has to be the whole command line, since it gets re-run as is."""
    proc_path = _build_proc(tmp_path, [("1", ["/sbin/init"], "init"), ("902", HCIATTACH_ARGUMENTS, "hciattach")])

    assert get_hciattach_cmdline(proc_path) == HCIATTACH_CMDLINE


def test_returns_none_when_hciattach_is_not_running(tmp_path):
    """This is the normal state on systems without a UART attached controller."""
    proc_path = _build_proc(tmp_path, [("1", ["/sbin/init"], "init")])

    assert get_hciattach_cmdline(proc_path) is None


def test_ignores_processes_that_only_mention_hciattach(tmp_path):
    """A monitoring script or a shell must not be taken for the BMS controller."""
    proc_path = _build_proc(tmp_path, DECOYS)

    assert get_hciattach_cmdline(proc_path) is None


def test_finds_hciattach_between_decoys(tmp_path):
    """Rejecting the decoys must not also reject the real process."""
    proc_path = _build_proc(tmp_path, list(DECOYS) + [("902", HCIATTACH_ARGUMENTS, "hciattach")])

    assert get_hciattach_cmdline(proc_path) == HCIATTACH_CMDLINE


def test_ignores_process_that_exits_during_the_scan(tmp_path):
    """/proc entries disappear while they are read, that must not raise."""
    proc_path = _build_proc(tmp_path, [("902", HCIATTACH_ARGUMENTS, "hciattach")])
    os.makedirs(os.path.join(proc_path, "1234"))

    assert get_hciattach_cmdline(proc_path) == HCIATTACH_CMDLINE


def test_ignores_hciattach_without_a_command_line(tmp_path):
    """An empty command line would be written out and later run as an empty command."""
    proc_path = _build_proc(tmp_path, [("55", [], "hciattach")])

    assert get_hciattach_cmdline(proc_path) is None


def test_returns_none_without_a_proc_filesystem(tmp_path):
    """The lookup runs in __init__(), so it must not raise if /proc is missing."""
    assert get_hciattach_cmdline(str(tmp_path / "missing")) is None


# --- The caller in LltJbd_Ble.__init__() -------------------------------------------------------
#
# The crash was not in the lookup but in its caller: __init__ called .group() on the result of
# re.search(), which is None whenever hciattach is not running, and raised AttributeError while
# constructing the battery. These tests run the real __init__ with its one hardcoded file
# redirected into tmp_path, so nothing is read from or written to the real /tmp.

CACHE_FILE = "/tmp/dbus-blebattery-hciattach"


@pytest.fixture
def init_env(tmp_path, monkeypatch):
    """Redirect the cache file, stub the lookup and record every relaunch."""
    cache = tmp_path / "dbus-blebattery-hciattach"
    env = types.SimpleNamespace(cache=cache, running=None, relaunched=[])

    real_open = open
    real_isfile = os.path.isfile

    def redirected(path):
        return str(cache) if path == CACHE_FILE else path

    monkeypatch.setattr(lltjbd_ble, "open", lambda path, *args, **kwargs: real_open(redirected(path), *args, **kwargs), raising=False)
    monkeypatch.setattr(lltjbd_ble.os.path, "isfile", lambda path: real_isfile(redirected(path)))
    monkeypatch.setattr(lltjbd_ble, "get_hciattach_cmdline", lambda: env.running)
    monkeypatch.setattr(lltjbd_ble.os, "system", lambda command: env.relaunched.append(command))

    return env


def _construct():
    return lltjbd_ble.LltJbd_Ble(None, None, "A4:C1:37:00:00:01")


def test_init_without_hciattach_does_not_raise(init_env):
    """The crash: normal on any system whose Bluetooth is not a UART controller running hciattach."""
    init_env.running = None

    _construct()

    # nothing to remember, so nothing is written; an empty file would be run on the next start
    assert not init_env.cache.exists()


def test_init_remembers_the_running_hciattach(init_env):
    init_env.running = HCIATTACH_CMDLINE

    _construct()

    assert init_env.cache.read_text() == HCIATTACH_CMDLINE
    assert init_env.relaunched == []


def test_init_leaves_a_running_hciattach_alone(init_env):
    init_env.cache.write_text(HCIATTACH_CMDLINE)
    init_env.running = HCIATTACH_CMDLINE

    _construct()

    assert init_env.relaunched == []


def test_init_relaunches_hciattach_that_has_stopped(init_env):
    """The remembered command line is run again when hciattach is found not running."""
    init_env.cache.write_text(HCIATTACH_CMDLINE)
    init_env.running = None

    _construct()

    assert init_env.relaunched == [HCIATTACH_CMDLINE]
