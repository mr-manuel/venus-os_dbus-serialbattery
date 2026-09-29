"""Tests for _CachedDbusProxy in dbushelper.py.

Platform-specific modules (dbus, velib_python) are stubbed via conftest.py
so these tests run on macOS, CI, and Linux alike.
"""

import pytest
from unittest.mock import MagicMock

import dbushelper
from dbushelper import PUBLISH_GATE_THRESHOLDS, PUBLISH_HEARTBEAT_S, DbusHelper, _CachedDbusProxy, _SENTINEL


@pytest.fixture
def mock_svc():
    """A mock VeDbusService supporting [] get/set and arbitrary attributes."""
    svc = MagicMock()
    svc._store = {}

    def setitem(path, value):
        svc._store[path] = value

    def getitem(path):
        return svc._store[path]

    svc.__setitem__ = MagicMock(side_effect=setitem)
    svc.__getitem__ = MagicMock(side_effect=getitem)
    return svc


@pytest.fixture
def proxy(mock_svc):
    return _CachedDbusProxy(mock_svc)


_UNSET = object()


class FakeServiceContext:
    """Stand-in for velib_python's ServiceContext.

    Mirrors ext/velib_python/vedbus.py: a write updates the stored value at
    once, but is only recorded for the batch when the value actually changed
    (``VeDbusItemExport._local_set_value`` returns None for an equal value),
    and flushing a context with no changes emits no ItemsChanged at all.
    """

    def __init__(self, parent):
        self.parent = parent
        self.changes = {}

    def __setitem__(self, path, value):
        if self.parent._set_local(path, value):
            self.changes[path] = value

    def __getitem__(self, path):
        return self.parent[path]

    def flush(self):
        if self.changes:
            self.parent.batches.append(dict(self.changes))
            self.changes.clear()


class FakeService:
    """Stand-in for VeDbusService with velib's rate-limiter stack semantics."""

    def __init__(self):
        self._store = {}
        self._ratelimiters = []
        self.direct_writes = []
        self.batches = []

    def _set_local(self, path, value):
        """velib's _local_set_value: store the value, report whether it changed."""
        if self._store.get(path, _UNSET) == value:
            return False
        self._store[path] = value
        return True

    def __setitem__(self, path, value):
        # velib's VeDbusService.__setitem__ bypasses the rate limiters and
        # emits PropertiesChanged straight away, but only for a changed value.
        if self._set_local(path, value):
            self.direct_writes.append((path, value))

    def __getitem__(self, path):
        return self._store[path]

    def __enter__(self):
        ctx = FakeServiceContext(self)
        self._ratelimiters.append(ctx)
        return ctx

    def __exit__(self, *exc):
        if self._ratelimiters:
            self._ratelimiters.pop().flush()


@pytest.fixture
def fake_svc():
    return FakeService()


@pytest.fixture
def batched_proxy(fake_svc):
    return _CachedDbusProxy(fake_svc)


