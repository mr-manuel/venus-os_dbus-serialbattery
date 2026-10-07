# -*- coding: utf-8 -*-

# Notes
# Added by https://github.com/mr-manuel
# Library link: https://github.com/patman15/aiobmsble

# TODO:
# - Check what happens when the battery looses the connection
# - Check if the battery reconnects properly

# avoid importing wildcards, remove unused imports
from battery import Battery, Cell
from utils import logger, BATTERY_CAPACITY
import os
import sys

import asyncio
import concurrent.futures
import importlib
import threading
import time

# add ext folder to sys.path
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "ext"))

from bleak import BleakScanner  # noqa: E402
from bleak.backends.device import BLEDevice  # noqa: E402
from bleak.exc import BleakError  # noqa: E402
from aiobmsble import BMSInfo, BMSSample, TempSensor  # noqa: E402


# Reconnect pacing for a device the adapter cannot reach.
#
# refresh_data polls once a second, and every poll that finds no client runs a
# full establish_connection, which makes its own four BlueZ attempts before it
# raises. For a device that is powered off, removed or out of range, retrying
# on every poll cannot succeed and only costs load.
#
# Indexed by the number of consecutive failures, which is at least 1, so the
# first entry is never used: after the first failure the next attempt is
# immediate, then the waits are 5, 15, 30 and 60 seconds. A pack that slept
# through one advertising window still recovers straight away; only a
# sustained run of failures earns a long wait.
RECONNECT_BACKOFF_SECONDS = (0, 0, 5, 15, 30, 60)


