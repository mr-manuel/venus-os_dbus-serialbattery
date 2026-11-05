# -*- coding: utf-8 -*-
"""Fallback sensor support as a wrapper around any configured Battery.

The whole feature lives in this file. ``FallbackBattery`` wraps a driver
instance and presents itself to ``DbusHelper`` as an ordinary ``Battery``:
attribute access is delegated to the wrapped driver, and the handful of
values the fallback feature changes are overridden here. The driver, the
harness and ``battery.py`` know nothing about it — the only hook is the
instantiation in ``dbus-serialbattery.py``.

What it does
------------

* **Serving rule.** BMS values are published only while the BMS is
  *connected* and its data is *younger than 15 s*; otherwise the values
  come from the configured fallback sensor (a shunt). Staleness is
  observed from the outside: the wrapper stamps its own clock whenever
  ``refresh_data()`` returns True with non-null core values. It never
  reads driver-private state. When the driver exposes a connection flag
  (``ble_handle.connected``), a known disconnect flips serving to the
  shunt instantly and skips ``refresh_data()`` entirely — reconnection is
  the driver's own daemon thread's job, and a call into a dead link only
  buys send timeouts.

* **Transparency (D2).** With no fallback sensor configured, or with one
  that is not answering, the wrapper is transparent: it serves whatever
  the wrapped driver serves and reports the driver's own refresh verdict,
  so the stock upstream disconnect handling in ``DbusHelper`` applies
  unchanged. There is no "both dark" hold: when both instruments are
  gone, this is an ordinary disconnect.

* **Governance.** While the shunt is serving, a private fallback mode
  keeps the alarm/ChargeMode/cell-projection bookkeeping: cell voltages
  are projected from the live shunt voltage onto a snapshot of the last
  live cell readings, the projection is checked against the configured
  safe zone, ``/Alarms/InternalFailure`` is suppressed (the delayed
  BmsCable warning is the outage's one voice) and ``/Mgmt/Connection``
  says where the values come from. Serving and governance share one
  clock by construction.

* **Persistence.** The wrapper stashes the little that D-Bus service
  registration needs (cell count, capacity, limits) to ``/data`` every
  five minutes, so a driver restart during an outage can register and
  serve shunt values without ever reaching the BMS. It also stashes the
  last real per-cell voltages **as a projection basis**, stamped with the
  age of the data rather than of the write, so a restarted process
  recomputes a current limit from the live shunt instead of serving a
  remembered one. A restored basis is an *input* only: it is never
  written into ``battery.cells`` and never published as a measurement.
"""

import json
import os
import sys
from time import time
from typing import Union

import utils
from utils import logger
from battery import Cell


def _alphanumeric(value) -> str:
    """
    Reduce a string to its lowercase alphanumeric characters, so identifiers
    that differ only in punctuation and case compare equal.

    :param value: the string to reduce
    :return: the reduced string
    """
    return "".join(character for character in str(value).lower() if character.isalnum())