class TestSetItem:
    """__setitem__: only forward writes when the value actually changes."""

    def test_first_write_always_forwards(self, proxy, mock_svc):
        proxy["/Soc"] = 50
        mock_svc.__setitem__.assert_called_once_with("/Soc", 50)

    def test_duplicate_write_is_suppressed(self, proxy, mock_svc):
        proxy["/Soc"] = 50
        proxy["/Soc"] = 50
        assert mock_svc.__setitem__.call_count == 1

    def test_changed_value_is_forwarded(self, proxy, mock_svc):
        proxy["/Soc"] = 50
        proxy["/Soc"] = 51
        assert mock_svc.__setitem__.call_count == 2
        mock_svc.__setitem__.assert_called_with("/Soc", 51)

    def test_none_is_a_valid_first_write(self, proxy, mock_svc):
        proxy["/ErrorCode"] = None
        mock_svc.__setitem__.assert_called_once_with("/ErrorCode", None)

    def test_none_to_none_is_suppressed(self, proxy, mock_svc):
        proxy["/ErrorCode"] = None
        proxy["/ErrorCode"] = None
        assert mock_svc.__setitem__.call_count == 1

    def test_none_to_value_is_forwarded(self, proxy, mock_svc):
        proxy["/ErrorCode"] = None
        proxy["/ErrorCode"] = 1
        assert mock_svc.__setitem__.call_count == 2

    def test_value_to_none_is_forwarded(self, proxy, mock_svc):
        proxy["/ErrorCode"] = 1
        proxy["/ErrorCode"] = None
        assert mock_svc.__setitem__.call_count == 2

    def test_unchanged_nan_is_suppressed(self, proxy, mock_svc):
        # NaN != NaN, so the equality check cannot catch it and the threshold
        # comparison is False for NaN too: without an explicit guard an
        # unchanging NaN republishes on every cycle, forever.
        proxy["/Dc/0/Voltage"] = float("nan")
        proxy["/Dc/0/Voltage"] = float("nan")
        assert mock_svc.__setitem__.call_count == 1

    def test_nan_to_a_real_value_is_forwarded(self, proxy, mock_svc):
        proxy["/Dc/0/Voltage"] = float("nan")
        proxy["/Dc/0/Voltage"] = 52.4
        assert mock_svc.__setitem__.call_count == 2

    def test_real_value_to_nan_is_forwarded(self, proxy, mock_svc):
        proxy["/Dc/0/Voltage"] = 52.4
        proxy["/Dc/0/Voltage"] = float("nan")
        assert mock_svc.__setitem__.call_count == 2

    def test_independent_paths_tracked_separately(self, proxy, mock_svc):
        proxy["/Soc"] = 50
        proxy["/Dc/0/Voltage"] = 13.6
        proxy["/Soc"] = 50  # suppressed
        proxy["/Dc/0/Voltage"] = 13.7  # forwarded
        assert mock_svc.__setitem__.call_count == 3

    def test_zero_is_distinct_from_none(self, proxy, mock_svc):
        proxy["/Alarms/HighVoltage"] = 0
        proxy["/Alarms/HighVoltage"] = None
        assert mock_svc.__setitem__.call_count == 2

    def test_float_equality(self, proxy, mock_svc):
        proxy["/Dc/0/Voltage"] = 13.600
        proxy["/Dc/0/Voltage"] = 13.6
        assert mock_svc.__setitem__.call_count == 1

    def test_string_values(self, proxy, mock_svc):
        proxy["/ConnectionInformation"] = "BLE connected"
        proxy["/ConnectionInformation"] = "BLE connected"
        assert mock_svc.__setitem__.call_count == 1
        proxy["/ConnectionInformation"] = "BLE disconnected"
        assert mock_svc.__setitem__.call_count == 2

    def test_list_values_compared_by_equality(self, proxy, mock_svc):
        proxy["/Voltages/Cell1"] = [3.3, 3.4]
        proxy["/Voltages/Cell1"] = [3.3, 3.4]
        assert mock_svc.__setitem__.call_count == 1
        proxy["/Voltages/Cell1"] = [3.3, 3.5]
        assert mock_svc.__setitem__.call_count == 2

    def test_same_object_identity_suppresses(self, proxy, mock_svc):
        """The `is` check short-circuits before equality for the same object."""
        obj = {"key": "value"}
        proxy["/Custom"] = obj
        proxy["/Custom"] = obj  # same object identity
        assert mock_svc.__setitem__.call_count == 1

    def test_bool_vs_int_distinction(self, proxy, mock_svc):
        """In Python bool is a subclass of int: True == 1, False == 0.
        The proxy uses equality, so True -> 1 is correctly suppressed
        since they compare equal.  This documents the expected behavior."""
        proxy["/ChargeFet"] = True
        proxy["/ChargeFet"] = 1  # True == 1, suppressed by equality
        assert mock_svc.__setitem__.call_count == 1