class Generic_AioBmsBle(Battery):
    def __init__(self, port, baud, address):
        super(Generic_AioBmsBle, self).__init__(port, baud, address)
        # Exclude history values from calculation if they are provided from the BMS
        self.history.exclude_values_to_calculate = []

        # If the BMS could be connected over RS485/Modbus and an address can be configured
        # please use the address in your commands. This will allow multiple batteries to be connected
        # on the same USB to RS485 adapter
        self.address = address

        module_name = f"aiobmsble.bms.{port.lower()}"
        try:
            bms_module = importlib.import_module(module_name)
            BMS = getattr(bms_module, "BMS")
            self.AIOBMSBLE_CLASS = BMS
            self.BATTERYTYPE = f"{BMS.INFO['default_manufacturer']} {BMS.INFO['default_model']}"
        except (ModuleNotFoundError, AttributeError) as e:
            logger.error(f"Could not import BMS class for module '{module_name}': {e}")
            self.AIOBMSBLE_CLASS = None
            self.BATTERYTYPE = "Unknown aiobmsble BMS"

        self.type = self.BATTERYTYPE

        self.aiobmsble_info: BMSInfo | None = None
        self.aiobmsble_data: BMSSample | None = None
        # Persistent aiobmsble client instance (created once when device is found)
        self._aiobmsble = None
        self._aiobmsble_device = None
        # background event loop for running aiobmsble coroutines to avoid loop conflicts
        self._loop = None
        self._loop_thread = None
        self._loop_ready = None
        # prevent scheduling multiple concurrent aiobmsble coroutines
        self._coro_lock = threading.Lock()
        # timeouts (seconds)
        self._run_timeout: int = 10
        # The first connection races a BMS that may be advertising sparsely:
        # establish_connection waits for the device's next connectable
        # advertisement, and a JBD module idling between app sessions can sit
        # on a multi-second interval. 10 s loses that race; the initial
        # attempt gets a budget that wins it.
        self._initial_connect_timeout: int = 40
        self._grace_timeout: int = 2
        self._cancel_timeout: int = 1
        # track the currently scheduled Future on the background loop
        self._current_future = None
        # background-update bookkeeping: whether we hold _coro_lock on behalf
        # of an in-flight refresh, and when it was scheduled
        self._update_lock_held = False
        self._update_started_at: float | None = None
        # staleness tracking
        self._last_successful_update: float | None = None
        self._max_data_age: int = 5  # seconds before stale cached data causes failure
        # the stale-data warning would fire on every poll while the BMS is away;
        # log it when a stale spell starts, then at most this often
        self._stale_warning_interval: int = 60
        self._stale_warned_at: float = 0.0
        # reconnect pacing: consecutive failed connects, when the next attempt
        # is allowed, and whether the sustained-failure warning has been logged
        self._connect_failures: int = 0
        self._reconnect_hold_until: float = 0.0
        self._reconnect_warned: bool = False

    BATTERYTYPE = "Generic aiobmsble BMS"

    def connection_name(self) -> str:
        return "aiobmsble " + self.address

    def custom_name(self) -> str:
        return "" + self.BATTERYTYPE + " (" + self.address[-5:] + ")"

    def product_name(self) -> str:
        return "SerialBattery(" + self.BATTERYTYPE + ")"

    async def _aiobmsble_connect(self, bms):
        # Try common connect method names, fallback to async context manager enter
        logger.debug("aiobmsble: attempting connect for %s", getattr(self, "address", "unknown"))
        for name in ("connect", "async_connect", "connect_async"):
            method = getattr(bms, name, None)
            if callable(method):
                logger.debug("aiobmsble: calling %s()", name)
                await method()
                logger.debug("aiobmsble: connected using %s", name)
                return

        aenter = getattr(bms, "__aenter__", None)
        if callable(aenter):
            logger.debug("aiobmsble: using __aenter__ to open connection")
            await aenter()
            logger.debug("aiobmsble: connected via context manager")

    async def _aiobmsble_disconnect(self, bms):
        # Try common disconnect/close method names, fallback to async context manager exit
        for name in ("disconnect", "async_disconnect", "disconnect_async", "close", "aclose"):
            method = getattr(bms, name, None)
            if callable(method):
                logger.debug("aiobmsble: calling %s() to disconnect", name)
                await method()
                logger.debug("aiobmsble: disconnected using %s", name)
                return

        aexit = getattr(bms, "__aexit__", None)
        if callable(aexit):
            logger.debug("aiobmsble: using __aexit__ to close connection")
            await aexit(None, None, None)
            logger.debug("aiobmsble: disconnected via context manager")

    def _reconnect_on_hold(self) -> bool:
        """True while the next connect attempt is still being paced out."""
        return time.monotonic() < self._reconnect_hold_until

    def _note_connect_failure(self, reason: str) -> None:
        """Record a failed connect and pace the next attempt.

        Emits exactly ONE warning per outage, when the ladder reaches its
        longest step, so a long outage cannot flood the log.
        """
        self._connect_failures += 1
        delay = RECONNECT_BACKOFF_SECONDS[min(self._connect_failures, len(RECONNECT_BACKOFF_SECONDS) - 1)]
        self._reconnect_hold_until = time.monotonic() + delay
        if delay == RECONNECT_BACKOFF_SECONDS[-1] and not self._reconnect_warned:
            self._reconnect_warned = True
            logger.warning(
                "aiobmsble: %s unreachable after %d attempts (%s); retrying every %ds until it returns",
                self.address,
                self._connect_failures,
                reason,
                delay,
            )
        else:
            logger.debug("aiobmsble: connect failed for %s (%s), next attempt in %ds", self.address, reason, delay)

    def _note_connect_success(self) -> None:
        """Clear the pacing state so the next outage starts from the top."""
        if self._reconnect_warned:
            logger.warning("aiobmsble: %s reachable again after %d failed attempts", self.address, self._connect_failures)
        self._connect_failures = 0
        self._reconnect_hold_until = 0.0
        self._reconnect_warned = False

    async def _resolve_device(self) -> BLEDevice | None:
        """BLEDevice for this address from the BlueZ cache, scanning as fallback.

        A sleeping BMS can advertise too sparsely for an active scan window
        to catch, while a connect to its cached device object still works -
        BlueZ's create-connection waits for the next connectable
        advertisement instead of needing a scan report. The scan remains the
        fallback for a device BlueZ has never seen.
        """
        try:
            from bleak_retry_connector import get_device
        except ImportError:
            get_device = None
        if get_device is not None:
            try:
                device = await get_device(self.address)
            except Exception as e:
                logger.debug("BlueZ cache lookup failed for %s: %r", self.address, e)
                device = None
            if device is not None:
                logger.debug("aiobmsble: %s resolved from BlueZ cache", self.address)
                return device
        return await BleakScanner.find_device_by_address(self.address)

    def _ensure_aiobmsble(self, device: BLEDevice):
        # Instantiate the aiobmsble client once, keep for reuse
        if self._aiobmsble is None:
            try:
                self._aiobmsble = self.AIOBMSBLE_CLASS(ble_device=device)
                self._aiobmsble_device = device
                logger.debug("aiobmsble: instantiated client for %s", getattr(self, "address", "unknown"))
            except Exception as e:
                logger.error("Failed to instantiate aiobmsble client: %s", e)
                self._aiobmsble = None
                self._aiobmsble_device = None

    def _ensure_event_loop(self):
        if self._loop is not None:
            return

        logger.debug("aiobmsble: creating background event loop")
        self._loop = asyncio.new_event_loop()
        self._loop_ready = threading.Event()

        def _run_loop():
            asyncio.set_event_loop(self._loop)
            # signal that loop is ready to accept coroutines
            try:
                self._loop_ready.set()
            except Exception:
                pass
            self._loop.run_forever()

        self._loop_thread = threading.Thread(target=_run_loop, daemon=True)
        self._loop_thread.start()

        # wait briefly until loop thread signals readiness
        if not self._loop_ready.wait(timeout=1.0):
            logger.warning("aiobmsble: background event loop did not signal readiness in time")
        else:
            logger.debug("aiobmsble: background event loop ready")

    def _poll_update(self, coro):
        """Harvest a finished background update and start the next one.

        NEVER waits on the BMS. refresh_data runs on the GLib main thread,
        which is also the thread that answers D-Bus, so blocking here for a
        coroutine timeout stops the driver serving anything at all - the
        battery's own service stops answering /Soc, /Connected and
        /Mgmt/Connection while remaining registered. An unreachable pack
        blocked the main thread for the whole coroutine timeout on every poll.

        Returns True only when an update completed successfully since the
        last poll; the caller's staleness logic decides what to serve.
        """
        self._ensure_event_loop()
        completed_ok = False

        future = self._current_future
        if future is not None and future.done():
            self._current_future = None
            self._update_started_at = None
            try:
                completed_ok = bool(future.result(0))
            except concurrent.futures.CancelledError:
                pass
            except Exception as e:
                # show the first failure of an outage; the pacing reports a long
                # one once, so the rest stay at debug
                if self._connect_failures <= 1:
                    logger.warning("aiobmsble: background update failed (addr=%s): %r", self.address, e)
                else:
                    logger.debug("aiobmsble: background update failed (addr=%s): %r", self.address, e)
            self._release_update_lock()
        elif future is not None and self._update_started_at is not None:
            # a coroutine that never returns must not wedge every later poll
            if time.monotonic() - self._update_started_at > self._run_timeout:
                logger.error("aiobmsble coroutine timed out for %s (addr=%s)", getattr(coro, "__name__", repr(coro)), self.address)
                try:
                    future.cancel()
                except Exception:
                    pass
                # A hang is a failed attempt. Count it here, on this thread and
                # before the next attempt is scheduled below, so the pacing
                # already applies to that attempt; counted inside the cancelled
                # coroutine it can land after the next attempt has started.
                self._note_connect_failure("timed out")
                self._current_future = None
                self._update_started_at = None
                self._release_update_lock()

        if self._current_future is None:
            # non-blocking: if something else holds the loop, skip this poll
            if self._coro_lock.acquire(blocking=False):
                self._update_lock_held = True
                try:
                    self._current_future = asyncio.run_coroutine_threadsafe(coro(), self._loop)
                    self._update_started_at = time.monotonic()
                except Exception as e:
                    logger.debug("aiobmsble: could not schedule update (addr=%s): %r", self.address, e)
                    self._release_update_lock()

        return completed_ok

    def _release_update_lock(self):
        if self._update_lock_held:
            self._update_lock_held = False
            try:
                self._coro_lock.release()
            except RuntimeError:
                pass

    def _run_coro(self, coro, timeout: float | None = None):
        try:
            if timeout is None:
                timeout = self._run_timeout

            self._ensure_event_loop()
            # ensure loop is ready
            if self._loop_ready is not None and not self._loop_ready.is_set():
                # small wait
                self._loop_ready.wait(timeout=0.5)
            logger.debug("aiobmsble: scheduling coroutine %s (addr=%s)", getattr(coro, "__name__", repr(coro)), getattr(self, "address", "unknown"))

            # try to acquire the coroutine lock to avoid overlapping calls
            acquired = False
            try:
                acquired = self._coro_lock.acquire(timeout=min(1.0, timeout))
                if not acquired:
                    logger.warning("aiobmsble: busy, another coroutine is running (addr=%s)", getattr(self, "address", "unknown"))
                    return None
                # if a callable (async function) was passed, call it now to create the coroutine
                coro_obj = coro() if callable(coro) else coro

                future = asyncio.run_coroutine_threadsafe(coro_obj, self._loop)
                # keep reference to currently running future so disconnect can cancel it
                self._current_future = future
                try:
                    return future.result(timeout)
                except concurrent.futures.TimeoutError:
                    name = getattr(coro_obj, "__name__", repr(coro_obj))
                    logger.error("aiobmsble coroutine timed out for %s (addr=%s)", name, getattr(self, "address", "unknown"))
                    try:
                        future.cancel()
                    except Exception:
                        pass
                    return None
                except Exception:
                    # re-raise to be caught by outer except
                    raise
                finally:
                    # clear current future
                    try:
                        self._current_future = None
                    except Exception:
                        pass
            finally:
                if acquired:
                    try:
                        self._coro_lock.release()
                    except Exception:
                        pass
        except concurrent.futures.TimeoutError:
            logger.error("aiobmsble coroutine outer timeout (addr=%s)", getattr(self, "address", "unknown"))
            return None
        except Exception as e:
            logger.exception("aiobmsble coroutine raised exception: %s", e)
            return None

    def disconnect(self):
        """
        Disconnect from the battery
        """
        logger.info(">>> Cleanly disconnecting from aiobmsble battery %s to prevent BLE adapter issues", getattr(self, "address", "unknown"))

        async def run_async():
            if self._aiobmsble is not None:
                try:
                    await self._aiobmsble_disconnect(self._aiobmsble)
                except Exception as ex:
                    logger.error("Failed to disconnect BMS: %s", type(ex).__name__)

        try:
            # ensure background loop exists
            self._ensure_event_loop()

            # If there is a current future running, try to let it finish gracefully
            if self._current_future is not None:
                try:
                    logger.debug("aiobmsble: waiting grace timeout for current future (addr=%s)", getattr(self, "address", "unknown"))
                    try:
                        self._current_future.result(timeout=self._grace_timeout)
                        logger.debug("aiobmsble: current future finished within grace timeout")
                    except concurrent.futures.TimeoutError:
                        logger.warning("aiobmsble: current task didn't finish in %ss, cancelling", self._grace_timeout)
                        try:
                            self._current_future.cancel()
                        except Exception:
                            pass
                        try:
                            self._current_future.result(timeout=self._cancel_timeout)
                            logger.debug("aiobmsble: current future cancelled cleanly")
                        except concurrent.futures.TimeoutError:
                            logger.warning("aiobmsble: cancel didn't finish in %ss", self._cancel_timeout)
                except Exception:
                    logger.exception("aiobmsble: exception while waiting/cancelling current future")

            # schedule disconnect directly on the background loop (bypass lock)
            try:
                coro_obj = run_async()
                fut = asyncio.run_coroutine_threadsafe(coro_obj, self._loop)
                try:
                    fut.result(timeout=self._run_timeout)
                except concurrent.futures.TimeoutError:
                    logger.warning("aiobmsble: disconnect didn't finish in %ss, cancelling (addr=%s)", self._run_timeout, getattr(self, "address", "unknown"))
                    try:
                        fut.cancel()
                    except Exception:
                        pass
            except Exception as ex:
                logger.exception("aiobmsble: exception during disconnect scheduling: %s", ex)

            # drop client reference
            self._aiobmsble = None
            self._aiobmsble_device = None

            # stop the background loop thread if it exists
            if self._loop is not None:
                try:
                    self._loop.call_soon_threadsafe(self._loop.stop)
                except Exception:
                    pass

                if self._loop_thread is not None:
                    try:
                        self._loop_thread.join(timeout=1.0)
                    except Exception:
                        pass

                try:
                    # close loop after thread stopped
                    self._loop.close()
                except Exception:
                    pass

                self._loop = None
                self._loop_thread = None
                if self._loop_ready is not None:
                    try:
                        self._loop_ready.clear()
                    except Exception:
                        pass
                    self._loop_ready = None

        except Exception:
            (
                exception_type,
                exception_object,
                exception_traceback,
            ) = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")

    def __del__(self):
        """
        Ensure we disconnect and shut down the background loop when the object is garbage-collected.
        """
        try:
            # Best-effort: call disconnect (it is defensive and tolerates shutdown)
            logger.info("Disconnected form __del__")
            self.disconnect()
        except Exception:
            pass

    def test_connection(self):
        """
        call a function that will connect to the battery, send a command and retrieve the result.
        The result or call should be unique to this BMS. Battery name or version, etc.
        Return True if success, False for failure
        """
        result = False

        async def run_async():
            device: BLEDevice | None = await self._resolve_device()

            if device is None:
                logger.error(f'Battery "{self.BATTERYTYPE}" with MAC "{self.address}" not found. Is it powered on and in range?')
                return False
            else:
                logger.debug(f'Battery "{self.BATTERYTYPE}" with MAC "{self.address}" found')

            # instantiate client once and keep it for later refreshes
            self._ensure_aiobmsble(device)
            if self._aiobmsble is None:
                return False

            try:
                # connect if client exposes a connect method or context manager
                await self._aiobmsble_connect(self._aiobmsble)

                logger.debug("Updating BMS data...")

                info = getattr(self._aiobmsble, "device_info", None)
                update = getattr(self._aiobmsble, "async_update", None)

                if callable(info):
                    self.aiobmsble_info = await info()

                if callable(update):
                    self.aiobmsble_data = await update()

                logger.debug("BMS info: %s", repr(dict(sorted(self.aiobmsble_info.items())) if self.aiobmsble_info else self.aiobmsble_info))
                logger.debug("BMS data: %s", repr(dict(sorted(self.aiobmsble_data.items())) if self.aiobmsble_data else self.aiobmsble_data))

                if self.aiobmsble_data:
                    # keep connection open for subsequent refreshes
                    return True
                else:
                    # failed to get data, disconnect
                    await self._aiobmsble_disconnect(self._aiobmsble)
                    return False

            except BleakError as ex:
                logger.error("Failed to update BMS: %s", type(ex).__name__)
                try:
                    await self._aiobmsble_disconnect(self._aiobmsble)
                except Exception:
                    pass
                return False

        try:
            result = self._run_coro(run_async, timeout=self._initial_connect_timeout)
            if result:
                # The startup reading is real, fresh data, so start the data-age
                # clock on it. refresh_data below only schedules the first
                # background update; if the clock waited for that update, a
                # battery that went away now would have this reading published
                # as current for as long as it stayed away.
                self._last_successful_update = time.monotonic()

            # get settings to check if the data is valid and the connection is working
            result = result and self.get_settings()

            # get the rest of the data to be sure, that all data is valid and the correct battery type is recognized
            # only read next data if the first one was successful, this saves time when checking multiple battery types
            result = result and self.refresh_data()
        except Exception:
            (
                exception_type,
                exception_object,
                exception_traceback,
            ) = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
            result = False

        if not result:
            # disconnect on failure
            try:
                self.disconnect()
            except Exception:
                pass

        return result

    def unique_identifier(self) -> str:
        """
        Used to identify a BMS when multiple BMS are connected
        Provide a unique identifier from the BMS to identify a BMS, if multiple same BMS are connected
        e.g. the serial number
        If there is no such value, please remove this function
        """
        return self.address.replace(":", "").lower()

    def get_settings(self):
        """
        After successful connection get_settings() will be called to set up the battery
        Set all values that only need to be set once
        Return True if success, False for failure
        """

        # MANDATORY values to set
        # does not need to be in this function, but has to be set at least once
        # could also be read in a function that is called from refresh_data()
        #
        # if not available from battery, then add a section in the `config.default.ini`
        # under ; --------- BMS specific settings ---------
        # number of connected cells (int)
        self.cell_count = self.aiobmsble_data["cell_count"]

        # capacity of the battery in ampere hours (float)
        self.capacity = self.aiobmsble_data.get("design_capacity", BATTERY_CAPACITY)

        # OPTIONAL values to set
        # does not need to be in this function
        # could also be read in a function that is called from refresh_data()

        # maximum charge current in amps (float)
        # self.max_battery_charge_current = VALUE_FROM_BMS

        # maximum discharge current in amps (float)
        # self.max_battery_discharge_current = VALUE_FROM_BMS

        # custom field, that the user can set in the BMS software (str)
        # self.custom_field = VALUE_FROM_BMS

        # maximum voltage of the battery in V (float)
        # self.max_battery_voltage_bms = VALUE_FROM_BMS

        # minimum voltage of the battery in V (float)
        # self.min_battery_voltage_bms = VALUE_FROM_BMS

        # production date of the battery (str)
        # self.production = VALUE_FROM_BMS

        # hardware version of the BMS (str)
        self.hardware_version = self.aiobmsble_info.get("hw_version", None) if self.aiobmsble_info else None

        # serial number of the battery (str)
        self.serial_number = self.aiobmsble_info.get("serial_number", None) if self.aiobmsble_info else None

        # init the cell array once
        if len(self.cells) == 0:
            for _ in range(self.cell_count):
                self.cells.append(Cell(False))

        return True

    def refresh_data(self):
        """
        call all functions that will refresh the battery data.
        This will be called for every iteration (1 second)
        Return True if success, False for failure
        """

        # Try to (re)fetch data from the stored aiobmsble client if available
        async def _update_async():
            # Pace an unreachable device rather than hammering it, on both
            # paths below: finding and connecting it here, and the client's own
            # reconnect inside async_update once a client exists. Every attempt
            # costs a full establish_connection of four BlueZ attempts, and for
            # a device that is not there none of them can win.
            if self._reconnect_on_hold():
                return False
            # ensure we have a client, try to find device and connect if not
            if self._aiobmsble is None:
                # Cache-first, like test_connection: a bare
                # find_device_by_address here starts a fresh BlueZ discovery on
                # EVERY poll of a battery whose client was lost, which on a GX
                # device with another service already scanning fails outright
                # with org.bluez.Error.InProgress - and then blocks the caller
                # for the whole coroutine timeout while it does. Resolving from
                # the BlueZ cache costs no scan at all in the common case.
                try:
                    device: BLEDevice | None = await self._resolve_device()
                except Exception as ex:
                    # a scan can fail outright, e.g. org.bluez.Error.InProgress
                    # while another service scans the adapter; count it, or the
                    # pacing never engages. (A hang is counted by _poll_update.)
                    self._note_connect_failure(repr(ex))
                    raise
                if device is None:
                    self._note_connect_failure("device not found")
                    logger.debug(f"Could not find device {self.address} for refresh")
                    return False
                self._ensure_aiobmsble(device)
                if self._aiobmsble is None:
                    self._note_connect_failure("no aiobmsble client")
                    return False
                try:
                    await self._aiobmsble_connect(self._aiobmsble)
                except Exception as ex:
                    self._note_connect_failure(repr(ex))
                    raise
                self._note_connect_success()

            update = getattr(self._aiobmsble, "async_update", None)
            if callable(update):
                try:
                    self.aiobmsble_data = await update()
                    self._note_connect_success()
                    return True
                except Exception as ex:
                    # the client reconnects inside async_update, so this is the
                    # failure path of a lost connection: count it for the pacing
                    self._note_connect_failure(repr(ex))
                    logger.error("Failed to refresh BMS data: %s", ex)
                    try:
                        await self._aiobmsble_disconnect(self._aiobmsble)
                    except Exception:
                        pass
                    # Drop the client. It is bound to the device object it was
                    # built from, and that object names the adapter it was
                    # found on. If that adapter has gone, the client can never
                    # reconnect, even with the battery in range of another
                    # adapter. The next attempt resolves the device afresh and
                    # builds a new client on whichever adapter has it now.
                    self._aiobmsble = None
                    self._aiobmsble_device = None
                    return False
            return False

        try:
            # perform an async update (keeps connection open on success)
            ok = self._poll_update(_update_async)
            if ok:
                self._last_successful_update = time.monotonic()
            elif self._last_successful_update is not None:
                data_age = time.monotonic() - self._last_successful_update
                if data_age > self._max_data_age:
                    # Warn when a stale spell starts - no warning since the last
                    # good data - and then once a minute; the growing age in the
                    # message shows the spell continuing.
                    now = time.monotonic()
                    if self._stale_warned_at < self._last_successful_update or now - self._stale_warned_at >= self._stale_warning_interval:
                        self._stale_warned_at = now
                        logger.warning(
                            "aiobmsble: cached data is %ds old, treating as failure (addr=%s)",
                            int(data_age),
                            self.address,
                        )
                    return False
                logger.debug("aiobmsble: using cached data (%.1fs old) (addr=%s)", data_age, self.address)
            elif not isinstance(self.aiobmsble_data, dict):
                return False

            # Integrate a check to be sure, that the received data is from the BMS type you are making this driver for

            # MANDATORY values to set
            # voltage of the battery in volts (float)
            self.voltage = self.aiobmsble_data["voltage"]

            # current of the battery in amps (float)
            self.current = self.aiobmsble_data["current"]

            # state of charge in percent (float)
            self.soc = self.aiobmsble_data["battery_level"]

            # temperature sensors
            # MOSFET temperature always goes to sensor slot 0, all other sensor
            # types are assigned to the remaining slots 1-4 in the order provided
            temp_values = self.aiobmsble_data.get("temp_values", [])
            other_slot = 1
            ignored_temps = []
            for sensor in temp_values:
                if sensor is None:
                    continue
                sensor_type = getattr(sensor, "type", TempSensor.T.GENERIC)
                temperature = float(sensor)
                if sensor_type == TempSensor.T.MOSFET:
                    self.to_temperature(0, temperature)
                elif other_slot <= 4:
                    self.to_temperature(other_slot, temperature)
                    other_slot += 1
                else:
                    ignored_temps.append(temperature)

                logger.debug(f'Battery "{self.BATTERYTYPE}" with MAC "{self.address}" temperature sensor {sensor_type.name}: {temperature} °C')

            if ignored_temps:
                logger.warning(
                    f'Battery "{self.BATTERYTYPE}" with MAC "{self.address}" provided {len(ignored_temps)} more temperature '
                    f"value(s) than the supported 4 slots; ignoring the extra reading(s): {ignored_temps} °C"
                )

            # cell voltages in volts (list of float)
            cell_voltages = self.aiobmsble_data.get("cell_voltages", [])
            for idx in range(min(self.cell_count, len(cell_voltages))):
                self.cells[idx].voltage = cell_voltages[idx]

            # show which cells are balancing
            self.balancing = self.aiobmsble_data.get("balancer", None)
            if self.balancing is not None and self.get_min_cell() is not None and self.get_max_cell() is not None:
                for c in range(self.cell_count):
                    if self.balancing and (self.get_min_cell() == c or self.get_max_cell() == c):
                        self.cells[c].balance = True
                    else:
                        self.cells[c].balance = False

            # status of the battery if charging is allowed (bool)
            self.charge_fet = self.aiobmsble_data.get("chrg_mosfet", True)

            # status of the battery if discharging is allowed (bool)
            self.discharge_fet = self.aiobmsble_data.get("dischrg_mosfet", True)

            # OPTIONAL values to set

            # remaining capacity of the battery in ampere hours (float)
            # if not available, then it's calculated from the SOC and the capacity
            capacity_remain = self.aiobmsble_data.get("cycle_charge", None)
            if capacity_remain is not None:
                self.capacity_remain = capacity_remain

            # state of health in percent (float)
            self.soh = self.aiobmsble_data.get("battery_health", None)

            # status of the battery if balancing is allowed (bool)
            # self.balance_fet = VALUE_FROM_BMS

            # status if heating is allowed (bool)
            # self.heater_fet = VALUE_FROM_BMS

            # status if the heater is currently on (bool)
            heating = self.aiobmsble_data.get("heater", None)
            self.heating = 1 if heating is True else 0 if heating is False else None

            # heater current in amps (float)
            # self.heater_current = VALUE_FROM_BMS

            # heater power in watts (float)
            # self.heater_power = VALUE_FROM_BMS

            # heater temperature start in °C (float)
            # self.heater_temperature_start = VALUE_FROM_BMS

            # heater temperature stop in °C (float)
            # self.heater_temperature_stop = VALUE_FROM_BMS

            # PROTECTION values
            # 2 = alarm, 1 = warningm 0 = ok
            # high battery voltage alarm (int)
            # self.protection.high_voltage = VALUE_FROM_BMS

            # high cell voltage alarm (int)
            # self.protection.high_cell_voltage = VALUE_FROM_BMS

            # low battery voltage alarm (int)
            # self.protection.low_voltage = VALUE_FROM_BMS

            # low cell voltage alarm (int)
            # self.protection.low_cell_voltage = VALUE_FROM_BMS

            # low SOC alarm (int)
            # self.protection.low_soc = VALUE_FROM_BMS

            # high charge current alarm (int)
            # self.protection.high_charge_current = VALUE_FROM_BMS

            # high discharge current alarm (int)
            # self.protection.high_discharge_current = VALUE_FROM_BMS

            # cell imbalance alarm (int)
            # self.protection.cell_imbalance = VALUE_FROM_BMS

            # internal failure alarm (int)
            # TODO: Check what values are send here
            # self.protection.internal_failure = self.aiobmsble_data.get("problem", None)

            # high charge temperature alarm (int)
            # self.protection.high_charge_temperature = VALUE_FROM_BMS

            # low charge temperature alarm (int)
            # self.protection.low_charge_temperature = VALUE_FROM_BMS

            # high temperature alarm (int)
            # self.protection.high_temperature = VALUE_FROM_BMS

            # low temperature alarm (int)
            # self.protection.low_temperature = VALUE_FROM_BMS

            # high internal temperature alarm (int)
            # self.protection.high_internal_temperature = VALUE_FROM_BMS

            # fuse blown alarm (int)
            # self.protection.fuse_blown = VALUE_FROM_BMS

            # HISTORY values
            # Deepest discharge in Ampere hours (float)
            # self.history.deepest_discharge = VALUE_FROM_BMS

            # Last discharge in Ampere hours (float)
            # self.history.last_discharge = VALUE_FROM_BMS

            # Average discharge in Ampere hours (float)
            # self.history.average_discharge = VALUE_FROM_BMS

            # Number of charge cycles (int)
            history_charge_cycles = self.aiobmsble_data.get("cycles", None)
            if history_charge_cycles is not None:
                self.history.charge_cycles = history_charge_cycles

            # Number of full discharges (int)
            # self.history.full_discharges = VALUE_FROM_BMS

            # Total Ah drawn (lifetime) (float)
            history_total_ah_drawn = self.aiobmsble_data.get("total_charge", None)
            if history_total_ah_drawn is not None:
                self.history.total_ah_drawn = history_total_ah_drawn

            # Minimum voltage in Volts (lifetime) (float)
            # self.history.minimum_voltage = VALUE_FROM_BMS

            # Maximum voltage in Volts (lifetime) (float)
            # self.history.maximum_voltage = VALUE_FROM_BMS

            # Minimum cell voltage in Volts (lifetime) (float)
            # self.history.minimum_cell_voltage = VALUE_FROM_BMS

            # Maximum cell voltage in Volts (lifetime) (float)
            # self.history.maximum_cell_voltage = VALUE_FROM_BMS

            # Time since last full charge in seconds (int)
            # self.history.timestamp_last_full_charge = VALUE_FROM_BMS

            # Number of low voltage alarms (int)
            # self.history.low_voltage_alarms = VALUE_FROM_BMS

            # Number of high voltage alarms (int)
            # self.history.high_voltage_alarms = VALUE_FROM_BMS

            # Minimum temperature in Celsius (lifetime)
            # self.history.minimum_temperature = VALUE_FROM_BMS

            # Maximum temperature in Celsius (lifetime)
            # self.history.maximum_temperature = VALUE_FROM_BMS

            # Discharged energy in kilo Watt hours (int)
            # self.history.discharged_energy = VALUE_FROM_BMS

            # Charged energy in kilo Watt hours (int)
            # self.history.charged_energy = VALUE_FROM_BMS

            # logger.info(self.hardware_version)
            return True

        except Exception:
            (
                exception_type,
                exception_object,
                exception_traceback,
            ) = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logger.error(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
            return False
