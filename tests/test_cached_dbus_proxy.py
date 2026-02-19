"""Tests for _CachedDbusProxy in dbushelper.py.

Platform-specific modules (dbus, velib_python) are stubbed via conftest.py
so these tests run on macOS, CI, and Linux alike.
"""

import pytest
from unittest.mock import MagicMock

from dbushelper import _CachedDbusProxy, _SENTINEL


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
        assert _SENTINEL is not 0

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
