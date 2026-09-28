# -*- coding: utf-8 -*-
"""Tests for the run scripts that enable.sh generates for the daemontools services.

The run script's process is the one supervise watches. If it forks python into
the background and waits, a TERM that the shell forwards but python outlives
leaves the shell exiting, supervise respawning, and the old python reparented to
init while still holding its D-Bus name. Using exec makes python the run process
itself, so there is nothing to fall out of sync.

The generator is shell, so these tests run the emitting block and read what it
writes, rather than matching the source that writes it.
"""

import os
import re
import subprocess

import pytest

ENABLE_SH = os.path.join(os.path.dirname(__file__), "..", "dbus-serialbattery", "enable.sh")

# redirect target -> positional arguments the block is emitted with
SERVICES = {
    "/service/dbus-blebattery.$1/run": ["0", "Jkbms_Ble", "C8:47:8C:E4:9F:2A"],
    "/service/dbus-canbattery.$1/run": ["can0"],
    "/service/dbus-mqttbattery/run": ["mqtt-battery"],
}

# the log/run scripts, generated next to each run script
LOG_SERVICES = {
    "/service/dbus-blebattery.$1/log/run": ["0", "Jkbms_Ble", "C8:47:8C:E4:9F:2A"],
    "/service/dbus-canbattery.$1/log/run": ["can0"],
    "/service/dbus-mqttbattery/log/run": ["mqtt-battery"],
}

# the log/run of the serial service, shipped as a file instead of generated
STATIC_LOG_RUN = os.path.join(os.path.dirname(__file__), "..", "dbus-serialbattery", "service", "log", "run")

# the run script of the serial service, shipped as a file instead of generated
STATIC_RUN = os.path.join(os.path.dirname(__file__), "..", "dbus-serialbattery", "service", "run")

# every run script this repository installs, generated or shipped. A check that only
# enumerates the generated ones cannot see a defect in the shipped one.
ALL_RUN_SCRIPTS = sorted(SERVICES) + ["service/run"]

# multilog keeps n files of s bytes. Sized against the rate during an incident, not
# when idle, because the flood that accompanies an incident evicts the record of it.
EXPECTED_RETENTION = "s1500000 n20"


def _extract_block(target):
    """Return the shell group command that writes the run script for `target`.

    The generator emits each run script as `{ ... } > "<target>"`. Dropping the
    redirect leaves a group command that writes the same bytes to stdout.
    """
    with open(ENABLE_SH, encoding="utf-8") as enable_file:
        lines = enable_file.read().splitlines()

    closing = f'}} > "{target}"'
    end = next(i for i, line in enumerate(lines) if line.strip() == closing)
    start = next(i for i in range(end, -1, -1) if lines[i].strip() == "{")

    return "\n".join(lines[start:end] + ["}"])


def _render(target):
    """Run the emitting block and return the run script it produces."""
    arguments = dict(SERVICES, **LOG_SERVICES)[target]
    result = subprocess.run(
        ["sh", "-s"] + arguments,
        input=_extract_block(target),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _run_script(target):
    """Return a run script, rendering it if generated and reading it if shipped."""
    if target == "service/run":
        with open(STATIC_RUN, encoding="utf-8") as static_file:
            return static_file.read()
    return _render(target)


@pytest.mark.parametrize("target", sorted(SERVICES))
def test_run_script_execs_python(target):
    """python must replace the shell, so it becomes the process supervise watches."""
    rendered = _render(target)

    assert re.search(r"^exec python .*dbus-serialbattery\.py", rendered, re.MULTILINE)


@pytest.mark.parametrize("target", sorted(SERVICES))
def test_run_script_does_not_background_python(target):
    """A trailing & is what creates the second process this change removes."""
    rendered = _render(target)

    python_lines = [line for line in rendered.splitlines() if "dbus-serialbattery.py" in line]
    assert python_lines
    for line in python_lines:
        assert not line.rstrip().endswith("&")


@pytest.mark.parametrize("target", ALL_RUN_SCRIPTS)
@pytest.mark.parametrize("shim", ["trap ", "PID=$!", "wait $PID", "EXIT_STATUS"])
def test_run_script_has_no_signal_forwarding_shim(target, shim):
    """No part of the fork-and-wait shim may survive; each piece is a failure mode."""
    assert shim not in _run_script(target)


@pytest.mark.parametrize("target", sorted(SERVICES))
def test_run_script_keeps_stderr_redirect(target):
    """`exec 2>&1` is the redirect-only form and must not be dropped with the rest."""
    rendered = _render(target)

    assert "exec 2>&1" in rendered


def test_ble_run_script_keeps_the_disconnect_preamble():
    """The preamble runs before python and survives the exec, so it must stay."""
    rendered = _render("/service/dbus-blebattery.$1/run")

    lines = rendered.splitlines()
    disconnect = next(i for i, line in enumerate(lines) if line.startswith("bluetoothctl disconnect"))
    python = next(i for i, line in enumerate(lines) if "dbus-serialbattery.py" in line)
    assert disconnect < python


def test_run_script_is_a_valid_shell_script():
    """A run script that does not parse would fail only at service start."""
    for target in ALL_RUN_SCRIPTS:
        rendered = _run_script(target)
        assert rendered.startswith("#!/bin/sh")
        subprocess.run(["sh", "-n"], input=rendered, text=True, check=True)


def test_static_run_script_execs_the_start_script():
    """The serial service starts through start-serialbattery.sh, which must replace the shell."""
    lines = _run_script("service/run").splitlines()

    launch = [line for line in lines if "start-serialbattery.sh" in line]
    assert launch == ['exec bash /data/apps/dbus-serialbattery/start-serialbattery.sh "$PORT_NAME"']


def test_static_run_script_keeps_the_port_derivation():
    """PORT_NAME is derived before the exec and passed to it, so it must survive the change."""
    lines = _run_script("service/run").splitlines()

    derive = next(i for i, line in enumerate(lines) if line.startswith("PORT_NAME="))
    launch = next(i for i, line in enumerate(lines) if "start-serialbattery.sh" in line)
    assert derive < launch


@pytest.mark.parametrize("target", sorted(LOG_SERVICES))
def test_log_run_script_uses_the_agreed_retention(target):
    """Retention is sized against the log rate during an incident, not when idle."""
    rendered = _render(target)

    assert f"multilog t {EXPECTED_RETENTION} " in rendered


def test_static_log_run_matches_the_generated_ones():
    """The serial service ships its log/run as a file, so it drifts silently."""
    with open(STATIC_LOG_RUN, encoding="utf-8") as static_file:
        static = static_file.read()

    assert f"multilog t {EXPECTED_RETENTION} " in static


def test_every_service_keeps_the_same_amount_of_log():
    """One service retaining less than the others is the case that loses the evidence."""
    settings = {re.search(r"multilog t (s\d+ n\d+)", _render(target)).group(1) for target in LOG_SERVICES}

    with open(STATIC_LOG_RUN, encoding="utf-8") as static_file:
        settings.add(re.search(r"multilog t (s\d+ n\d+)", static_file.read()).group(1))

    assert settings == {EXPECTED_RETENTION}