class TestSignificanceGate:
    """__setitem__: gated paths only re-publish once the value moved enough."""

    def test_below_threshold_is_suppressed(self, proxy, mock_svc):
        proxy["/Dc/0/Current"] = 10.0
        proxy["/Dc/0/Current"] = 10.05  # 0.05 A < 0.1 A gate
        assert mock_svc.__setitem__.call_count == 1
        assert mock_svc._store["/Dc/0/Current"] == 10.0

    def test_at_threshold_is_published(self, proxy, mock_svc):
        proxy["/Dc/0/Current"] = 10.0
        proxy["/Dc/0/Current"] = 10.1  # exactly the gate, must not be swallowed
        assert mock_svc.__setitem__.call_count == 2

    def test_above_threshold_is_published(self, proxy, mock_svc):
        proxy["/Dc/0/Power"] = 100.0
        proxy["/Dc/0/Power"] = 106.0  # 6 W > 5 W gate
        assert mock_svc.__setitem__.call_count == 2
        assert mock_svc._store["/Dc/0/Power"] == 106.0

    def test_comparison_base_is_the_last_published_value(self, proxy, mock_svc):
        """Cumulative drift must eventually cross the gate.

        The suppressed value must NOT become the new comparison base,
        otherwise a slow ramp would never publish again.
        """
        proxy["/Dc/0/Temperature"] = 20.0
        for step in (20.05, 20.1, 20.15):
            proxy["/Dc/0/Temperature"] = step
            assert mock_svc.__setitem__.call_count == 1
        proxy["/Dc/0/Temperature"] = 20.2  # 0.2 °C away from 20.0
        assert mock_svc.__setitem__.call_count == 2
        assert mock_svc._store["/Dc/0/Temperature"] == 20.2

    def test_float_representation_error_does_not_swallow_a_step(self, proxy, mock_svc):
        """4.35 - 4.34 evaluates to 0.00999999999999978 in binary floats.

        Values are published pre-rounded, so a single 10 mV step must still
        pass the 0.01 V gate despite the representation error.
        """
        assert abs(4.35 - 4.34) < 0.01  # the trap this guards against
        proxy["/Dc/0/Voltage"] = 4.34
        proxy["/Dc/0/Voltage"] = 4.35
        assert mock_svc.__setitem__.call_count == 2

    def test_first_write_of_a_gated_path_always_publishes(self, proxy, mock_svc):
        proxy["/TimeToGo"] = 5
        mock_svc.__setitem__.assert_called_once_with("/TimeToGo", 5)

    def test_transition_to_none_is_never_gated(self, proxy, mock_svc):
        proxy["/Dc/0/Current"] = 10.0
        proxy["/Dc/0/Current"] = None
        assert mock_svc.__setitem__.call_count == 2
        proxy["/Dc/0/Current"] = 10.02
        assert mock_svc.__setitem__.call_count == 3

    def test_ungated_path_publishes_every_change(self, proxy, mock_svc):
        """/Soc is deliberately not gated - ESS compares it to MinimumSocLimit."""
        assert "/Soc" not in PUBLISH_GATE_THRESHOLDS
        proxy["/Soc"] = 50.0
        proxy["/Soc"] = 50.01
        assert mock_svc.__setitem__.call_count == 2

    @pytest.mark.parametrize(
        "path",
        [
            "/Info/MaxChargeVoltage",
            "/Info/MaxChargeCurrent",
            "/Info/MaxDischargeCurrent",
            "/Info/BatteryLowVoltage",
            "/Info/ChargeRequest",
        ],
    )
    def test_info_limits_are_ungated(self, proxy, mock_svc, path):
        """Charge control limits must publish exactly; a stale limit is a control error."""
        assert path not in PUBLISH_GATE_THRESHOLDS
        proxy[path] = 55.2
        proxy[path] = 55.21
        assert mock_svc.__setitem__.call_count == 2

    @pytest.mark.parametrize(
        "path",
        [
            "/Alarms/LowVoltage",
            "/Alarms/HighVoltage",
            "/Alarms/HighTemperature",
            "/Alarms/BmsCable",
            "/Alarms/CellImbalance",
        ],
    )
    def test_alarms_are_ungated(self, proxy, mock_svc, path):
        """Alarm state is discrete and must reach consumers immediately."""
        assert path not in PUBLISH_GATE_THRESHOLDS
        proxy[path] = 0
        proxy[path] = 1
        proxy[path] = 2
        assert mock_svc.__setitem__.call_count == 3

    def test_no_gated_path_is_a_control_or_alarm_path(self):
        for path in PUBLISH_GATE_THRESHOLDS:
            assert not path.startswith("/Info/"), path
            assert not path.startswith("/Alarms/"), path

    def test_all_thresholds_are_positive_numbers(self):
        for path, threshold in PUBLISH_GATE_THRESHOLDS.items():
            assert isinstance(threshold, (int, float)), path
            assert threshold > 0, path

    def test_bool_is_never_gated(self, proxy, mock_svc):
        """bool is an int subclass; a flag must never be threshold-compared."""
        proxy["/TimeToGo"] = False
        proxy["/TimeToGo"] = True  # abs(1 - 0) = 1 < the 60 s gate
        assert mock_svc.__setitem__.call_count == 2


