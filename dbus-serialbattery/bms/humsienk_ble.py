# -*- coding: utf-8 -*-

"""HumsiENK BLE battery driver.

Read-only driver for HumsiENK BLE batteries, using the existing
utils_ble.Syncron_Ble helper for BLE I/O.

The HumsiENK BLE wire protocol — GATT service / characteristic UUIDs,
[0xAA, CMD, LEN, DATA, CHK_LO, CHK_HI] frame format, command codes,
register maps for the 0x21 / 0x20 / 0x22 / 0x58 responses, and the
operation_status bit definitions — is documented in the aiobmsble
project:

  https://github.com/patman15/aiobmsble/blob/main/docs/humsienk_bms.md
  https://github.com/patman15/aiobmsble/blob/main/aiobmsble/bms/humsienk_bms.py

The same protocol was contributed to aiobmsble in parallel with this
driver; the two implementations decode the same frames. This driver
exists for users who want a standalone driver via the serialbatteries
Syncron_Ble path while the aiobmsble integration in serialbatteries is
being worked through separately.
"""

from battery import Battery, Cell
from collections import deque
from utils import logger, capture_raw_data, USE_BMS_DVCC_VALUES
from utils_ble import BLE_ESTABLISH_TIMEOUT, BLE_RELEASE_TIMEOUT, Syncron_Ble
import asyncio
import sys
import threading
import time


class HumsiENK_Syncron_Ble(Syncron_Ble):
    """Syncron_Ble adapted to a BMS that streams notifications.

    Syncron_Ble is built for request/response BMS: it keeps a single
    response slot (response_data) that the next notification overwrites.
    The HumsiENK BMS instead streams frames continuously once the vendor
    handshake has been sent, and one logical frame regularly spans several
    notifications, so this subclass adds:

      - a notification queue, so no chunk is lost between poll cycles
      - live `connected` tracking, so the driver only writes to the
        characteristic while the link is actually up (the stock class sets
        `connected` once, in __init__, from the initial 10 s wait)
      - a data watchdog: because notifications are unsolicited, a link can
        stay "connected" while the stream is dead, and only a reconnect
        recovers it (Jkbms_Ble handles the same failure by resetting the
        BLE stack after 30 s without data)

    The connect and teardown deadlines are the ones Syncron_Ble itself uses
    (BLE_ESTABLISH_TIMEOUT / BLE_RELEASE_TIMEOUT), not local copies, so this
    override does not fork the base class's deadline policy.
    """

    # Longest silence tolerated on an established link before it is dropped
    # so the Syncron_Ble reconnect loop can rebuild it.
    WATCHDOG_TIMEOUT = 180.0

    def __init__(self, *args, **kwargs):
        self._notification_queue = deque(maxlen=256)
        self._notification_signal = threading.Condition()
        self._watchdog_last_fed = time.time()
        super().__init__(*args, **kwargs)

    def feed_watchdog(self) -> None:
        self._watchdog_last_fed = time.time()

    def get_notification(self, timeout: float = 0.0):
        """Pop the next queued notification chunk, waiting up to timeout seconds."""
        with self._notification_signal:
            if not self._notification_queue and timeout > 0:
                self._notification_signal.wait(timeout)
            if self._notification_queue:
                return self._notification_queue.popleft()
        return None

    def notify_read_callback(self, sender, data: bytearray) -> None:
        capture_raw_data(self.address, "rx", data)
        with self._notification_signal:
            self._notification_queue.append(bytes(data))
            self._notification_signal.notify_all()
        # Keep the stock request/response contract that send_data() relies on
        if self.response_event:
            self.response_data = data
            self.response_event.set()

    # How often supervision re-checks the conditions that have no callback.
    # The link drop and the data watchdog are both awaited, so this is a
    # safety net rather than a poll; it replaced a 0.1s spin that cost ten
    # timer wakeups a second per battery for the life of every connection.
    SUPERVISION_RECHECK = 5.0

    # set per connection in connect_to_bms; class defaults so a callback
    # arriving before or after one cannot fault
    _link_down = None
    _link_down_loop = None

    def client_disconnected(self, client):
        """Wake supervision as well as logging it.

        Defined here rather than relying on the base class so this driver
        does not depend on which utils_ble revision it is paired with.
        """
        super(HumsiENK_Syncron_Ble, self).client_disconnected(client)
        event, loop = self._link_down, self._link_down_loop
        if event is None or loop is None:
            return
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:
            # loop already closed; the link is over either way
            pass

    async def supervise_link(self):
        """Wait for the link to end, instead of polling for it.

        Ends on a disconnect (awaited on an event), on the data watchdog
        expiring, on the main thread going away, or on a disconnect whose
        callback never fired - the last two have no callback, so they are
        re-checked on a coarse timeout. The watchdog wakes exactly when it
        is due rather than being sampled ten times a second.
        """
        while True:
            timeout = self.SUPERVISION_RECHECK
            if self.connected:
                remaining = self.WATCHDOG_TIMEOUT - (time.time() - self._watchdog_last_fed)
                if remaining <= 0:
                    logger.error(f"HumsiENK: no data for {self.WATCHDOG_TIMEOUT:.0f} s on an open link, dropping it to reconnect")
                    return
                timeout = min(remaining, self.SUPERVISION_RECHECK)
            try:
                await asyncio.wait_for(self._link_down.wait(), timeout=timeout)
                return
            except asyncio.TimeoutError:
                pass
            if not self.main_thread.is_alive() or not self.client.is_connected:
                return

    async def connect_to_bms(self, address):
        # one event per connection: a stale set() from the previous link must
        # not end this one's supervision immediately
        self._link_down = asyncio.Event()
        self._link_down_loop = asyncio.get_running_loop()
        self.client = self.backend.create_client(address, self.client_disconnected)
        try:
            # The reconnect loop in async_main only turns while this returns, so
            # neither the connect nor the teardown may await without a bound: a
            # single stalled D-Bus call would otherwise park reconnection for good.
            self.client = await asyncio.wait_for(
                self.backend.establish(self.client, address, self.read_characteristic, self.notify_read_callback), timeout=BLE_ESTABLISH_TIMEOUT
            )
            self.feed_watchdog()
            self.connected = True
        except Exception as e:
            logger.error(f"Failed when trying to connect: {e}")
            return False
        finally:
            self.ble_connection_ready.set()
            try:
                if self.client:
                    await self.supervise_link()
            finally:
                self.connected = False
                if self.client:
                    try:
                        await asyncio.wait_for(self.backend.release(self.client), timeout=BLE_RELEASE_TIMEOUT)
                    except Exception as e:
                        logger.debug(f"HumsiENK: releasing the connection failed: {repr(e)}")