class FallbackBattery:
    """Wrap a ``Battery`` so a fallback sensor serves while the BMS is away."""

    # ── serving ──────────────────────────────────────────────────────────
    #: BMS data older than this is not published, whatever the link says.
    #: Zombie and half-connected links report "connected" while delivering
    #: nothing, so the age of the data is the only honest source selector.
    FRESHNESS_SECONDS = 15.0

    # ── cell projection ──────────────────────────────────────────────────
    #: Re-entry margin for the safe-zone band checks (volts per cell): a
    #: direction blocked at a band edge is only re-allowed once the
    #: projected extreme is back inside the band by this margin, so
    #: chargers and inverters do not chatter at the edge.
    BAND_HYSTERESIS = 0.05

    #: Maximum plausible per-cell delta between the snapshot and the
    #: projection (volts per cell). A larger delta means the shunt is not
    #: measuring this pack (wrong pairing, series string) and the
    #: projection must not be trusted.
    PROJECTION_MAX_DELTA = 0.3

    #: Maximum age (seconds) of the BMS data underlying the cell snapshot
    #: for it to serve as a projection basis. Imbalance drifts, so
    #: projecting live shunt deltas onto cell voltages read too long ago
    #: fabricates precision the data no longer has: better no projection
    #: (configured limits, BMS self-protects) than a wrong one. Checked
    #: continuously, not only when the snapshot is taken.
    SNAPSHOT_MAX_AGE_SECONDS = 600.0

    # ── persistence ──────────────────────────────────────────────────────
    #: How often the registration stash is written to disk.
    STASH_INTERVAL_SECONDS = 300.0
    #: Directory of the stash; overridable for tests.
    STASH_DIRECTORY = "/data"

    # ── recovery ladder ──────────────────────────────────────────────────
    #: How long the wrapper may serve the shunt with zero fresh BMS data
    #: before it assumes the driver's reconnect machinery is wedged rather
    #: than the BMS being away, and acts. Long on purpose: a BMS can be
    #: legitimately unreachable for a while (a radio that needs quiet, a
    #: pack woken by a charger), and acting on a healthy outage costs more
    #: than waiting through one, since the fallback sensor is measuring
    #: throughout.
    STALL_MINUTES = 30.0
    #: In-process BLE thread rebuilds tried before giving up and asking
    #: for a driver restart.
    STALL_MAX_REBUILDS = 2

    #: The fallback sensor paths this wrapper can read, in probe order.
    #: The first configured one answers the "is the shunt alive?" question.
    SENSOR_KEYS = ("Voltage", "Current", "Temperature", "Soc")

    #: Everything else set on this object is forwarded to the wrapped
    #: battery, so ``DbusHelper`` writing e.g. ``battery.state`` reaches
    #: the driver. Keep this list in sync with ``__init__``.
    _WRAPPER_ATTRS = frozenset(
        (
            "battery",
            "dbus_fallback_objects",
            "bms_cable_alarm",
            "restart_requested",
            "_device",
            "_dbus_connection",
            "_shunt",
            "_shunt_alive",
            "_serving",
            "_last_fresh_time",
            "_fallback_mode",
            "_fallback_since",
            "_soc_anchor",
            "_shunt_soc_anchor",
            "_cell_snapshot",
            "_cell_snapshot_time",
            "_cell_snapshot_restored",
            "_projection_valid",
            "_charge_blocked",
            "_discharge_blocked",
            "_stash",
            "_stash_path",
            "_stash_written",
            "_stall_rebuilds",
            "_stall_action_time",
            "_last_stall_log",
        )
    )

    # ── construction ─────────────────────────────────────────────────────

    @staticmethod
    def resolve_device(battery) -> Union[str, None]:
        """
        Resolve the fallback sensor dbus device for a battery instance.

        ``FALLBACK_SENSOR_DBUS_DEVICE`` is either a single dbus service name,
        which applies to every battery instance, or a comma-separated list of
        IDENTIFIER:SERVICE pairs for setups where each battery has its own
        fallback device. The identifier is the battery specific suffix of the
        driver's own dbus service name, e.g. "ble_5320b7d7f9e7" for
        com.victronenergy.battery.ble_5320b7d7f9e7.

        :param battery: the battery instance to resolve the device for
        :return: The dbus service name of the fallback device, or None
        """
        raw = utils.FALLBACK_SENSOR_DBUS_DEVICE
        if raw is None:
            return None
        # dbus service names cannot contain ":", so a colon means the mapping syntax is used
        if ":" not in raw:
            return raw
        port = getattr(battery, "port", None) or ""
        identifier = port[port.rfind("/") + 1 :]
        for item in raw.split(","):
            key, _, value = item.strip().partition(":")
            if key.strip() == identifier and value.strip():
                return value.strip()
        return None

    @staticmethod
    def configured_for(battery) -> bool:
        """
        Whether the fallback feature is configured for this battery: a device
        is mapped to it and at least one value path is set. This is the opt-in
        that decides whether the harness wraps the battery at all.

        :param battery: the battery instance to check
        :return: True if this battery should be wrapped
        """
        if FallbackBattery.resolve_device(battery) is None:
            return False
        return any(FallbackBattery._path_for(key) is not None for key in FallbackBattery.SENSOR_KEYS)

    @staticmethod
    def _path_for(key: str) -> Union[str, None]:
        """
        Map a sensor key to its configured dbus path.

        :param key: one of SENSOR_KEYS
        :return: the configured dbus path, or None if not configured
        """
        return {
            "Voltage": utils.FALLBACK_SENSOR_DBUS_PATH_VOLTAGE,
            "Current": utils.FALLBACK_SENSOR_DBUS_PATH_CURRENT,
            "Temperature": utils.FALLBACK_SENSOR_DBUS_PATH_TEMPERATURE,
            "Soc": utils.FALLBACK_SENSOR_DBUS_PATH_SOC,
        }.get(key)

    def __init__(self, battery):
        object.__setattr__(self, "battery", battery)

        self.dbus_fallback_objects: dict = None
        """Resolved VeDbusItemImport proxies of the fallback sensor, or None."""
        self._device: str = FallbackBattery.resolve_device(battery)
        self._dbus_connection = None

        self._shunt: dict = {}
        """This cycle's fallback sensor readings, taken once per refresh."""
        self._shunt_alive: bool = False
        self._serving: bool = False
        """True while this cycle's published values come from the shunt."""
        self._last_fresh_time: float = 0.0
        """Observed clock: last time the wrapped battery delivered real data."""

        self._fallback_mode: bool = False
        self._fallback_since: float = None
        self._soc_anchor: float = None
        self._shunt_soc_anchor: float = None
        self._cell_snapshot: list = None
        self._cell_snapshot_time: float = None
        self._cell_snapshot_restored: bool = False
        """Whether the current basis came off disk rather than from this
        process. A restored basis is an input to the projection only: it
        must never be written back into the cells as a measurement."""
        self._projection_valid: bool = False
        self._charge_blocked: bool = False
        self._discharge_blocked: bool = False

        self.bms_cable_alarm: int = 0
        """Cable alarm this wrapper asks for (delayed warn while serving)."""
        self.restart_requested: bool = False
        """Set when the recovery ladder is exhausted; the helper exits then."""

        self._stash: dict = {}
        self._stash_path: str = os.path.join(self.STASH_DIRECTORY, f"fallback_state_{self._stash_identifier()}.json")
        self._stash_written: float = 0.0
        self._stall_rebuilds: int = 0
        self._stall_action_time: float = 0.0
        self._last_stall_log: float = 0.0

        self._load_stash()

        logger.info(f"Fallback sensor for {getattr(battery, 'port', '?')}: {self._device}")

    def _stash_identifier(self) -> str:
        """
        Build the per-battery stash file name component.

        Uses the same identity the config mapping uses (the battery specific
        suffix of the dbus service name) plus the bus address where one is
        used, so it is stable from the very first cycle — unlike
        ``unique_identifier()``, which some drivers only know after reading
        the BMS, and this stash exists precisely for the case where the BMS
        was never reached.

        :return: a filename-safe identifier for this battery
        """
        port = getattr(self.battery, "port", None) or "unknown"
        raw = port[port.rfind("/") + 1 :]
        address = getattr(self.battery, "address", None)
        # Serial ports carry several bus addresses; BLE ports already spell the
        # address out, so only add it when it is not in there already.
        if address and _alphanumeric(address) not in _alphanumeric(raw):
            raw += "_" + str(address)
        return "".join(character if character.isalnum() else "_" for character in raw)

    # ── delegation ───────────────────────────────────────────────────────

    def __getattr__(self, name):
        # Only called when normal lookup fails, i.e. for everything that is
        # neither wrapper state nor a wrapper override.
        try:
            battery = object.__getattribute__(self, "battery")
        except AttributeError:
            raise AttributeError(name)
        return getattr(battery, name)

    # DbusHelper re-applies TEMPERATURE_*_ADJUST to these attributes on every
    # success cycle. While the fallback serves, the driver never refreshes
    # them, so each pass would adjust the previous pass's output - the values
    # would compound without bound over a long outage. Dropping the writes
    # while serving freezes them at the last live reading, exactly what the
    # pre-wrapper fallback did by skipping the adjustment during an outage.
    _FROZEN_WHILE_SERVING = frozenset(
        (
            "temperature_1",
            "temperature_2",
            "temperature_3",
            "temperature_4",
            "temperature_mos",
        )
    )

    def __setattr__(self, name, value):
        # DbusHelper writes to the battery (state, temperatures, online,
        # connection_info, history values, ...). Those must reach the driver
        # instance, or nothing else that reads it directly sees them.
        if name in FallbackBattery._WRAPPER_ATTRS:
            object.__setattr__(self, name, value)
        elif name in FallbackBattery._FROZEN_WHILE_SERVING and getattr(self, "_serving", False):
            pass
        else:
            setattr(self.battery, name, value)

    @property
    def __class__(self):
        # Present the wrapped driver's class: isinstance(battery, Battery)
        # keeps working, and the harness's BMS-type detection cache (which
        # stores battery.__class__.__name__) keeps recording the driver
        # rather than this wrapper.
        return self.battery.__class__

    def __repr__(self):
        return f"FallbackBattery({self.battery!r})"

    # ── measurement topology ─────────────────────────────────────────────

    def get_paired_sensor_device(self) -> Union[str, None]:
        """
        Expose the paired instrument for consumers that need the measurement
        topology: a second dbus service measuring the same physical battery.

        This wrapper is the only component that knows a battery has a second
        instrument on it, so it is the natural place to publish that fact.
        The name is deliberately generic rather than fallback specific: the
        pairing is a physical fact about the installation — a shunt bolted to
        the same pack — not a feature of this wrapper. Serving values from
        that instrument during an outage is one use of the pairing; declaring
        it so that consumers do not double count the pack is another.

        :return: the dbus service name of the paired sensor, or None when no
            fallback sensor device is configured for this battery
        """
        return self._device

    # ── fallback sensor plumbing ─────────────────────────────────────────

    def setup_fallback_sensor(self) -> None:
        """
        Resolve the fallback sensor's dbus items.

        Unlike the external sensor, which always overrides the BMS values, the
        fallback sensor is only read while the BMS values are not current.

        :return: None
        """
        import dbus
        from dbus.mainloop.glib import DBusGMainLoop
        from vedbus import VeDbusItemImport

        try:
            if self._device is None:
                logger.warning("No fallback sensor device configured for this battery, fallback not available")
                return

            DBusGMainLoop(set_as_default=True)

            # connect to the sessionbus, on a CC GX the systembus is used
            if self._dbus_connection is None:
                self._dbus_connection = dbus.SessionBus() if "DBUS_SESSION_BUS_ADDRESS" in os.environ else dbus.SystemBus()

            if self._device not in self._dbus_connection.list_names():
                return

            dbus_objects = {}
            for key in self.SENSOR_KEYS:
                path = self._path_for(key)
                if path is not None:
                    logger.info(f"Using fallback sensor for {key.lower()}: {self._device}{path}")
                    dbus_objects[key] = VeDbusItemImport(self._dbus_connection, self._device, path)

            self.dbus_fallback_objects = dbus_objects

        except Exception:
            self.dbus_fallback_objects = None
            exception_type, exception_object, exception_traceback = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
            logger.error("Fallback sensor setup failed, fallback not available")

    def _watch_fallback_sensor(self) -> None:
        """
        Follow the fallback sensor service coming and going, so a restarted
        shunt driver is picked up again and a removed one stops being trusted.

        :return: None
        """
        if self._device is None:
            return
        try:
            if self._dbus_connection is None:
                self.setup_fallback_sensor()
                return
            present = self._device in self._dbus_connection.list_names()
            if self.dbus_fallback_objects is not None and not present:
                logger.error("Fallback sensor was disconnected, fallback not available")
                self.dbus_fallback_objects = None
            elif self.dbus_fallback_objects is None and present:
                logger.info("Fallback sensor was connected")
                self.setup_fallback_sensor()
        except Exception as e:
            logger.debug(f"Fallback sensor watch failed: {repr(e)}")

    def read_fallback_sensor(self, key: str) -> Union[float, None]:
        """
        Read a value straight from the resolved fallback sensor proxy.

        This is the liveness probe: "is the shunt answering right now?" is a
        different question from "should the published values come from it?".

        :param key: "Voltage", "Current", "Temperature" or "Soc"
        :return: the value, or None if unresolved, unmapped or unreadable
        """
        objects = self.dbus_fallback_objects
        if objects is None or key not in objects or objects[key] is None:
            return None
        try:
            return objects[key].get_value()
        except Exception:
            return None

    def get_value_from_fallback_sensor(self, key: str) -> Union[float, None]:
        """
        The fallback sensor value this cycle is serving, if any.

        :param key: "Voltage", "Current", "Temperature" or "Soc"
        :return: the value, or None if the BMS is being served instead
        """
        if not self._serving:
            return None
        return self._shunt.get(key)

    # ── serving decision ─────────────────────────────────────────────────

    def _bms_connected(self) -> Union[bool, None]:
        """
        The driver's own opinion on whether the BMS link is up.

        :return: True/False when the driver exposes a connection state
                 (``ble_handle.connected``), None when it does not
        """
        handle = getattr(self.battery, "ble_handle", None)
        if handle is None:
            return None
        connected = getattr(handle, "connected", None)
        return bool(connected) if connected is not None else None

    def _core_values_present(self) -> bool:
        """
        Whether the wrapped battery currently holds the values that make a
        refresh worth stamping as "real data". A driver that returns True
        with empty core values has not delivered anything to serve.

        Note for other drivers: a BMS that never reports SoC at all would
        never stamp here and would therefore serve the fallback sensor
        permanently. Relax this to the values that BMS does report when one
        turns up; every driver in tree reports all three.

        :return: True if voltage, current and SoC are all set
        """
        return self.battery.voltage is not None and self.battery.current is not None and self.battery.soc is not None

    def _read_shunt(self) -> dict:
        """
        Take this cycle's snapshot of the fallback sensor, so every published
        value and every decision below uses one consistent set of readings.

        :return: the readings, keyed by sensor key
        """
        readings = {}
        for key in self.SENSOR_KEYS:
            value = self.read_fallback_sensor(key)
            if value is not None:
                readings[key] = value
        return readings

    def _external_active(self, key: str) -> bool:
        """
        Whether the (separate) external sensor feature is supplying this value.
        The external sensor always overrides the BMS, and therefore the shunt.

        :param key: "Voltage", "Current", "Temperature" or "Soc"
        :return: True if the external sensor answers for this key
        """
        objects = self.battery.dbus_external_objects
        if objects is None or objects.get(key) is None:
            return False
        try:
            return objects[key].get_value() is not None
        except Exception:
            return False

    def refresh_data(self) -> bool:
        """
        Refresh the wrapped battery, then decide what this cycle publishes.

        Returns True whenever there are values to publish — fresh BMS data or
        live fallback data — so DbusHelper's disconnect handling stays out of
        the way while an instrument is still measuring. When both are gone the
        wrapped driver's own verdict is returned unchanged and the stock
        upstream disconnect handling takes over.

        :return: True if this cycle has values to publish
        """
        self._watch_fallback_sensor()

        connected = self._bms_connected()
        if connected is False:
            # Known disconnect: do not spend the cycle on send timeouts.
            # Reconnecting is the driver's daemon thread's job.
            result = False
        else:
            result = self.battery.refresh_data()
            if result and self._core_values_present():
                self._last_fresh_time = time()

        fresh = (time() - self._last_fresh_time) <= self.FRESHNESS_SECONDS
        want_fallback = self.dbus_fallback_objects is not None and not (connected is not False and fresh)

        self._shunt = self._read_shunt() if want_fallback else {}
        self._shunt_alive = bool(self._shunt)
        self._serving = want_fallback and self._shunt_alive

        self._update_fallback_mode(fresh)
        self._update_projection()
        self._update_alarms()
        self._update_recovery_ladder()
        self._update_stash(fresh)

        return True if self._serving else result

    # ── governance ───────────────────────────────────────────────────────

    def _update_fallback_mode(self, fresh: bool) -> None:
        """
        Engage and leave the private fallback mode that governs alarms,
        ChargeMode and cell projection.

        Engagement follows serving; leaving requires the published values to
        have gone back to the BMS *and* that data to be FRESH — a shunt that
        stops answering mid-outage must not destroy the projection basis and
        re-arm the alarms while the BMS is still away.

        :param fresh: whether the wrapped battery's data is current
        :return: None
        """
        if fresh and not self._serving:
            if self._fallback_mode:
                logger.info(">>> Battery responds again, leaving fallback mode <<<")
                # Data provably resumed: clear the stale-data escalation
                # before the next publish, or the cycle between leaving
                # fallback and the next BMS read publishes a spurious
                # InternalFailure alarm.
                self._clear_internal_failure()
                # Undo the projection: put the measured basis voltages back
                # into the cells. Freshness proves core values resumed, not
                # that a cell frame arrived yet - without this, a partial
                # frame lets the next engagement snapshot our own synthetic
                # voltages as if they were measurements.
                # A restored basis is not this process's measurement, so it
                # is put back as *unread* rather than as a reading: nothing
                # off disk may reach a published cell voltage.
                if self._cell_snapshot is not None:
                    for index, voltage in enumerate(self._cell_snapshot):
                        if index < len(self.battery.cells):
                            self.battery.cells[index].voltage = None if self._cell_snapshot_restored else voltage
            self._fallback_mode = False
            self._fallback_since = None
            self._soc_anchor = None
            self._shunt_soc_anchor = None
            self._cell_snapshot = None
            self._cell_snapshot_time = None
            self._cell_snapshot_restored = False
            self._projection_valid = False
            self._charge_blocked = False
            self._discharge_blocked = False
            self._stall_rebuilds = 0
            self._stall_action_time = 0.0
            return

        if self._serving and not self._fallback_mode:
            self._fallback_mode = True
            self._fallback_since = time()
            self._charge_blocked = False
            self._discharge_blocked = False
            self._take_soc_anchor()
            self._take_cell_snapshot()
            logger.warning(
                "    Entering fallback mode: voltage/current/temperature/SoC live from the fallback sensor, "
                "cell voltages projected from the last live reading"
            )

    def _take_soc_anchor(self) -> None:
        """
        Record the pair of readings the served SoC will be built from.

        The BMS and the fallback sensor rarely agree on absolute SoC: they
        are two independent estimates of the same pack, and a couple of
        points apart is normal. Publishing the sensor's absolute value on
        engagement therefore steps the SoC, and publishing the BMS value
        again on recovery steps it back. On a system that loses its BMS link
        a few times an hour that is a sawtooth on every consumer that reads
        it, including the ESS minimum-SoC comparison.

        Anchoring fixes that without inventing a number: hold the BMS's last
        reading, and move it by how far the sensor's own reading travels
        during the outage. The travel is the sensor's coulomb count, which is
        a measurement; only its absolute value is an estimate, and that is
        the part being discarded.

        Both readings are needed for the pair to mean anything. Without them
        the served SoC falls back to the sensor's absolute value, which is
        what a process that has never reached the BMS has to do anyway.

        :return: None
        """
        bms_soc = self.battery.soc
        shunt_soc = self._shunt.get("Soc")
        if bms_soc is None or shunt_soc is None:
            self._soc_anchor = None
            self._shunt_soc_anchor = None
            return
        self._soc_anchor = bms_soc
        self._shunt_soc_anchor = shunt_soc

    def _take_cell_snapshot(self) -> None:
        """
        Capture the projection basis at engagement, in order of preference:

        1. this process's own cell readings, if every cell is readable and
           the data behind them is within SNAPSHOT_MAX_AGE_SECONDS;
        2. otherwise an existing basis, if there is one and it is still
           within that age — this is the mid-outage restart, where the basis
           came off disk and the live cells are all unread precisely because
           restored cells are deliberately left that way;
        3. otherwise nothing, and the projection is unavailable.

        Reading the live cells unconditionally would destroy a restored basis
        the moment the shunt engaged, which is the whole point of stashing it.

        :return: None
        """
        cell_count = self.battery.cell_count if self.battery.cell_count is not None else 0
        cells = [cell.voltage for cell in self.battery.cells[:cell_count]]
        # The basis is as old as the data the cells came from, which is the
        # last observed live refresh — zero for a process that has never seen
        # one, so live cells cannot pass this in a mid-outage restart.
        if cells and all(voltage is not None for voltage in cells) and self._basis_within_age(self._last_fresh_time):
            self._cell_snapshot = cells
            self._cell_snapshot_time = self._last_fresh_time
            self._cell_snapshot_restored = False
            return

        if self._cell_snapshot is not None and self._basis_within_age(self._cell_snapshot_time):
            return

        self._cell_snapshot = None
        self._cell_snapshot_time = None
        self._cell_snapshot_restored = False

    def _basis_within_age(self, basis_time: Union[float, None]) -> bool:
        """
        :param basis_time: when the data behind a basis was observed
        :return: whether a basis of that age may still be projected from
        """
        if not basis_time:
            return False
        return (time() - basis_time) <= self.SNAPSHOT_MAX_AGE_SECONDS

    def project_cells(self, shunt_voltage: Union[float, None]) -> Union[list, None]:
        """
        Project per-cell voltages from the live fallback shunt voltage.

        Series cells carry identical current, so the pack delta since the
        snapshot is distributed evenly across the cells: the known imbalance
        is carried forward instead of being erased by the sum.

        The basis age is re-checked on every call, not only when the snapshot
        was taken — imbalance drifts, and a projection is refused as soon as
        its basis is older than SNAPSHOT_MAX_AGE_SECONDS.

        :param shunt_voltage: live pack voltage from the fallback sensor
        :return: projected per-cell voltages, or None if not possible
        """
        if self._cell_snapshot is None or shunt_voltage is None:
            return None
        if not self._basis_within_age(self._cell_snapshot_time):
            return None
        delta_per_cell = (shunt_voltage - sum(self._cell_snapshot)) / len(self._cell_snapshot)
        if abs(delta_per_cell) > self.PROJECTION_MAX_DELTA:
            return None
        return [voltage + delta_per_cell for voltage in self._cell_snapshot]

    def zone_configured(self) -> bool:
        """
        Whether the dedicated fallback safe zone is configured and sane.

        :return: True if FALLBACK_SAFE_CELL_VOLTAGE_MIN/MAX are usable
        """
        return 0 < utils.FALLBACK_SAFE_CELL_VOLTAGE_MIN < utils.FALLBACK_SAFE_CELL_VOLTAGE_MAX

    def update_band_flags(self, projected_min: float, projected_max: float) -> None:
        """
        Evaluate the projected cell extremes against the fallback safe zone
        with hysteresis: above the zone charging is blocked, below the zone
        discharging is blocked, inside the zone both are allowed. Without a
        configured zone there is no basis for blind charging: charging stays
        blocked, discharging stays allowed with the last known limits.

        :param projected_min: lowest projected cell voltage
        :param projected_max: highest projected cell voltage
        :return: None
        """
        if not self.zone_configured():
            self._charge_blocked = True
            self._discharge_blocked = False
            return

        if projected_max >= utils.FALLBACK_SAFE_CELL_VOLTAGE_MAX:
            self._charge_blocked = True
        elif projected_max < utils.FALLBACK_SAFE_CELL_VOLTAGE_MAX - self.BAND_HYSTERESIS:
            self._charge_blocked = False

        if projected_min <= utils.FALLBACK_SAFE_CELL_VOLTAGE_MIN:
            self._discharge_blocked = True
        elif projected_min > utils.FALLBACK_SAFE_CELL_VOLTAGE_MIN + self.BAND_HYSTERESIS:
            self._discharge_blocked = False

    def _update_projection(self) -> None:
        """
        Project the cell voltages from this cycle's shunt voltage and publish
        them onto the wrapped battery, so everything that reads cells (min/max,
        midpoint, balance display, the CVL/CCL management) sees one consistent
        picture instead of pack voltage from the shunt and cells from an old
        BMS read.

        :return: None
        """
        if not self._fallback_mode:
            return
        projected = self.project_cells(self._shunt.get("Voltage") if self._serving else None)
        self._projection_valid = projected is not None
        if projected is None:
            return
        for index, voltage in enumerate(projected):
            self.battery.cells[index].voltage = round(voltage, 3)
        self.update_band_flags(min(projected), max(projected))

    def _clear_internal_failure(self) -> None:
        """
        Drop the driver's stale-data escalation.

        :return: None
        """
        protection = getattr(self.battery, "protection", None)
        if protection is not None:
            protection.internal_failure = 0

    def _update_alarms(self) -> None:
        """
        While the fallback sensor is actively serving, the outage's one
        designated voice is the delayed BmsCable warning. The driver's
        stale-data InternalFailure escalation predates the fallback feature
        and only duplicates it as alarm noise.

        :return: None
        """
        if self._serving:
            self._clear_internal_failure()
            outage = time() - (self._fallback_since if self._fallback_since is not None else time())
            self.bms_cable_alarm = 1 if outage >= utils.FALLBACK_BMS_CABLE_WARN_MINUTES * 60 else 0
        else:
            # Not serving: either everything is fine, or both instruments are
            # gone and DbusHelper's own cable alarm ladder is running.
            self.bms_cable_alarm = 0

    def _update_recovery_ladder(self) -> None:
        """
        When the wrapper has served the shunt for STALL_MINUTES with zero
        fresh BMS data, rebuild the driver's BLE thread in-process: it cures
        a wedged reconnect loop, and against a BMS that is simply away it is
        a cheap no-op (the fresh thread scans like the old one did).

        Staleness alone NEVER requests a driver restart: the wrapper cannot
        distinguish a wedged loop from a long outage, outages are covered
        operation (that is the feature), and restart-cycling the dbus service
        every STALL window during a multi-hour outage is exactly the churn
        the fallback exists to prevent. A restart is requested only when the
        rebuild machinery itself fails - the one case an in-process cure
        cannot reach.

        :return: None
        """
        if not self._serving:
            return
        since = max(self._last_fresh_time, self._stall_action_time, self._fallback_since or 0.0)
        stalled_for = time() - since
        if stalled_for < self.STALL_MINUTES * 60:
            return

        self._stall_action_time = time()
        handle = getattr(self.battery, "ble_handle", None)
        if self._stall_rebuilds < self.STALL_MAX_REBUILDS and handle is not None and hasattr(handle, "rebuild_ble_thread"):
            self._stall_rebuilds += 1
            logger.error(
                f">>> No BMS data for {stalled_for:.0f}s while serving the fallback sensor — "
                f"rebuilding the BLE thread in-process (attempt {self._stall_rebuilds}/{self.STALL_MAX_REBUILDS}) <<<"
            )
            try:
                handle.rebuild_ble_thread()
            except Exception as e:
                logger.error(f">>> BLE thread rebuild failed mechanically ({repr(e)}). Exiting so the driver restarts. <<<")
                self.restart_requested = True
        elif time() - self._last_stall_log >= 3600.0:
            self._last_stall_log = time()
            logger.warning(
                f">>> No BMS data for {stalled_for:.0f}s; in-process rebuilds exhausted. " "Holding on the fallback sensor until the BMS returns. <<<"
            )

    # ── persistence ──────────────────────────────────────────────────────

    def _load_stash(self) -> None:
        """
        Load the registration stash and apply it to the wrapped battery, so
        the dbus service can be registered without ever reaching the BMS.

        Carries no served values: voltage, current, SoC and the cell
        voltages are never restored onto the battery. Restored cells exist
        (the per-cell dbus paths are built once, at registration) but are
        left unread, so nothing can publish a persisted number as a
        measurement.

        The stashed cell voltages are restored to a different place: they
        seed the projection *basis*, an input to project_cells(). That is
        what lets a mid-outage restart compute a current limit from the live
        shunt rather than serve the pack's persisted rating - a limit that
        was computed self-clears when conditions change, a persisted one is
        a latch with no input that could ever revise it.

        :return: None
        """
        try:
            if not os.path.exists(self._stash_path):
                return
            with open(self._stash_path, "r") as stash_file:
                self._stash = json.load(stash_file)
        except Exception as e:
            # Loud: without the stash a boot with no BMS contact cannot
            # register, which is the very scenario the stash exists for.
            logger.warning(f"Fallback stash could not be read: {repr(e)}")
            self._stash = {}
            return

        age = time() - self._stash.get("timestamp", 0)
        logger.info(f"Fallback stash loaded ({age:.0f}s old): registration without BMS contact is possible")

        try:
            # Capacity is a BMS reading with no config equivalent, so it is
            # restored whatever the source.
            if self._stash.get("capacity") is not None:
                self.battery.capacity = self._stash["capacity"]

            # The four DVCC values are restored only when they came from the
            # BMS. With USE_BMS_DVCC_VALUES off they are config values, or
            # config multiplied by the cell count, and the base class already
            # applies them from the config as it reads today. Restoring them
            # would pin whatever the config said when the stash was last
            # written, so an edited limit would never reach a registration
            # made without BMS contact.
            if utils.USE_BMS_DVCC_VALUES:
                for name in ("max_battery_voltage", "min_battery_voltage", "max_battery_charge_current", "max_battery_discharge_current"):
                    if self._stash.get(name) is not None:
                        setattr(self.battery, name, self._stash[name])
            if self._stash.get("hardware_version"):
                self.battery.hardware_version = self._stash["hardware_version"]
            cell_count = self._stash.get("cell_count") or 0
            if cell_count > 0:
                self.battery.cell_count = cell_count
                while len(self.battery.cells) < cell_count:
                    self.battery.cells.append(Cell(False))
                del self.battery.cells[cell_count:]
            self._restore_projection_basis(cell_count)
        except Exception as e:
            logger.debug(f"Fallback stash could not be applied: {repr(e)}")

    def _restore_projection_basis(self, cell_count: int) -> None:
        """
        Seed the projection basis from the stash, without touching the cells.

        The voltages land in _cell_snapshot, never in battery.cells: they are
        an input to project_cells(), not a reading. The recorded time is the
        age of the DATA, so the ordinary SNAPSHOT_MAX_AGE_SECONDS check
        refuses a basis from an outage the process slept through.

        :param cell_count: the restored cell count, 0 if unknown
        :return: None
        """
        cells = self._stash.get("cells")
        basis_time = self._stash.get("cells_time")
        if not cells or not basis_time or any(voltage is None for voltage in cells):
            return
        if cell_count and len(cells) != cell_count:
            return
        self._cell_snapshot = list(cells)
        self._cell_snapshot_time = basis_time
        self._cell_snapshot_restored = True
        logger.info(f"Fallback projection basis restored ({time() - basis_time:.0f}s old): limits will be computed, not remembered")

    def _update_stash(self, fresh: bool) -> None:
        """
        Refresh the stash from live BMS data and write it at most every
        STASH_INTERVAL_SECONDS. Only real data is stashed: an outage must
        never overwrite a good stash with the nothing it knows.

        :param fresh: whether the wrapped battery's data is current
        :return: None
        """
        if not fresh or self.battery.cell_count is None:
            return
        previous = self._stash or {}
        self._stash = {
            "timestamp": time(),
            "cell_count": self.battery.cell_count,
            "capacity": self.battery.capacity,
            "max_battery_voltage": self.battery.max_battery_voltage,
            "min_battery_voltage": self.battery.min_battery_voltage,
            "max_battery_charge_current": self.battery.max_battery_charge_current,
            "max_battery_discharge_current": self.battery.max_battery_discharge_current,
            "hardware_version": self.battery.hardware_version,
        }
        self._stash_projection_basis(previous)
        if time() - self._stash_written < self.STASH_INTERVAL_SECONDS:
            return
        self._write_stash()

    def _stash_projection_basis(self, previous: dict) -> None:
        """
        Carry the projection basis into the rebuilt stash.

        What is persisted is the *input* to the limit calculation, not the
        limit: a restarted process projects it against the live shunt and
        arrives at a current answer that self-clears when conditions change.
        A persisted limit could not - it would latch, which is how a zeroed
        CCL once propagated bank-wide with nothing able to revise it.

        Only measurements qualify. Projected voltages are this wrapper's own
        arithmetic, so nothing is taken while fallback mode is engaged; a
        cycle that cannot offer a full frame carries the previous basis
        forward rather than dropping it, on the same principle that stops an
        outage overwriting a good stash.

        :param previous: the stash contents before this refresh
        :return: None
        """
        cells = [cell.voltage for cell in self.battery.cells[: self.battery.cell_count]]
        if not self._fallback_mode and cells and all(voltage is not None for voltage in cells):
            self._stash["cells"] = cells
            # Stamped with the age of the data, not of the write, so the
            # recorded age survives the restart meaningfully.
            self._stash["cells_time"] = self._last_fresh_time
        elif previous.get("cells") and previous.get("cells_time"):
            self._stash["cells"] = previous["cells"]
            self._stash["cells_time"] = previous["cells_time"]

    def _write_stash(self) -> None:
        """
        Write the stash to disk.

        :return: None
        """
        if not self._stash:
            return
        try:
            # Atomic: a power cut mid-write must never truncate the stash -
            # a corrupt stash silently loses the boot-without-BMS registration
            # this file exists to provide.
            temporary_path = self._stash_path + ".tmp"
            with open(temporary_path, "w") as stash_file:
                json.dump(self._stash, stash_file)
            os.replace(temporary_path, self._stash_path)
            self._stash_written = time()
            logger.debug(f"Fallback stash written to {self._stash_path}")
        except Exception as e:
            logger.debug(f"Fallback stash could not be written: {repr(e)}")

    # ── startup ──────────────────────────────────────────────────────────

    def test_connection(self) -> bool:
        """
        Let the driver test its connection, and stand in for it when it fails.

        The driver only reports success once it has real data, which is the
        honest answer for a driver but the wrong answer for a battery that has
        a second instrument watching it: with a stash to register from and a
        fallback sensor configured, the service must come up and start serving
        shunt values immediately instead of leaving the system with no battery
        at all until the BMS happens to answer. The driver's own reconnect
        machinery keeps chasing the BMS in the background.

        :return: True if the service should be registered
        """
        try:
            if self.battery.test_connection():
                if self._core_values_present():
                    self._last_fresh_time = time()
                return True
        except Exception as e:
            logger.error(f"Fallback: the wrapped driver's connection test raised {repr(e)}")

        if self._device is not None and self._stash:
            logger.warning(
                f">>> No BMS contact at startup — registering from the fallback stash and serving {self._device}. "
                "The driver keeps trying to reach the BMS in the background. <<<"
            )
            # Resolve the sensor and serve one cycle BEFORE the service is
            # registered, so the values are real the instant the paths exist.
            # Consumers that recompute on change sample the leading edge by
            # construction, and would otherwise read None off a brand-new
            # service for a full poll interval.
            self.refresh_data()
            return True
        return False

    # ── values ───────────────────────────────────────────────────────────

    def get_voltage(self) -> Union[float, None]:
        """
        :return: the served voltage
        """
        voltage = self.battery.get_voltage()
        if not self._serving or self._external_active("Voltage"):
            return voltage
        shunt = self._shunt.get("Voltage")
        return round(shunt, 3) if shunt is not None else voltage

    def get_current(self) -> Union[float, None]:
        """
        :return: the served current
        """
        # Always call through: the wrapped getter owns the coulomb counting
        # and its timestamps, which must advance exactly once per cycle.
        current = self.battery.get_current()
        if not self._serving or self._external_active("Current"):
            return current
        shunt = self._shunt.get("Current")
        if shunt is None:
            return current
        shunt = round(shunt, 3)
        # When a FET is off the BMS physically blocks that direction of
        # current flow; the last known FET state still applies while it is away.
        if self.battery.discharge_fet is False:
            shunt = max(0.0, shunt)
        if self.battery.charge_fet is False:
            shunt = min(0.0, shunt)
        return shunt

    def get_power(self) -> Union[float, None]:
        """
        :return: the power, derived from the served voltage and current
        """
        # Always call through: the wrapped getter owns the energy counting and
        # its timestamps, which must advance exactly once per cycle. It counts
        # the power published last cycle, which is the served one.
        power = self.battery.get_power()
        if not self._serving:
            return power
        voltage = self.get_voltage()
        current = self.battery.current_calc
        return voltage * current if voltage is not None and current is not None else power

    def get_soc(self) -> Union[float, None]:
        """
        :return: the served state of charge
        """
        soc = self.battery.get_soc()
        if not self._serving or self._external_active("Soc"):
            return soc
        shunt = self._shunt.get("Soc")
        if shunt is None:
            return soc
        if self._soc_anchor is None or self._shunt_soc_anchor is None:
            # No anchor pair, so the sensor's absolute value is all there is
            return round(shunt, 3)
        # Anchored: the BMS reading at engagement, moved by how far the
        # sensor has travelled since. Clamped, because the sum of two
        # readings from different instruments can leave the range even when
        # each is in it.
        anchored = self._soc_anchor + (shunt - self._shunt_soc_anchor)
        return round(min(100.0, max(0.0, anchored)), 3)

    def get_temperature(self) -> Union[float, None]:
        """
        :return: the served temperature
        """
        temperature = self.battery.get_temperature()
        if not self._serving or self._external_active("Temperature"):
            return temperature
        shunt = self._shunt.get("Temperature")
        return round(shunt, 1) if shunt is not None else temperature

    def set_calculated_data(self) -> None:
        """
        Run the calculations through this wrapper, so the served values end up
        on the wrapped battery where everything else reads them.

        :return: None
        """
        self.battery.current_calc = self.get_current()
        self.battery.power_calc = self.get_power()
        self.battery.soc_calc = self.get_soc()

    def get_capacity_remain(self) -> Union[float, None]:
        """
        While the shunt is serving, derive the remaining capacity from the
        served SoC so Capacity, ConsumedAmphours and TimeToGo stay consistent
        with it instead of freezing at the BMS-reported value.

        :return: the remaining capacity
        """
        if self._serving and self.battery.capacity is not None and self.battery.soc_calc is not None:
            return self.battery.capacity * self.battery.soc_calc / 100
        return self.battery.get_capacity_remain()

    def get_capacity_consumed(self) -> Union[float, None]:
        """
        :return: the consumed capacity, derived from the served remaining capacity
        """
        remain = self.get_capacity_remain()
        if self.battery.capacity is not None and remain is not None:
            return abs(self.battery.capacity - remain) * -1
        return None

    # ── governed reports ─────────────────────────────────────────────────

    def _charge_is_blocked(self) -> bool:
        """
        :return: True if the fallback governance blocks charging this cycle
        """
        if not self._fallback_mode or not self._projection_valid:
            return False
        return not self.zone_configured() or self._charge_blocked

    def _discharge_is_blocked(self) -> bool:
        """
        :return: True if the fallback governance blocks discharging this cycle
        """
        if not self._fallback_mode or not self._projection_valid:
            return False
        return self.zone_configured() and self._discharge_blocked

    def _fet_never_read(self, fet) -> bool:
        """
        Whether a FET state is unknown rather than known to be open.

        The base class reads an unset FET as "not allowed", which is right for
        a battery that is talking and wrong for one that has never been
        reached: a service registered from the stash would report both
        directions blocked while publishing full configured limits, and a
        blocked flag does not stay local, it reaches DVCC through any
        aggregator that takes a minimum over the bank.

        Reports, not cutoffs: the BMS opens its own FETs whether or not this
        driver can see them, so an unread FET is not a reason to assert a
        block. A FET the BMS has actually reported as open is honoured.

        :param fet: the FET state as last read, or None if never read
        :return: whether the state is unknown
        """
        return self._serving and fet is None

    def get_allow_to_charge(self) -> bool:
        """
        :return: whether charging is allowed
        """
        if self._charge_is_blocked():
            return False
        if self._fet_never_read(self.battery.charge_fet):
            return bool(self.battery.control_allow_charge)
        return self.battery.get_allow_to_charge()

    def get_allow_to_discharge(self) -> bool:
        """
        :return: whether discharging is allowed
        """
        if self._discharge_is_blocked():
            return False
        if self._fet_never_read(self.battery.discharge_fet):
            return bool(self.battery.control_allow_discharge)
        return self.battery.get_allow_to_discharge()

    def manage_charge_voltage(self) -> None:
        """
        Run the CVL state machine only when there are cell voltages to run it on.

        Registering from the stash produces a battery whose cells exist but
        were never read. The state machine subtracts the minimum cell voltage
        from the maximum without guarding for that, and its own TypeError
        handler treats the result as a fault: CVL collapses to the float
        voltage and error code 8 lights up the GUI - for what is a legitimate
        state, on every restart that cannot reach the BMS. Publish the
        configured ceiling instead and let the state machine start when real
        cell voltages do.

        :return: None
        """
        if self._cells_unread():
            if self.battery.control_voltage is None:
                ceiling = self.battery.max_battery_voltage
                if ceiling is None and self.battery.cell_count:
                    ceiling = utils.MAX_CELL_VOLTAGE * self.battery.cell_count
                if ceiling is not None:
                    self.battery.control_voltage = round(ceiling, 2)
            return
        self.battery.manage_charge_voltage()

    def manage_charge_and_discharge_current(self) -> None:
        """
        Skip the current limiters while their inputs have not been read.

        The limiter suite assumes a full BMS dataset. Run against a partial
        one it still lands on the configured current, which is the right
        answer, but noisily: unread cells raise error code 8 on the way
        there, and unread temperatures make the temperature limiter log a
        warning on every single cycle - observed at two per second for the
        whole registration-without-BMS-contact window, on a device that
        logs to flash. Publish the configured limits directly until the
        BMS has delivered what the limiters consume.

        Cells count as read once a projection basis is written onto them,
        so a mid-outage restart with a restored basis runs the limiters
        normally - but temperatures are never projected, so those wait for
        a real frame.

        :return: None
        """
        if self._cells_unread() or self._temperatures_unread():
            charge_limit = self.battery.max_battery_charge_current
            discharge_limit = self.battery.max_battery_discharge_current
            self.battery.control_charge_current = charge_limit if charge_limit is not None else utils.MAX_BATTERY_CHARGE_CURRENT
            self.battery.control_discharge_current = discharge_limit if discharge_limit is not None else utils.MAX_BATTERY_DISCHARGE_CURRENT
            return
        self.battery.manage_charge_and_discharge_current()

    def _temperatures_unread(self) -> bool:
        """
        Whether the temperature limiters would run against unread sensors.

        Only meaningful when temperature-based limiting is enabled; with it
        disabled the limiters never consult the sensors and there is nothing
        to wait for.

        :return: whether enabled temperature limiting lacks its inputs
        """
        if not (utils.CCCM_T_ENABLE or utils.DCCM_T_ENABLE):
            return False
        return self.battery.get_max_temperature() is None or self.battery.get_min_temperature() is None

    def _cells_unread(self) -> bool:
        """
        Whether there is nothing to compute a limit from.

        Deliberately asked of the cells rather than of the link: a usable
        projection basis has already been written onto them by
        _update_projection() before DbusHelper calls the managers, so a
        mid-outage restart with a restored basis computes its limits from
        the live shunt like any other serving cycle. The configured rating
        is taken only when there is neither a reading nor a projection -
        which is a statement about the cells, and the cells are where both
        arrive.

        :return: whether the pack has no cell voltages at all
        """
        return self.battery.get_max_cell_voltage() is None or self.battery.get_min_cell_voltage() is None

    @property
    def control_charge_current(self):
        """Charge current limit; zero only when the projection says so.

        Without a valid projection the configured limits are kept. Zeroing
        them propagated bank-wide once (the aggregate went strict, the Multi
        raised "BMS connection lost" and the whole bank showed
        charging/discharging not allowed) — a system outage caused by our own
        conservatism. These are reports, not cutoffs: the BMS's own protection
        does the disconnecting, and the live shunt still watches the pack.
        """
        return 0 if self._charge_is_blocked() else self.battery.control_charge_current

    @property
    def control_discharge_current(self):
        """Discharge current limit; zero only when the projection says so."""
        return 0 if self._discharge_is_blocked() else self.battery.control_discharge_current

    @property
    def charge_mode(self):
        """Charge mode string, replaced by the fallback state while SERVING.

        Gated on _serving, not _fallback_mode: when the shunt also stops
        answering, fallback_mode stays engaged (it guards the projection
        basis) but DbusHelper's stock disconnect ladder takes over the
        user-visible story - a "Fallback" label next to its "Disconnect in:"
        countdown would be contradictory.
        """
        if not self._fallback_mode or not self._serving:
            return self.battery.charge_mode
        if not self._projection_valid:
            return "Fallback - no cell projection (limits unchanged, BMS self-protects)"
        if not self.zone_configured():
            return "Fallback - charging blocked (no safe zone configured)"
        if self._charge_blocked and self._discharge_blocked:
            return "Fallback - charge and discharge blocked (projected cells outside safe zone)"
        if self._charge_blocked:
            return "Fallback - charging blocked (projected cell above safe zone)"
        if self._discharge_blocked:
            return "Fallback - discharging blocked (projected cell below safe zone)"
        return "Fallback - operating on projected cells"

    @property
    def online(self):
        """Module online state.

        False while the shunt is serving: the values published are real, but
        the BMS this service represents is not answering, and
        /System/NrOfModulesOnline is the place that says so. When the shunt is
        not serving either, the wrapped battery's own state is reported, so
        the stock disconnect handling sees exactly what it expects.
        """
        return False if self._serving else self.battery.online

    @property
    def connection_info(self):
        """Connection line for the GUI, telling the truth while serving."""
        if not self._serving:
            return self.battery.connection_info
        outage = int(time() - self._fallback_since) if self._fallback_since is not None else 0
        return f"BMS lost for: {self.battery.get_seconds_to_string(outage, 3)} | operating on live fallback values"

    def connection_name(self) -> str:
        """
        Surface the fallback state where every stock GUI already shows it: the
        "Connection" row of the device page and the VRM device list.

        :return: the connection name, suffixed while the shunt serves
        """
        name = self.battery.connection_name()
        return name + " - FALLBACK: on shunt" if self._serving else name