class TestHeartbeat:
    """Entering the batch context periodically drops the proxy's cache.

    What that buys on the bus is narrower than "re-publish every path":
    velib itself suppresses a write whose value equals the one it already
    holds, so an unchanged value is NOT re-sent. The heartbeat's observable
    effect is to refresh a value that has been sitting under its gate
    threshold, bounding how long the published value can lag the measured
    one. These tests pin that contract; a value held under its gate is used
    wherever a test needs the heartbeat to be visible.
    """

    @pytest.fixture
    def clock(self, monkeypatch):
        state = {"now": 1_000_000.0}
        monkeypatch.setattr(dbushelper, "time", lambda: state["now"])
        return state

    def test_no_refresh_before_the_interval(self, clock, fake_svc):
        proxy = _CachedDbusProxy(fake_svc)
        with proxy:
            proxy["/Dc/0/Current"] = 10.0
        clock["now"] += PUBLISH_HEARTBEAT_S - 1
        with proxy:
            proxy["/Dc/0/Current"] = 10.05  # below the gate
        assert fake_svc.batches == [{"/Dc/0/Current": 10.0}]

    def test_heartbeat_refreshes_a_value_held_under_its_gate(self, clock, fake_svc):
        proxy = _CachedDbusProxy(fake_svc)
        with proxy:
            proxy["/Dc/0/Current"] = 10.0
        with proxy:
            proxy["/Dc/0/Current"] = 10.05  # suppressed by the gate
        assert fake_svc.batches == [{"/Dc/0/Current": 10.0}]

        clock["now"] += PUBLISH_HEARTBEAT_S
        with proxy:
            proxy["/Dc/0/Current"] = 10.05
        assert fake_svc.batches == [{"/Dc/0/Current": 10.0}, {"/Dc/0/Current": 10.05}]

    def test_heartbeat_does_not_resend_unchanged_values(self, clock, fake_svc):
        """On a quiescent bank the heartbeat emits nothing: velib drops equal values."""
        proxy = _CachedDbusProxy(fake_svc)
        with proxy:
            proxy["/Dc/0/Current"] = 10.0
            proxy["/Soc"] = 50.0

        clock["now"] += PUBLISH_HEARTBEAT_S
        with proxy:
            proxy["/Dc/0/Current"] = 10.0
            proxy["/Soc"] = 50.0
        assert fake_svc.batches == [{"/Dc/0/Current": 10.0, "/Soc": 50.0}]

    def test_heartbeat_is_only_evaluated_on_the_outermost_enter(self, clock, fake_svc):
        proxy = _CachedDbusProxy(fake_svc)
        with proxy:
            proxy["/Dc/0/Current"] = 10.0
            clock["now"] += PUBLISH_HEARTBEAT_S
            with proxy:
                proxy["/Dc/0/Current"] = 10.05  # must stay gated mid-cycle
                assert fake_svc._ratelimiters[-1].changes == {}

    def test_heartbeat_does_not_fire_without_a_batch_context(self, clock, fake_svc):
        """Unbatched writes keep their gate however much time passes."""
        proxy = _CachedDbusProxy(fake_svc)
        proxy["/Dc/0/Current"] = 10.0
        clock["now"] += PUBLISH_HEARTBEAT_S * 10
        proxy["/Dc/0/Current"] = 10.05  # below the gate
        assert fake_svc.direct_writes == [("/Dc/0/Current", 10.0)]