class HumsiENK_Ble(Battery):
    BATTERYTYPE = "HumsiENK BLE"

    # BLE service and characteristic UUIDs (RX/TX named from the driver's
    # perspective, not the device's)
    BLE_SERVICE_UUID = "00000001-0000-1000-8000-00805f9b34fb"
    BLE_RX_UUID = "00000003-0000-1000-8000-00805f9b34fb"  # notifications arrive here
    BLE_TX_UUID = "00000002-0000-1000-8000-00805f9b34fb"  # commands are written here

    # Protocol command codes
    CMD_HANDSHAKE = 0x00  # starts the notification stream
    CMD_STATUS = 0x20  # operating status (FETs, protections, balancing)
    CMD_BATTERY_INFO = 0x21  # voltage, current, SOC, SOH, capacity, cycles, temperatures
    CMD_CELL_VOLTAGES = 0x22  # individual cell voltages
    CMD_CONFIG = 0x58  # configuration (cell count, capacity, protection limits)
    CMD_VERSION = 0xF5  # firmware version (ASCII)

    FRAME_START = 0xAA
    MAX_FRAME_DATA_LENGTH = 200

    # Data older than this counts as a refresh failure, so the framework's
    # normal disconnect handling engages instead of the driver republishing
    # values the radio never delivered. Jkbms_Ble reports stale data on the
    # same threshold.
    DATA_FRESHNESS_SECONDS = 15.0

    # The vendor app requests all three data commands every 3 s.
    POLL_INTERVAL_SECONDS = 3.0

    # Shortest interval between handshake re-sends while the stream is starved.
    HANDSHAKE_RETRY_SECONDS = 30.0

    # How long a single request waits for its response.
    REQUEST_TIMEOUT_SECONDS = 3.0

    # Budget for the whole data phase of test_connection, from the handshake to
    # the last response. A BMS that is streaming answers a burst of commands in
    # well under a second, so anything still unanswered when this expires is not
    # coming, and the only thing more waiting achieves is keeping the D-Bus
    # service from existing - during which the rest of the bus sees the battery
    # as absent rather than as merely unresponsive.
    STARTUP_TIMEOUT_SECONDS = 10.0

    def __init__(self, port, baud, address):
        super(HumsiENK_Ble, self).__init__(port, baud, address)
        self.type = self.BATTERYTYPE
        self.address = address
        self.poll_interval = 1000
        self.ble_handle = None
        self.history.exclude_values_to_calculate = ["charge_cycles"]
        self._rx_buffer = bytearray()
        self._last_frame_time = 0.0  # last checksum-verified frame from the radio
        self._last_poll_time = 0.0
        self._last_handshake_time = 0.0
        self._deadline = None  # caps a run of requests, see _request()

        logger.info("Init of HumsiENK_Ble at " + address)

    def connection_name(self) -> str:
        return "BLE " + self.address

    def custom_name(self) -> str:
        return "SerialBattery(" + self.type + ") " + self.address[-5:]

    def unique_identifier(self) -> str:
        return self.address

    def test_connection(self):
        """
        Connect, start the notification stream and wait for real data.

        Return True if success, False for failure
        """
        result = False
        try:
            self.ble_handle = HumsiENK_Syncron_Ble(self.address, read_characteristic=self.BLE_RX_UUID, write_characteristic=self.BLE_TX_UUID)

            if not self.ble_handle.connected:
                logger.error("HumsiENK_Ble: could not connect to " + self.address)
                return False

            # One budget for the whole exchange below, so that four requests
            # against a link that is up but silent cost STARTUP_TIMEOUT_SECONDS
            # in total instead of four separate timeouts one after the other.
            self._deadline = time.time() + self.STARTUP_TIMEOUT_SECONDS

            # The BMS stays silent until the handshake is sent
            self._send_command(self.CMD_HANDSHAKE)
            self._last_handshake_time = time.time()

            # Cell voltages carry the cell count, so ask for them first
            result = self._request(self.CMD_CELL_VOLTAGES)
            result = result and self._request(self.CMD_BATTERY_INFO)
            result = result and self.get_settings()

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

        finally:
            self._deadline = None

        return result

    def get_settings(self):
        """
        Capacity, cell count and the charge/discharge limits come from the BMS
        configuration frame, the firmware version from the version frame.

        Return True if success, False for failure
        """
        result = self._request(self.CMD_CONFIG)
        self._request(self.CMD_VERSION)
        return result

    def refresh_data(self):
        """
        Read everything the BMS has streamed since the last cycle and ask for
        the next round of data.

        Return True if success, False for failure
        """
        try:
            self._read_frames()

            now = time.time()
            stale_seconds = now - self._last_frame_time

            if self.ble_handle.connected:
                # Syncron_Ble reconnects on its own, but the BMS only streams
                # after a handshake and a single re-send can be lost while the
                # BMS is still settling, so keep re-sending while starved.
                if stale_seconds > self.DATA_FRESHNESS_SECONDS and (now - self._last_handshake_time) > self.HANDSHAKE_RETRY_SECONDS:
                    # _last_frame_time is 0.0 until the first verified frame,
                    # so the age is only meaningful once one has arrived -
                    # otherwise "stale" would be measured from the epoch.
                    if self._last_frame_time > 0.0:
                        logger.info(f"HumsiENK: re-sending handshake after {stale_seconds:.0f} s without data")
                    else:
                        logger.info("HumsiENK: re-sending handshake, no data since connection")
                    self._send_command(self.CMD_HANDSHAKE)
                    self._last_handshake_time = now

                if (now - self._last_poll_time) >= self.POLL_INTERVAL_SECONDS:
                    self._last_poll_time = now
                    for command in (self.CMD_BATTERY_INFO, self.CMD_STATUS, self.CMD_CELL_VOLTAGES):
                        self._send_command(command)

        except Exception as e:
            logger.warning(f"HumsiENK: refresh_data failed: {repr(e)}")

        # Report only what the radio delivered: values are published as current
        # or not at all, never republished as if they were fresh.
        return (time.time() - self._last_frame_time) <= self.DATA_FRESHNESS_SECONDS

    def _build_command(self, command: int, data: list = None) -> bytes:
        """
        Build a command frame: [0xAA, CMD, LEN, DATA..., CHK_LO, CHK_HI]

        LEN counts the data bytes only and the checksum is the 16-bit
        little-endian sum of CMD, LEN and the data bytes.

        :param command: the command code
        :param data: the data bytes, if the command takes any
        :return: the encoded frame
        """
        data = data if data is not None else []
        frame = bytearray([self.FRAME_START, command, len(data)])
        frame.extend(data)
        checksum = sum(frame[1:]) & 0xFFFF
        frame.extend([checksum & 0xFF, checksum >> 8])
        return bytes(frame)

    def _send_command(self, command: int, data: list = None) -> None:
        """
        Write a command frame to the BMS.

        Sends fail routinely while the link is being rebuilt, so a failure is
        logged and the next poll cycle simply tries again.

        :param command: the command code
        :param data: the data bytes, if the command takes any
        :return: None
        """
        try:
            self.ble_handle.send_data(self._build_command(command, data))
        except Exception as e:
            logger.debug(f"HumsiENK: sending command 0x{command:02X} failed: {repr(e)}")

    def _request(self, command: int, timeout: float = REQUEST_TIMEOUT_SECONDS) -> bool:
        """
        Send a command and read frames until its response has been parsed.

        Waits at most `timeout` seconds and never past `self._deadline` when the
        caller has set one, so a run of requests made while the link is up but
        the BMS is silent costs the caller's budget rather than the sum of the
        individual timeouts. Once the budget is gone the command is not even
        sent: nothing is answering it.

        :param command: the command code
        :param timeout: how long to wait for the response
        :return: True if the response was parsed, False on timeout
        """
        if self._deadline is not None:
            timeout = min(timeout, self._deadline - time.time())
            if timeout <= 0:
                logger.warning(f"HumsiENK: out of time before command 0x{command:02X} could be sent")
                return False

        self._send_command(command)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if command in self._read_frames():
                return True
        logger.warning(f"HumsiENK: no response to command 0x{command:02X} within {timeout:.1f} s")
        return False

    def _read_frames(self, timeout: float = 0.3) -> list:
        """
        Drain the queued notifications and parse every complete frame in them.

        Response frames use the same layout as commands,
        [0xAA, CMD, LEN, DATA..., CHK_LO, CHK_HI], but arrive split across
        notifications, so they are reassembled in a receive buffer. A frame
        with a bad checksum or an implausible length is resynchronised past
        by dropping its start byte.

        :param timeout: how long to wait for the first notification
        :return: the command codes of the frames that were parsed
        """
        while True:
            chunk = self.ble_handle.get_notification(timeout)
            if chunk is None:
                break
            self._rx_buffer.extend(chunk)
            timeout = 0.0  # only wait for the first chunk, then drain

        commands = []
        while len(self._rx_buffer) >= 5:
            start = self._rx_buffer.find(self.FRAME_START)
            if start == -1:
                self._rx_buffer.clear()
                break
            del self._rx_buffer[:start]

            if len(self._rx_buffer) < 5:
                break

            data_length = self._rx_buffer[2]
            if data_length > self.MAX_FRAME_DATA_LENGTH:
                logger.debug(f"HumsiENK: implausible frame length {data_length}, resyncing")
                del self._rx_buffer[:1]
                continue

            total_length = 3 + data_length + 2
            if len(self._rx_buffer) < total_length:
                break

            frame = bytes(self._rx_buffer[:total_length])
            if sum(frame[1:-2]) & 0xFFFF != frame[-2] | (frame[-1] << 8):
                logger.debug("HumsiENK: checksum mismatch, resyncing")
                del self._rx_buffer[:1]
                continue

            del self._rx_buffer[:total_length]
            self._parse_and_update(frame)
            self._last_frame_time = time.time()
            # Fed only here, so the watchdog proves real data, not just a link
            self.ble_handle.feed_watchdog()
            commands.append(frame[1])

        return commands

    def _parse_and_update(self, frame: bytes) -> None:
        """
        Route a checksum-verified frame to the parser for its command.

        :param frame: the complete frame
        :return: None
        """
        command = frame[1]
        data = frame[3 : 3 + frame[2]]

        if command == self.CMD_BATTERY_INFO:
            self._parse_battery_info(data)
        elif command == self.CMD_CELL_VOLTAGES:
            self._parse_cell_voltages(data)
        elif command == self.CMD_STATUS:
            self._parse_status(data)
        elif command == self.CMD_CONFIG:
            self._parse_config(data)
        elif command == self.CMD_VERSION:
            self._parse_version(data)
        else:
            logger.debug(f"HumsiENK: ignoring response to unknown command 0x{command:02X}")

    def _parse_battery_info(self, data: bytes) -> None:
        """
        Parse the 0x21 response (26 bytes).

            voltage (4 bytes): pack voltage in mV
            current (4 bytes): current in mA, signed
            soc (1 byte): state of charge in %
            soh (1 byte): state of health in %
            capacity (4 bytes): remaining capacity in mAh
            capacity_total (4 bytes): rated capacity in mAh
            cycles (2 bytes): charge cycle count
            t1..t4, mos, environment (1 byte each): temperatures in °C, signed

        The FET states are not in this response, they come from 0x20.

        :param data: the frame payload
        :return: None
        """
        if len(data) < 26:
            logger.warning(f"HumsiENK: battery info response too short: {len(data)} bytes")
            return

        self.voltage = int.from_bytes(data[0:4], "little") / 1000
        self.current = int.from_bytes(data[4:8], "little", signed=True) / 1000
        self.soc = data[8]
        self.soh = data[9] if data[9] <= 100 else None
        self.capacity_remain = int.from_bytes(data[10:14], "little") / 1000

        capacity_total = int.from_bytes(data[14:18], "little") / 1000
        if capacity_total > 0:
            self.capacity = capacity_total

        self.history.charge_cycles = int.from_bytes(data[18:20], "little")

        # Temperatures are signed bytes; the environment sensor in data[25] has
        # no D-Bus path and is not published.
        for sensor, index in ((1, 20), (2, 21), (3, 22), (4, 23), (0, 24)):
            self.to_temperature(sensor, data[index] - 256 if data[index] > 127 else data[index])

        logger.debug(
            f"HumsiENK: {self.voltage:.2f} V, {self.current:.2f} A, {self.soc} %, "
            f"{self.capacity_remain:.1f}/{self.capacity:.1f} Ah, {self.history.charge_cycles} cycles"
        )

    def _parse_cell_voltages(self, data: bytes) -> None:
        """
        Parse the 0x22 response (up to 48 bytes).

        Up to 24 cell slots of 2 bytes each, in mV. The cells in use are
        contiguous from the start, so the first slot outside the plausible
        range marks the end of the string.

        :param data: the frame payload
        :return: None
        """
        millivolts = [int.from_bytes(data[i : i + 2], "little") for i in range(0, min(len(data), 48) - 1, 2)]

        cell_count = 0
        for millivolt in millivolts:
            if not 1000 <= millivolt <= 5000:
                break
            cell_count += 1

        if cell_count == 0:
            logger.debug("HumsiENK: cell voltage response contains no plausible cells")
            return

        if cell_count != self.cell_count:
            logger.info(f"HumsiENK: detected {cell_count} cells (was {self.cell_count})")
            self.cell_count = cell_count

        while len(self.cells) < cell_count:
            self.cells.append(Cell(False))
        del self.cells[cell_count:]

        for index in range(cell_count):
            self.cells[index].voltage = millivolts[index] / 1000

        # self.voltage is deliberately left alone: the pack voltage reported by
        # 0x21 is more accurate than the sum of the rounded cell voltages.

    def _parse_status(self, data: bytes) -> None:
        """
        Parse the 0x20 response (14 bytes).

            bytes 0-3: runtime (days: 2, hours: 1, minutes: 1), not published
            bytes 4-7: operation status flags (32 bit, see below)
            bytes 8-10: cell balancing bitmap (24 bit)
            bytes 11-13: cell disconnect bitmap (24 bit)

        Operation status flags, charge section:

            bit 0: charge overcurrent protection
            bit 1: charge over-temperature protection
            bit 2: charge under-temperature protection
            bit 3: cell overvoltage protection
            bit 4: pack overvoltage protection
            bit 5: analogue front end error
            bit 6: charging stopped
            bit 7: charge FET state (1 = on)
            bit 8: charge overcurrent warning
            bit 9: charge over-temperature warning
            bit 10: charge under-temperature warning
            bit 11: cell overvoltage warning
            bit 12: pack overvoltage warning
            bit 13: voltage difference warning
            bit 14: voltage difference too large
            bit 15: heater state (1 = on)

        Discharge section:

            bit 16: discharge overcurrent protection
            bit 17: discharge over-temperature protection
            bit 18: discharge under-temperature protection
            bit 19: cell undervoltage protection
            bit 20: short circuit protection
            bit 21: pack undervoltage protection
            bit 22: discharging stopped
            bit 23: discharge FET state (1 = on)
            bit 24: discharge overcurrent warning
            bit 25: discharge over-temperature warning
            bit 26: discharge under-temperature warning
            bit 27: cell undervoltage warning
            bit 28: pack undervoltage warning
            bit 29: MOSFET over-temperature warning
            bit 30: MOSFET over-temperature protection
            bit 31: pre-discharge FET on

        The word is four bytes of one byte each: charge protection, charge
        warning, discharge protection, discharge warning. Bit 7 of each byte is
        a switch state rather than a condition. Bits 3, 5, 6, 13, 14, 19, 27 and
        31 are documented upstream but the vendor app never reads them, so their
        labels are taken on the upstream maintainer's authority rather than
        verified here.

        :param data: the frame payload
        :return: None
        """
        if len(data) < 14:
            logger.warning(f"HumsiENK: status response too short: {len(data)} bytes")
            return

        status = int.from_bytes(data[4:8], "little")

        def alarm(protection_bit: int, warning_bit: int = None) -> int:
            """Map a protection/warning bit pair to 0 (ok), 1 (warning) or 2 (alarm)."""
            if status & (1 << protection_bit):
                return 2
            if warning_bit is not None and status & (1 << warning_bit):
                return 1
            return 0

        self.charge_fet = bool(status & (1 << 7))
        self.discharge_fet = bool(status & (1 << 23))
        # The three switch bits are a set: the vendor app labels them charging
        # switch, discharge switch and heating switch. balance_fet is left
        # unset, because whether balancing is *allowed* is not reported; the
        # per-cell bitmap below says only which cells are balancing right now.
        self.heater_fet = bool(status & (1 << 15))

        # The overvoltage WARNINGS (bits 11 and 12) are deliberately not
        # published. On these packs both assert while charging to the voltage
        # the manufacturer specifies, and hold for hours: bit 12 was set for
        # about three hours during a charge to 14.4 V, released only once the
        # pack had fallen to somewhere between 13.97 and 13.50 V, and bit 11
        # behaved the same way. A signal that asserts throughout normal, in
        # spec operation is telemetry, not an alarm, and publishing it puts a
        # warning in the VRM alarm log on every charge cycle. Aggregators take
        # the maximum across a bank, so one pack in absorption raises the whole
        # bank. The protections (bits 3 and 4) are what actually open a FET and
        # are reported in full.
        self.protection.high_voltage = 2 if status & (1 << 4) else 0
        self.protection.high_cell_voltage = 2 if status & (1 << 3) else 0

        # The undervoltage warnings are kept, because their thresholds sit
        # below the operating floor rather than inside it: nothing reaches them
        # during ordinary use, so an assertion is worth surfacing.
        self.protection.low_voltage = alarm(21, 28)
        self.protection.low_cell_voltage = alarm(19, 27)

        self.protection.cell_imbalance = alarm(14, 13)

        self.protection.high_charge_current = alarm(0, 8)
        self.protection.high_charge_temperature = alarm(1, 9)
        self.protection.low_charge_temperature = alarm(2, 10)
        self.protection.high_temperature = alarm(17, 25)
        self.protection.low_temperature = alarm(18, 26)
        self.protection.high_internal_temperature = alarm(30, 29)  # MOSFET

        # A short circuit trips the same discharge path and has no D-Bus alarm
        # of its own, so it is reported as a discharge overcurrent.
        self.protection.high_discharge_current = 2 if status & (1 << 20) else alarm(16, 24)

        balancing = int.from_bytes(data[8:11], "little")
        for index in range(min(len(self.cells), 24)):
            self.cells[index].balance = bool(balancing & (1 << index))

        # A set disconnect bit means a cell is physically disconnected, which is
        # a wiring fault rather than a battery condition. The vendor app reads
        # this field but never shows it.
        disconnected = int.from_bytes(data[11:14], "little")
        # Bit 5 is the analogue front end, the part that measures the cells. A
        # fault there means the readings themselves are untrustworthy, which is
        # the same class of problem as a disconnected cell.
        self.protection.internal_failure = 2 if (disconnected or status & (1 << 5)) else 0
        if disconnected:
            cells = [index + 1 for index in range(min(len(self.cells), 24)) if disconnected & (1 << index)]
            logger.error(f"HumsiENK: cells reported as disconnected: {cells}")

        logger.debug(f"HumsiENK: charge FET {self.charge_fet}, discharge FET {self.discharge_fet}, heater {self.heater_fet}")

    def _parse_config(self, data: bytes) -> None:
        """
        Parse the 0x58 response (44 bytes).

        22 little-endian 16-bit values: cell count, rated capacity in 0.01 Ah,
        then the protection thresholds with their recovery points and delays —
        cell overvoltage and undervoltage in mV, charge and discharge
        overcurrent in 0.1 A, and the temperature limits in deciKelvin.

        :param data: the frame payload
        :return: None
        """
        if len(data) < 44:
            logger.warning(f"HumsiENK: config response too short: {len(data)} bytes")
            return

        values = [int.from_bytes(data[i : i + 2], "little") for i in range(0, 44, 2)]
        cell_count = values[0]
        capacity = values[1] / 100
        cell_max_voltage = values[2] / 1000
        cell_min_voltage = values[5] / 1000
        max_charge_current = values[8] / 10
        max_discharge_current = values[10] / 10
        # Vendor scaling for the temperature limits: (raw - 2731) / 10 -> °C
        charge_temp_max = (values[14] - 2731) / 10
        charge_temp_min = (values[16] - 2731) / 10
        discharge_temp_max = (values[18] - 2731) / 10
        discharge_temp_min = (values[20] - 2731) / 10

        if 0 < cell_count <= 24:
            self.cell_count = cell_count
        if capacity > 0:
            self.capacity = capacity
        # get DVCC values from BMS if the user wants to use them and they are
        # available. Left unset otherwise, so the base class derives them from
        # the configured cell voltages. Opting in is worth understanding here:
        # this BMS reports its protection trip points, not charge targets, so
        # the charge voltage becomes the voltage at which the BMS opens the
        # charge FET.
        if USE_BMS_DVCC_VALUES:
            if cell_max_voltage > 0 and cell_count > 0:
                self.max_battery_voltage = round(cell_max_voltage * cell_count, 2)
            if cell_min_voltage > 0 and cell_count > 0:
                self.min_battery_voltage = round(cell_min_voltage * cell_count, 2)
            if max_charge_current > 0:
                self.max_battery_charge_current = max_charge_current
            if max_discharge_current > 0:
                self.max_battery_discharge_current = max_discharge_current

        logger.info(
            f"HumsiENK: config {cell_count}S {capacity} Ah, "
            f"cell {cell_min_voltage}-{cell_max_voltage} V, "
            f"charge {max_charge_current} A at {charge_temp_min}-{charge_temp_max} °C, "
            f"discharge {max_discharge_current} A at {discharge_temp_min}-{discharge_temp_max} °C"
        )

    def _parse_version(self, data: bytes) -> None:
        """
        Parse the 0xF5 response, an ASCII firmware version string.

        :param data: the frame payload
        :return: None
        """
        version = "".join(chr(byte) for byte in data if 32 <= byte <= 126)
        if version:
            self.hardware_version = f"HumsiENK v{version}"
            logger.info(f"HumsiENK: firmware version {version}")
        else:
            logger.warning(f"HumsiENK: could not decode the firmware version from {data.hex()}")
