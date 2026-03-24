# JKBMS PB RS485 — Performance & Integration Notes

## Hardware

- BMS: JKBMS PB series, firmware >= v15.36
- RS485 adapter: factory-supplied JKBMS comm adapter (CH341-based USB-serial)
- Host: Victron Cerbo GX (armv7l), Venus OS v3.70

## CH341 Adapter Issues

The CH341 is a half-duplex USB-serial chip with two known quirks:

1. **TX echo**: transmitted bytes appear in the RX buffer. Fixed by
   scanning for the `0x55 0xAA` response header via `data.find()` rather
   than assuming it starts at offset 0.

2. **Stale FIFO**: the chip's internal buffer retains bytes across port
   open/close. On a multi-battery RS485 bus, residual bytes from the
   previous battery's response leak into the next battery's read. Fixed
   by a 20ms settle + `reset_input_buffer()` drain before the first
   command after opening the port.

Both issues are specific to the CH341 in half-duplex RS485 mode and would
not occur with a proper RS485 transceiver with separate TX/RX control.

## Protocol Timing (per battery, measured)

| Phase | Duration | Notes |
|-------|----------|-------|
| Serial port open | 15–50ms | USB device enumeration |
| Wake-up write + flush | 75ms | `command_settings` write-only, fixed sleep |
| Status read | 35–50ms | `command_status`, 299 bytes at 115200 baud |
| Serial port close | 3–15ms | |
| **Total serial** | **~130–160ms** | |
| Calculations | 2–5ms | `set_calculated_data`, charge management |
| D-Bus publish | 3–30ms | typical, with EMA cache hits |
| **Total per battery** | **~150–200ms** | |

## Maximum Battery Count

At 1s poll interval, the budget for serial I/O is ~1000ms minus framework
overhead (~100ms GLib scheduling + dbus housekeeping).

| Poll interval | Serial budget | Max batteries (theoretical) | Practical limit |
|---------------|--------------|----------------------------|-----------------|
| 1.0s | ~900ms | 6 (900/150) | 4–5 |
| 1.5s | ~1400ms | 9 | 6–7 |
| 2.0s | ~1900ms | 12 | 8–10 |

Practical limits are lower because:
- Fail-fast retry on missed response adds ~250ms per failure
- D-Bus reentrancy spikes (see below) consume unpredictable time
- GLib main loop scheduling jitter on the Cerbo's ARM CPU

With 4 batteries the measured total poll cycle is ~700–800ms, well within
the 1s interval.

## D-Bus Performance

Venus OS uses D-Bus (via dbus-python + GLib) for inter-process
communication. Each battery publishes ~100 properties per cycle. Two
mitigations are in place:

1. **`_CachedDbusProxy`**: suppresses writes when the value has not
   changed. Combined with the EMA cell voltage filter, this reduces
   actual D-Bus writes from ~100 to ~3–10 per battery per cycle.

2. **`last_refresh_duration` decoupling**: the poll interval auto-increase
   logic uses only the serial+calc time, not the full runtime. This
   prevents D-Bus overhead from silently degrading the poll rate.

### Reentrancy problem (unresolved)

The dbus-serialbattery process runs a single-threaded GLib main loop that
handles both outgoing property updates and incoming `GetValue`/`GetText`
requests from other Venus OS services (GUI, VRM portal, system-calc).

During the ~500ms serial read phase, incoming requests queue up. When
`publish_dbus()` touches D-Bus objects, dbus-python processes the queued
requests reentrantly, causing occasional 1–2s stalls. This is a
dbus-python/GLib architectural limitation. Approaches tried:

- **Deferred signal emission** (`GLib.idle_add`): idle callbacks run
  inline due to GLib main loop reentrancy — no improvement.
- **GLib context pumping** (`ctx.iteration`): processes events during the
  poll measurement window — makes timing worse.
- **Threaded signal writer**: signal emission itself is fast (~1–3ms);
  the blocking is in dbus-python's internal request dispatch, not in
  signal sending.
- **Threaded `refresh_data`** with GLib pumping: GLib reentrancy causes
  recursive callback dispatch — unstable.

The current mitigation (decoupled poll interval) prevents the stalls from
affecting data rate. A full fix would require replacing dbus-python with
an async D-Bus library (e.g. `dasbus`, `sdbus`) or restructuring the
driver into separate serial and D-Bus processes.