class TestBatching:
    """The proxy as a context manager: one ItemsChanged per publish cycle."""

    def test_writes_inside_the_block_are_batched(self, batched_proxy, fake_svc):
        with batched_proxy:
            batched_proxy["/Soc"] = 50.0
            batched_proxy["/Soh"] = 99.0
            assert fake_svc.batches == []  # nothing emitted yet
        assert fake_svc.direct_writes == []
        assert fake_svc.batches == [{"/Soc": 50.0, "/Soh": 99.0}]

    def test_only_changed_values_reach_the_batch(self, batched_proxy, fake_svc):
        with batched_proxy:
            batched_proxy["/Soc"] = 50.0
            batched_proxy["/Dc/0/Current"] = 10.0
        with batched_proxy:
            batched_proxy["/Soc"] = 50.0  # unchanged
            batched_proxy["/Dc/0/Current"] = 10.05  # below the gate
            batched_proxy["/Soh"] = 99.0
        assert fake_svc.batches[1] == {"/Soh": 99.0}

    def test_empty_cycle_emits_nothing(self, batched_proxy, fake_svc):
        """velib's ServiceContext.flush() only signals when something changed."""
        with batched_proxy:
            batched_proxy["/Soc"] = 50.0
        with batched_proxy:
            batched_proxy["/Soc"] = 50.0
        assert fake_svc.batches == [{"/Soc": 50.0}]

    def test_writes_outside_the_block_go_out_immediately(self, batched_proxy, fake_svc):
        """publish_battery() sets /Alarms/BmsCable after publish_dbus() returns."""
        with batched_proxy:
            batched_proxy["/Soc"] = 50.0
        batched_proxy["/Alarms/BmsCable"] = 2
        assert fake_svc.direct_writes == [("/Alarms/BmsCable", 2)]
        assert fake_svc._store["/Alarms/BmsCable"] == 2

    def test_context_manager_returns_the_proxy(self, batched_proxy):
        with batched_proxy as entered:
            assert entered is batched_proxy

    def test_nested_blocks_flush_independently(self, batched_proxy, fake_svc):
        with batched_proxy:
            batched_proxy["/Soc"] = 50.0
            with batched_proxy:
                batched_proxy["/Soh"] = 99.0
            # the inner block flushed its own changes only
            assert fake_svc.batches == [{"/Soh": 99.0}]
            batched_proxy["/ErrorCode"] = 0
        assert fake_svc.batches == [{"/Soh": 99.0}, {"/Soc": 50.0, "/ErrorCode": 0}]
        assert fake_svc.direct_writes == []

    def test_batching_resumes_after_a_nested_block_exits(self, batched_proxy, fake_svc):
        """A nested exit must not strand later writes outside the outer batch."""
        with batched_proxy:
            with batched_proxy:
                batched_proxy["/Soh"] = 99.0
            batched_proxy["/Soc"] = 50.0
        assert fake_svc.direct_writes == []
        assert fake_svc.batches[-1] == {"/Soc": 50.0}

    def test_service_rate_limiter_stack_is_balanced(self, batched_proxy, fake_svc):
        with batched_proxy:
            with batched_proxy:
                pass
        assert fake_svc._ratelimiters == []

    def test_exception_inside_the_block_still_flushes_and_propagates(self, batched_proxy, fake_svc):
        with pytest.raises(ValueError):
            with batched_proxy:
                batched_proxy["/Soc"] = 50.0
                raise ValueError("boom")
        assert fake_svc.batches == [{"/Soc": 50.0}]
        assert fake_svc._ratelimiters == []
        # the proxy is reusable afterwards
        batched_proxy["/ErrorCode"] = 1
        assert fake_svc.direct_writes == [("/ErrorCode", 1)]

    def test_reads_inside_a_block_still_delegate(self, batched_proxy, fake_svc):
        fake_svc._store["/Mode"] = 3
        with batched_proxy:
            assert batched_proxy["/Mode"] == 3


class TestPublishDbusBatching:
    """DbusHelper.publish_dbus() must wrap the value writes in one batch."""

    def test_publish_dbus_batches_the_value_writes(self, fake_svc):
        proxy = _CachedDbusProxy(fake_svc)

        class Helper:
            _dbusservice = proxy

            def _publish_dbus_values(self):
                self._dbusservice["/Soc"] = 50.0
                self._dbusservice["/Soh"] = 99.0
                # nothing may have gone out on its own yet
                assert fake_svc.direct_writes == []
                assert fake_svc.batches == []

        DbusHelper.publish_dbus(Helper())

        assert fake_svc.direct_writes == []
        assert fake_svc.batches == [{"/Soc": 50.0, "/Soh": 99.0}]


class TestGetItem:
    """__getitem__: always delegates to the real service."""

    def test_read_delegates(self, proxy, mock_svc):
        mock_svc._store["/Soc"] = 42
        assert proxy["/Soc"] == 42
        mock_svc.__getitem__.assert_called_with("/Soc")

    def test_read_after_cached_write(self, proxy, mock_svc):
        proxy["/Soc"] = 55
        assert proxy["/Soc"] == 55


class TestGetAttr:
    """__getattr__: transparent delegation for methods and attributes."""

    def test_add_path_delegated(self, proxy, mock_svc):
        proxy.add_path("/Soc", 50, writeable=True)
        mock_svc.add_path.assert_called_once_with("/Soc", 50, writeable=True)

    def test_register_delegated(self, proxy, mock_svc):
        proxy.register()
        mock_svc.register.assert_called_once()

    def test_arbitrary_method(self, proxy, mock_svc):
        mock_svc.some_method.return_value = "result"
        assert proxy.some_method(1, 2, key="val") == "result"
        mock_svc.some_method.assert_called_once_with(1, 2, key="val")


class TestSentinel:
    """_SENTINEL distinguishes 'never cached' from cached None."""

    def test_sentinel_is_unique(self):
        assert _SENTINEL is not None
        assert _SENTINEL != None  # noqa: E711
        assert _SENTINEL is not False
        assert _SENTINEL != 0

    def test_first_none_write_not_suppressed(self, proxy, mock_svc):
        """If sentinel were None, the first write of None would be wrongly skipped."""
        proxy["/Path"] = None
        mock_svc.__setitem__.assert_called_once_with("/Path", None)


class TestHighWriteVolume:
    """Simulate realistic battery update cycles to verify suppression ratio."""

    def test_steady_state_suppression(self, proxy, mock_svc):
        """During steady-state charging, most values are unchanged cycle to cycle."""
        readings = {
            "/Soc": 50,
            "/Dc/0/Voltage": 13.6,
            "/Dc/0/Current": 2.1,
            "/Dc/0/Power": 28.56,
            "/Dc/0/Temperature": 25.0,
            "/System/MaxCellVoltage": 3.42,
            "/System/MinCellVoltage": 3.39,
            "/Alarms/HighVoltage": 0,
            "/Alarms/LowVoltage": 0,
            "/Alarms/HighTemperature": 0,
            "/ErrorCode": 0,
        }

        for path, val in readings.items():
            proxy[path] = val

        first_cycle_writes = mock_svc.__setitem__.call_count
        assert first_cycle_writes == len(readings)

        for _ in range(10):
            for path, val in readings.items():
                proxy[path] = val

        assert mock_svc.__setitem__.call_count == first_cycle_writes

    def test_single_value_change_per_cycle(self, proxy, mock_svc):
        """When only SoC ticks up by 1%, only that write should go through."""
        base = {"/Soc": 50, "/Dc/0/Voltage": 13.6, "/Dc/0/Current": 2.1}
        for path, val in base.items():
            proxy[path] = val

        initial = mock_svc.__setitem__.call_count

        base["/Soc"] = 51
        for path, val in base.items():
            proxy[path] = val

        assert mock_svc.__setitem__.call_count == initial + 1


class TestCgwacsSettingsCache:
    """Time-to-Go reads the ESS settings at most every CGWACS_SETTINGS_CACHE_S.

    The cache is inline in DbusHelper._publish_dbus_values(), so these tests
    drive the real method with a stub battery. That method wraps the
    Time-to-Go block in a broad ``except Exception`` which would swallow a
    stub mistake and let a test pass without ever reaching the cache, so
    every publish first asserts that the block actually ran.
    """

    # get_settings_with_values() builds absolute-path nesting and stringifies
    # every leaf; the stubs return that exact shape.
    BATTERY_LIFE = {"Settings": {"CGwacs": {"BatteryLife": {"State": "1", "MinimumSocLimit": "10.0", "SocLimit": "20.0"}}}}
    HUB4MODE = {"Settings": {"CGwacs": {"Hub4Mode": "1"}}}

    @pytest.fixture
    def clock(self, monkeypatch):
        state = {"now": 1_000_000.0}
        monkeypatch.setattr(dbushelper, "time", lambda: state["now"])
        return state

    @pytest.fixture
    def helper(self, monkeypatch, clock):
        monkeypatch.setattr(dbushelper.utils, "TIME_TO_GO_ENABLE", True)
        monkeypatch.setattr(dbushelper.utils, "TIME_TO_SOC_RECALCULATE_EVERY", 60)
        monkeypatch.setattr(dbushelper.utils, "TIME_TO_SOC_POINTS", [])
        monkeypatch.setattr(dbushelper.utils, "HISTORY_ENABLE", False)
        monkeypatch.setattr(dbushelper.utils, "PUBLISH_BATTERY_DATA_AS_JSON", False)

        # The real constructor, so the cache's starting state is whatever
        # production initialises it to, not a value supplied by this test.
        helper = DbusHelper(_stub_battery())
        # conftest stubs VeDbusService as the MagicMock class itself, so the
        # constructor's service is specced on its first argument (a str) and
        # rejects item assignment. Swap in the faithful double as the sink.
        helper._dbusservice = _CachedDbusProxy(FakeService())
        helper._dbusservice._svc._store["/Mode"] = 3
        # Periodic housekeeping in the same method writes to the settings
        # service; it is not under test here, so absorb it.
        helper.save_current_battery_state = MagicMock()
        helper.set_settings = MagicMock()

        reads = []

        def get_settings_with_values(bus, service, object_path, recursive=True):
            reads.append(object_path)
            return self.BATTERY_LIFE if object_path.endswith("/BatteryLife") else self.HUB4MODE

        helper.get_settings_with_values = get_settings_with_values
        helper.reads = reads
        return helper

    @staticmethod
    def _publish(helper, clock, advance):
        """One publish cycle, advancing past the Time-to-Go recalculation gate."""
        clock["now"] += advance
        calls_before = helper.battery.get_time_to_soc.call_count
        helper._publish_dbus_values()
        # the Time-to-Go block really ran, and did not fail silently
        assert helper.battery.get_time_to_soc.call_count == calls_before + 1
        assert 8 not in [c.args[0] for c in helper.battery.manage_error_code.call_args_list]

    def test_first_recalculation_reads_the_settings(self, helper, clock):
        self._publish(helper, clock, 60)
        assert helper.reads == ["/Settings/CGwacs/BatteryLife", "/Settings/CGwacs/Hub4Mode"]

    def test_recalculations_within_the_cache_window_do_not_reread(self, helper, clock):
        self._publish(helper, clock, 60)
        for _ in range(4):  # four more 60 s recalculations: 240 s < 300 s
            self._publish(helper, clock, 60)
        assert len(helper.reads) == 2

    def test_settings_are_reread_once_the_cache_expires(self, helper, clock):
        self._publish(helper, clock, 60)
        clock["now"] += dbushelper.CGWACS_SETTINGS_CACHE_S - 60
        self._publish(helper, clock, 60)  # exactly CGWACS_SETTINGS_CACHE_S after the first read
        assert helper.reads == ["/Settings/CGwacs/BatteryLife", "/Settings/CGwacs/Hub4Mode"] * 2

    def test_cached_settings_still_drive_time_to_go(self, helper, clock):
        """A cached read must feed the calculation exactly like a fresh one."""
        self._publish(helper, clock, 60)
        self._publish(helper, clock, 60)  # served from the cache
        soc_targets = [c.args[0] for c in helper.battery.get_time_to_soc.call_args_list]
        # Hub4Mode 1 with BatteryLife State 1 (optimised with BatteryLife) -> SocLimit
        assert soc_targets == [20, 20]
        assert len(helper.reads) == 2


def _stub_battery():
    """A battery with numeric values wherever _publish_dbus_values() does arithmetic."""
    b = MagicMock()
    b.port = "/dev/ttyUSB0"
    b.unique_identifier.return_value = "STUB0001"
    numbers = {
        "cell_count": 4,
        "soc": 80.0,
        "soc_calc": 80.0,
        "soh": 100.0,
        "voltage": 13.3,
        "current_calc": -5.0,
        "power_calc": -66.5,
        "current_avg": -5.0,
        "capacity": 100.0,
        "time_to_soc_update": 0,
        "temperature_mos": 20.0,
        "control_voltage": 14.2,
        "control_charge_current": 50.0,
        "control_discharge_current": 50.0,
        "max_battery_voltage": 14.6,
        "min_battery_voltage": 12.0,
        "state": 9,
        "online": True,
    }
    for name, value in numbers.items():
        setattr(b, name, value)
    b.cells = []
    b.current_avg_lst = []
    b.get_midvoltage.return_value = (None, None)
    b.get_time_to_soc.return_value = 3600
    for method in ("get_temperature", "get_min_temperature", "get_max_temperature"):
        getattr(b, method).return_value = 20.0
    for method in ("get_capacity_remain", "get_capacity_consumed", "get_capacity_remain_bms", "get_capacity_consumed_bms"):
        getattr(b, method).return_value = 50.0
    for method in ("get_max_cell_voltage", "get_min_cell_voltage"):
        getattr(b, method).return_value = 3.3
    return b
