# JKBMS PB RS485 — Wire Protocol Reference

This document describes the RS485 protocols used by JKBMS PB series BMS
units.  Based on the official JKBMS RS485 Modbus V1.0/V1.1 spec,
reverse-engineered driver code, and protocol-level testing on a
4-battery system (protocol-level testing on a real bus).

## Hardware

- BMS: JKBMS PB series (tested with firmware V15.x and V19.x)
- RS485 adapter: factory-supplied JKBMS comm adapter (CH341-based USB-serial)
- Bus: multi-drop RS485, half-duplex, 115200 baud, 8N1
- Addressing: each BMS has a DIP-switch configurable address (0x01–0xFF);
  address 0x00 configures the BMS as bus master

## Two Protocols on One Bus

The JKBMS PB supports **two distinct protocols** on the same RS485 bus:

1. **Standard Modbus RTU** — official, documented in "极空BMS RS485
   Modbus通用协议 V1.0/V1.1". Standard FC 0x03 / FC 0x10 against the
   register map below; big-endian.
2. **The bus master protocol** — proprietary FC 0x10 "trigger" writes
   that elicit a 300-byte `0x55 0xAA` response. Used by:
   - the BMS-resident bus master (the BMS at DIP-switch address 0x00),
   - JKBMS Monitor (vendor PC software),
   - this driver (`dbus-serialbattery`) — a software client that
     implements a **subset** of the bus master protocol.

### Protocol 1: Standard Modbus RTU

Standard Modbus RTU framing with FC 0x03 (Read Holding Registers) and
FC 0x10 (Write Multiple Registers).  Big-endian register values per
Modbus spec.

**FC 0x03 read request:**

    [ ADDR (1) ] [ 0x03 ] [ START_REG (2) ] [ REG_COUNT (2) ] [ CRC (2) ]

Total: 8 bytes.

**FC 0x03 response:**

    [ ADDR (1) ] [ 0x03 ] [ BYTE_COUNT (1) ] [ DATA (N) ] [ CRC (2) ]

**Properties** (tested external host, no bus master present):
- ✅ Address filtering works — only the addressed BMS responds
- ✅ CRC is checked — corrupted CRC gets no response
- ✅ No cross-talk — unaddressed BMS units stay silent
- ⚠️ Max register count per read appears limited (~40 works, 128 fails)

**Register base addresses** (Modbus register addresses, not byte offsets):

| Base     | Content                        | Access |
|----------|--------------------------------|--------|
| 0x1000   | Settings/configuration         | RW     |
| 0x1200   | Status/telemetry (live data)   | R      |
| 0x1400   | Device info (version, serial)  | R      |
| 0x1600   | Calibration/control            | W      |

**Verified FC 0x03 reads** (test D):
- `01 03 1200 000A crc` → response `01 03 14 0d0d 0d0e 0d0d...` —
  10 status registers (cell voltages in mV, big-endian)
- `01 03 1400 000A crc` → response `01 03 14 4a4b5f504232...` —
  10 about registers ("JK_PB2A16S20P...15A")
- `04 03 1200 000A crc` → response from addr 0x04, cells=[3341,3341,...]
  (correct address filtering confirmed)

#### Why this driver does not use Protocol 1

Extended testing with the FC 0x03 probe scripts in `test/` (commit
`257d198`) found Protocol 1 unsuitable for a polling
driver:

- **Cold-bus knock-out.** After a few seconds without FC 0x10 traffic
  on the bus, slaves stop responding to FC 0x03 entirely. The first
  FC 0x03 read on a quiescent bus essentially always fails; subsequent
  reads continue to fail until an FC 0x10 trigger is sent. The slaves
  appear to gate FC 0x03 service on recent bus-master activity.
- **~50 % fail rate even when "warm".** Once primed with FC 0x10,
  sustained FC 0x03 polling still drops roughly half of all reads with
  no response, across all four batteries.
- **No reliable way to keep the bus warm** with FC 0x03 alone — the
  warmup test (`jkbms_pb_fc03_warmup.py`) shows that only FC 0x10
  triggers reliably revive the slaves; FC 0x03, serial breaks, and
  short-burst FC 0x10 sequences do not sustain responsiveness.

In other words, a Protocol-1-only driver would have to interleave
Protocol 2 FC 0x10 triggers as keepalives anyway. Given that, there is
no advantage to switching, so this driver stays on Protocol 2.

### Protocol 2: Bus Master Protocol

The proprietary trigger/response protocol that the BMS-resident bus
master uses to poll the other batteries.  This driver implements the
same protocol as a software client, but exercises only a subset of it.

#### Wire format (used by every master)

**Request** — Modbus FC 0x10 (Write Multiple Registers) directed at one
specific battery address:

    [ ADDR (1) ] [ COMMAND (8) ] [ CRC (2) ]                    = 11 bytes

The 8-byte command body is a Modbus FC 0x10 write to a register in the
0x1600 area (function code + register address + register count + byte
count + data).

**Response** — proprietary 0x55AA payload followed by a standard FC 0x10
ACK from the addressed slave:

    [ TX echo (0-11) ] [ 0x55AA payload (300) ] [ 0x00 ] [ FC10 ACK (8) ] [ 0x00 ]

After the `0x55 0xAA` header the slave emits **310 bytes**:
- Payload: 300 bytes starting with `55 AA EB 90`, little-endian data
- Padding: 1 byte, always `0x00`
- FC10 ACK: 8 bytes, standard Modbus FC 0x10 ACK with valid CRC
- Trailing: 1 byte, always `0x00`

The `0x55 0xAA` header is found by scanning (variable offset 0–11 due
to CH341 TX echo).  `0xEB 0x90` at bytes 2–3 is a constant frame
marker present in all responses.  Byte 299 is a sum-8 checksum
(`sum(bytes[0:299]) & 0xFF`).

**Offset 4–5** is a *frame type* identifier, NOT the responding battery
address.  The 0x55AA payload contains **no battery address field at
all**.  Frame types observed:

| Frame type | Meaning  | Trigger register |
|------------|----------|------------------|
| 0x0001     | settings | 0x161E           |
| 0x0002     | status   | 0x1620           |
| 0x0003     | about    | 0x161C           |

All four batteries (three slaves at addr 1–3 plus the bus master at
addr 0) return the same frame-type bytes for the same trigger.

**Critical for any master implementation:** all 310 bytes after the
0x55AA header must be consumed before the next command, or the trailing
ACK + padding will appear as stale leading bytes on the next response.

#### Trigger commands

| Command (8-byte body)        | Register | Frame type | Used by BMS bus master | Used by JKBMS Monitor | Used by this driver |
|------------------------------|----------|------------|------------------------|-----------------------|---------------------|
| `10 16 20 00 01 02 00 00`    | 0x1620   | 0x0002 status   | yes (every cycle) | yes (steady-state poll) | **yes** |
| `10 16 1e 00 01 02 00 00`    | 0x161E   | 0x0001 settings | yes (every cycle) | yes (init only)         | **yes** |
| `10 16 1c 00 01 02 00 00`    | 0x161C   | 0x0003 about    | **no** (never observed in 60s of capture) | yes (init only) | **yes** (startup only) |

The "about" trigger appears unique to *external* clients: the BMS bus
master never reads it, but both JKBMS Monitor and this driver do.

#### Behaviour exclusive to the BMS-resident bus master

Captured with three active batteries at addr 1–3 plus the
master at addr 0.  None of these behaviours are required to talk to a
slave — they are how the BMS at addr 0 chooses to drive the bus.

**Fixed cycle (~4400 ms):**

| Phase | Duration | Description |
|-------|----------|-------------|
| Active poll: each active battery | ~260 ms | 0x1620 req→ACK, then 0x161E req→ACK |
| Discovery scan: addr 4–15        | ~2640 ms | 0x1620 only, 220 ms timeout each |
| Master self-broadcast            | ~440 ms  | own status (ftype=2) + settings (ftype=1) as 0x55AA frames in the addr-15 → addr-1 gap, **without a preceding request** |
| **Total**                        | **~4400 ms** | fixed period |

Per-battery: FC 0x10 request → ACK in ~38 ms; ~180 ms gap between ACK
and next request.

**Discovery scan:** the master probes addresses 4–15 every cycle with
0x1620; non-existent addresses simply time out.  Settings (0x161E) is
never scanned, only status.

**Self-broadcast:** in the addr-15 → addr-1 gap (~660 ms) the master
transmits its own status and settings as 0x55AA frames *with no
preceding request*.  These appear once per cycle.

**Continuous bus utilisation (~70 %, ~8 KB/s):** the line is driven
even during scan timeouts where no slave responds.  Decoding at
alternative baud rates (9600–460800) yields zero valid frames — the
continuous activity is not UART data at any standard rate.  Source
unknown.

#### Behaviour specific to this driver

`dbus-serialbattery` does not need to mimic the master cycle; it just
needs single, reliable request/response transactions.

- Polling cadence is set by the dbus-serialbattery framework, not the
  master's fixed 4.4 s cycle. We poll status (0x1620) per active address
  on each cycle, and settings (0x161E) on driver startup / configuration
  events.
- "About" (0x161C) is read once at startup and cached. The BMS bus
  master never reads it.
- We send single commands separated by `COMMAND_GAP` (default 100 ms,
  configurable). With ≥100 ms gap, address filtering is reliable on
  every adapter we have tested. Sub-50 ms bursts produced cross-talk in
  early tests (see "Bus Behaviour" below).
- Because the 0x55AA payload contains no responder address, we
  **validate the responder via the address byte of the trailing FC 0x10
  ACK** (CRC-checked). The BMS bus master appears to skip this check.
- We do not perform discovery scans — battery addresses come from
  configuration (`BATTERY_ADDRESSES`).
- We do not self-broadcast.

#### Reference: JKBMS Monitor software

The vendor's PC tool implements the same protocol as a third class of
master.  Init sequence captured:

1. About (0x161C) × 2, then Settings (0x161E) × 2, ~160 ms apart
2. Steady-state: Status (0x1620) every ~800 ms

About response (ftype=0x0003) returns device ID `JK_PB2A16S20P`,
firmware `15.41`.

#### Request→response sequence (slave's perspective)

Identical regardless of which master sent the request:

    Master TX: [ ADDR ] [ 10 16 20 00 01 02 00 00 ] [ CRC ]    (11 bytes)
    Slave  TX: [ 0x55AA payload (300) ] [ 0x00 ] [ FC10 ACK (8) ] [ 0x00 ]
                                                                 (310 bytes total)

The slave emits the 0x55AA payload first, then the FC 0x10 ACK; a master
that uses the ACK as a delimiter (as the BMS does) gets free framing.

## Official Register Map (from JKBMS RS485 Modbus V1.0/V1.1)

All registers are 16-bit Modbus registers.  Multi-byte values span 2
registers (4 bytes).  In FC 0x03 responses, values are **big-endian**
(standard Modbus).  In proprietary 0x55AA responses, they are
**little-endian**.

### Settings Registers (base 0x1000, RW)

| Offset | Hex    | Type   | Unit  | Field                           |
|--------|--------|--------|-------|---------------------------------|
| 0      | 0x0000 | UINT32 | mV    | VolSmartSleep                   |
| 4      | 0x0004 | UINT32 | mV    | VolCellUV (cell undervoltage)   |
| 8      | 0x0008 | UINT32 | mV    | VolCellUVPR (UV recovery)       |
| 12     | 0x000C | UINT32 | mV    | VolCellOV (cell overvoltage)    |
| 16     | 0x0010 | UINT32 | mV    | VolCellOVPR (OV recovery)       |
| 20     | 0x0014 | UINT32 | mV    | VolBalanTrig (balance trigger)   |
| 24     | 0x0018 | UINT32 | mV    | VolSOC100% (SOC full voltage)   |
| 28     | 0x001C | UINT32 | mV    | VolSOC0% (SOC empty voltage)    |
| 32     | 0x0020 | UINT32 | mV    | VolCellRCV (charge voltage) ¹   |
| 36     | 0x0024 | UINT32 | mV    | VolCellRFV (float voltage) ¹    |
| 40     | 0x0028 | UINT32 | mV    | VolSysPwrOff (auto shutdown)    |
| 44     | 0x002C | UINT32 | mA    | CurBatCOC (charge current limit)|
| 48     | 0x0030 | UINT32 | s     | TIMBatCOCPDly (charge OCP delay)|
| 52     | 0x0034 | UINT32 | s     | TIMBatCOCPRDly (charge OCP recovery)|
| 56     | 0x0038 | UINT32 | mA    | CurBatDcOC (discharge current)  |
| 60     | 0x003C | UINT32 | s     | TIMBatDcOCPDly                  |
| 64     | 0x0040 | UINT32 | s     | TIMBatDcOCPRDly                 |
| 68     | 0x0044 | UINT32 | s     | TIMBatSCPRDly (SCP recovery)    |
| 72     | 0x0048 | UINT32 | mA    | CurBalanMax (max balance current)|
| 76     | 0x004C | INT32  | 0.1°C | TMPBatCOT (charge overtemp)     |
| 80     | 0x0050 | INT32  | 0.1°C | TMPBatCOTPR                     |
| 84     | 0x0054 | INT32  | 0.1°C | TMPBatDcOT (discharge overtemp) |
| 88     | 0x0058 | INT32  | 0.1°C | TMPBatDcOTPR                    |
| 92     | 0x005C | INT32  | 0.1°C | TMPBatCUT (charge undertemp)    |
| 96     | 0x0060 | INT32  | 0.1°C | TMPBatCUTPR                     |
| 100    | 0x0064 | INT32  | 0.1°C | TMPMosOT (MOS overtemp)         |
| 104    | 0x0068 | INT32  | 0.1°C | TMPMosOTPR                      |
| 108    | 0x006C | UINT32 | —     | CellCount                       |
| 112    | 0x0070 | UINT32 | —     | BatChargeEN (1=on)              |
| 116    | 0x0074 | UINT32 | —     | BatDisChargeEN (1=on)           |
| 120    | 0x0078 | UINT32 | —     | BalanEN (1=on)                  |
| 124    | 0x007C | UINT32 | mAh   | CapBatCell (design capacity)    |
| 128    | 0x0080 | UINT32 | µs    | SCPDelay                        |
| 132    | 0x0084 | UINT32 | mV    | VolStartBalan                   |
| 136–260| 0x0088–0x0104 | UINT32 | µΩ | CellConWireRes0–31 (wire resistance) |
| 264    | 0x0108 | UINT32 | —     | DevAddr (device address)        |
| 268    | 0x010C | UINT32 | s     | TIMProdischarge                 |
| 276    | 0x0114 | UINT16 | —     | Control bitmask (see below)     |
| 278    | 0x0116 | INT8×2 | °C    | TMPBatOTA / TMPBatOTAR          |
| 280    | 0x0118 | UINT8×2| —     | TIMSmartSleep (hours) / data ctrl |

¹ V1.1 adds VolCellRCV (0x0020) and VolCellRFV (0x0024); V1.0 has
  VolSysPwrOff at 0x0028 instead.

**Control bitmask** (offset 276 / register 0x0114):

| Bit | Function                              |
|-----|---------------------------------------|
| 0   | HeatEN (heating enabled)              |
| 1   | Disable temp-sensor                   |
| 2   | GPS Heartbeat                         |
| 3   | Port Switch (1=RS485, 0=CAN)          |
| 4   | LCD Always On                         |
| 5   | Special Charger                       |
| 6   | SmartSleep                            |
| 7   | DisablePCLModule (V1.1 only)          |
| 8   | TimedStoredData (V1.1 only)           |
| 9   | ChargingFloatMode (V1.1 only)         |

### Status Registers (base 0x1200, R)

| Offset | Hex    | Type   | Unit  | Field                           |
|--------|--------|--------|-------|---------------------------------|
| 0–62   | 0x0000–0x003E | UINT16 | mV | CellVol0–31                |
| 64     | 0x0040 | UINT32 | bit   | CellSta (cell presence bitmask) |
| 68     | 0x0044 | UINT16 | mV    | CellVolAve (average)            |
| 70     | 0x0046 | UINT16 | mV    | CellVdifMax (max delta)         |
| 72     | 0x0048 | UINT8×2| —     | MaxVolCellNbr / MinVolCellNbr   |
| 74–136 | 0x004A–0x0088 | UINT16 | mΩ | CellWireRes0–31            |
| 138    | 0x008A | INT16  | 0.1°C | TempMos                         |
| 140    | 0x008C | UINT32 | bit   | CellWireResSta                  |
| 144    | 0x0090 | UINT32 | mV    | BatVol (pack voltage)           |
| 148    | 0x0094 | UINT32 | mW    | BatWatt (pack power)            |
| 152    | 0x0098 | INT32  | mA    | BatCurrent (signed)             |
| 156    | 0x009C | INT16  | 0.1°C | TempBat1                        |
| 158    | 0x009E | INT16  | 0.1°C | TempBat2                        |
| 160    | 0x00A0 | UINT32 | bit   | Alarm bitmask (see below)       |
| 164    | 0x00A4 | INT16  | mA    | BalanCurrent                    |
| 166    | 0x00A6 | UINT8×2| —     | BalanSta (2=discharge,1=charge,0=off) / SOC (%) |
| 168    | 0x00A8 | INT32  | mAh   | SOCCapRemain                    |
| 172    | 0x00AC | UINT32 | mAh   | SOCFullChargeCap                |
| 176    | 0x00B0 | UINT32 | —     | SOCCycleCount                   |
| 180    | 0x00B4 | UINT32 | mAh   | SOCCycleCap                     |
| 184    | 0x00B8 | UINT8×2| —     | SOCSOH (%) / Precharge (1=on)   |
| 188    | 0x00BC | UINT32 | s     | RunTime                         |
| 192    | 0x00C0 | UINT8×2| —     | Charge (1=on) / Discharge (1=on)|
| 208    | 0x00D0 | UINT8×2| bit   | TempSensor presence / Heating   |
| 228    | 0x00E4 | UINT16 | 0.01V | BatVol (alternate)              |
| 230    | 0x00E6 | INT16  | mA    | HeatCurrent                     |
| 248    | 0x00F8 | INT16  | 0.1°C | TempBat3                        |
| 250    | 0x00FA | INT16  | 0.1°C | TempBat4                        |
| 252    | 0x00FC | INT16  | 0.1°C | TempBat5                        |

**Alarm bitmask** (offset 160 / register 0x00A0, UINT32):

| Bit  | Alarm                          |
|------|--------------------------------|
| 0    | AlarmWireRes (wire resistance)  |
| 1    | AlarmMosOTP                    |
| 2    | AlarmCellQuantity              |
| 3    | AlarmCurSensorErr              |
| 4    | AlarmCellOVP                   |
| 5    | AlarmBatOVP                    |
| 6    | AlarmChOCP (charge overcurrent)|
| 7    | AlarmChSCP (charge short-circuit)|
| 8    | AlarmChOTP (charge overtemp)   |
| 9    | AlarmChUTP (charge undertemp)  |
| 10   | AlarmCPUAuxCommuErr            |
| 11   | AlarmCellUVP                   |
| 12   | AlarmBatUVP                    |
| 13   | AlarmDchOCP                    |
| 14   | AlarmDchSCP                    |
| 15   | AlarmDchOTP                    |
| 16   | AlarmChargeMOS                 |
| 17   | AlarmDischargeMOS              |
| 18   | GPSDisconnected                |
| 19   | Modify PWD in time             |
| 20   | Discharge On Failed            |
| 21   | Battery Over Temp Alarm        |
| 22   | Temperature sensor anomaly (V1.1)|
| 23   | PLCModule anomaly (V1.1)       |

**Temperature sensor presence** (offset 208, first UINT8):

| Bit | Sensor                    |
|-----|---------------------------|
| 0   | MOS TempSensorAbsent      |
| 1   | BATTempSensor1Absent      |
| 2   | BATTempSensor2Absent      |
| 3   | BATTempSensor3Absent (V1.1)|
| 4   | BATTempSensor4Absent      |
| 5   | BATTempSensor5Absent      |

(1 = sensor present/normal, 0 = absent)

### Device Info Registers (base 0x1400, R)

| Offset | Hex    | Type   | Field                    |
|--------|--------|--------|--------------------------|
| 0      | 0x0000 | ASCII  | ManufacturerDeviceID (16 chars) |
| 16     | 0x0010 | ASCII  | HardwareVersion (8 chars)|
| 24     | 0x0018 | ASCII  | SoftwareVersion (8 chars)|
| 32     | 0x0020 | UINT32 | ODDRunTime (seconds)     |
| 36     | 0x0024 | UINT32 | PWROnTimes               |

### Calibration/Control Registers (base 0x1600, W)

| Offset | Type   | Field                    |
|--------|--------|--------------------------|
| 0      | UINT16 | VoltageCalibration (mV)  |
| 4      | UINT16 | Shutdown                 |
| 6      | UINT16 | CurrentCalibration (mA)  |
| 10     | UINT16 | LI-ION preset            |
| 12     | UINT16 | LIFEPO4 preset           |
| 14     | UINT16 | LTO preset               |
| 16     | UINT16 | Emergency start          |
| 18     | UINT32 | Timecalibration          |

## Proprietary 0x55AA Response Mapping

The proprietary responses use **different byte offsets** from the official
register map because they include a proprietary header and frame metadata.
All offsets below are from the `0x55 0xAA` header.  Values are
**little-endian** (opposite of standard Modbus).

**Offset rule:** For both status and settings responses, the 0x55AA
payload offset = official register byte offset + 6 (accounting for the
4-byte header `55 AA EB 90` + 2-byte frame type).  This means the
official register maps above can be used directly by adding 6 to each
byte offset.

### Status (trigger 0x1620) — verified field map

Cross-validated against 3 batteries (addr 1–3) with known physical state:
16S LiFePO4, 280 Ah design capacity, indoor ~20°C, idle/no load.
Captured.

**Confidence levels:**
- **V** = Verified by cross-battery comparison and physical plausibility
- **D** = Matches driver code (may not be independently verified)
- **?** = Unidentified; values observed but purpose unknown

| Offset | Size | Type    | Conf | Field / Interpretation |
|--------|------|---------|------|------------------------|
| 0–1    | 2    | —       | V | Magic header `0x55 0xAA` |
| 2–3    | 2    | —       | V | Frame marker `0xEB 0x90` (constant) |
| 4–5    | 2    | uint16  | V | Frame type: 0x0002=status, 0x0001=settings. **Not** the battery address. |
| 6+2n   | 2    | uint16  | V | Cell voltage [n] in mV (n=0..15 for 16S). ÷1000 for volts. |
| 38–69  | 32   | —       | V | Unused cell slots 17–32 (all zeros on 16S) |
| 70–73  | 4    | uint32  | V | Cell presence bitmask (0x0000FFFF for 16S) |
| 74–75  | 2    | uint16  | V | Max cell voltage (mV) |
| 76–77  | 2    | uint16  | V | Cell voltage delta (mV) |
| 78     | 1    | uint8   | ?  | Cell index field (meaning unclear) |
| 79     | 1    | uint8   | ?  | Cell index field (meaning unclear) |
| 80+2n  | 2    | uint16  | V | Wire resistance [n] in mΩ (n=0..15) |
| 112–143| 32   | —       | V | All zeros (unused wire resistance slots 17–32) |
| 144–145| 2    | int16   | V | TempMos: raw ÷ 10 = °C. See temperature encoding below. |
| 146–149| 4    | uint32  | D | Wire resistance status (0 = all ok) |
| 150–153| 4    | uint32  | V | Pack voltage in mV. ÷1000 for volts. |
| 154–157| 4    | uint32  | V | Pack power in mW (0 at idle) |
| 158–161| 4    | int32   | V | Pack current in mA (signed). ÷1000 for amps. |
| 162–163| 2    | int16   | V | TempBat1: raw ÷ 10 = °C |
| 164–165| 2    | int16   | V | TempBat2: raw ÷ 10 = °C |
| 166–169| 4    | uint32  | V | Alarm bitmask (same bits as status register 0x00A0) |
| 170–171| 2    | int16   | D | Balance current in mA |
| 172    | 1    | uint8   | D | Balance state (0=off, 1=charge, 2=discharge) |
| 173    | 1    | uint8   | V | SOC in %. Verified: 55% × 280 Ah = 154 Ah ≈ remaining cap. |
| 174–177| 4    | int32   | V | Remaining capacity in mAh. ÷1000 for Ah. |
| 178–181| 4    | uint32  | V | Design capacity in mAh (280000 = 280 Ah, matches config) |
| 182–185| 4    | uint32  | V | Charge cycle count (differs per battery: 57, 61, 62) |
| 186–189| 4    | uint32  | V | Cumulative cycle capacity in mAh. ≈ cycles × capacity. |
| 190    | 1    | uint8   | V | SOH in % (100 for all batteries) |
| 191    | 1    | uint8   | D | Precharge state |
| 194–197| 4    | uint32  | V | Total runtime in seconds (562–624 days, per battery) |
| 198    | 1    | uint8   | V | Charge FET state (1=on, same across batteries at idle) |
| 199    | 1    | uint8   | V | Discharge FET state (1=on) |
| 214    | 1    | uint8   | V | Temp sensor presence bitmask (0xFF = all present) |
| 215    | 1    | uint8   | D | Heating active (0/1) |
| 236–237| 2    | uint16  | D | Heater current in mA. ÷1000 for amps. |
| 254–255| 2    | int16   | V | Temperature — identical to [144] (MOS temp duplicate) |
| 256–257| 2    | int16   | V | TempBat3: raw ÷ 10 = °C. Driver reads at this offset. |
| 258–259| 2    | int16   | V | TempBat4: raw ÷ 10 = °C. Driver reads at this offset. |
| 286–297| 12   | —       | V | Constant footer (identical across all 4 batteries) |
| 298    | 1    | uint8   | ?  | Last per-battery field (varies between batteries) |
| 299    | 1    | uint8   | V | 8-bit checksum: `sum(bytes[0:299]) & 0xFF` |

**Unidentified offsets** (non-zero, vary between batteries):
192–193, 216–217, 220–221, 226–229, 234–235, 238–243, 246–249,
260–267, 270–273, 276–277, 298.

### Temperature encoding

The driver reads temperatures as `int16` (signed, little-endian) and
divides by 10 to get degrees Celsius:

```python
raw = unpack_from("<h", data, offset)[0] / 10
if raw < 99:
    temp_c = raw          # normal: 199 → 19.9°C
else:
    temp_c = 100 - raw    # negative: 1050 → 105.0 → 100-105 = -5°C
```

Observed values at ~20°C ambient: raw=187–207, giving 18.7–20.7°C.

### Settings (trigger 0x161E) — verified field map

Settings payload starts at offset 6 (after the 4-byte header + 2-byte
frame type).  Each field is a 32-bit little-endian value.  Offsets 6–138
map sequentially to the 0x1000 register map (offset 6 in the 0x55AA
frame = register offset 0 in the settings map).

Verified against 3 batteries (all identical settings):

| Offset | Register field  | Observed value | Interpretation |
|--------|-----------------|----------------|----------------|
| 6      | VolSmartSleep   | 3500           | 3.500 V |
| 10     | VolCellUV       | 2700           | 2.700 V |
| 14     | VolCellUVPR     | 2901           | 2.901 V |
| 18     | VolCellOV       | 3650           | 3.650 V |
| 22     | VolCellOVPR     | 3444           | 3.444 V |
| 26     | VolBalanTrig    | 5              | 5 mV |
| 30     | VolSOC100%      | 3445           | 3.445 V |
| 34     | VolSOC0%        | 2900           | 2.900 V |
| 38     | VolCellRCV      | 3450           | 3.450 V |
| 42     | VolCellRFV      | 3350           | 3.350 V |
| 46     | VolSysPwrOff    | 2500           | 2.500 V |
| 50     | CurBatCOC       | 60000          | 60 A |
| 54     | TIMBatCOCPDly   | 3              | 3 s |
| 58     | TIMBatCOCPRDly  | 60             | 60 s |
| 62     | CurBatDcOC      | 100000         | 100 A |
| 66     | TIMBatDcOCPDly  | 300            | 300 s |
| 70     | TIMBatDcOCPRDly | 60             | 60 s |
| 74     | TIMBatSCPRDly   | 5              | 5 s |
| 78     | CurBalanMax     | 2000           | 2 A |
| 82     | TMPBatCOT       | 350            | 35.0 °C |
| 86     | TMPBatCOTPR     | 320            | 32.0 °C |
| 90     | TMPBatDcOT      | 350            | 35.0 °C |
| 94     | TMPBatDcOTPR    | 320            | 32.0 °C |
| 98     | TMPBatCUT       | 50             | 5.0 °C |
| 102    | TMPBatCUTPR     | 70             | 7.0 °C |
| 106    | TMPMosOT        | 800            | 80.0 °C |
| 110    | TMPMosOTPR      | 700            | 70.0 °C |
| 114    | CellCount       | 16             | |
| 118    | BatChargeEN     | 1              | enabled |
| 122    | BatDisChargeEN  | 1              | enabled |
| 126    | BalanEN         | 1              | enabled |
| 130    | CapBatCell      | 280000         | 280 Ah |
| 134    | SCPDelay        | 1500           | 1500 µs |
| 138    | VolStartBalan   | 3440           | 3.440 V |

Offsets 142–269 contain wire resistance calibration values
(CellConWireRes0–31, 32 × 4 bytes = 128 bytes).

Higher offsets (derived from official register map, offset = register + 6):

| Offset | Register field  | Type   | Interpretation |
|--------|-----------------|--------|----------------|
| 270    | DevAddr         | uint32 | Device address (DIP switch) |
| 274    | TIMProdischarge | uint32 | Pre-discharge time (s) |
| 282    | Control bitmask | uint16 | See control bitmask table above |
| 284    | TMPBatOTA       | int8   | Heating start temp (°C) |
| 285    | TMPBatOTAR      | int8   | Heating stop temp (°C) |
| 286    | TIMSmartSleep   | uint8  | Smart sleep hours |

### About (trigger 0x161C) — driver offsets

Not used by the BMS bus master.  Observed in JKBMS Monitor init
sequence : ftype=0x0003, 300-byte payload (310 bytes total
on wire including padding + ACK), checksum at byte 299.
Device ID and firmware version confirmed readable.  Field offsets below
are from the driver source.

| Offset | Size | Type   | Field                    |
|--------|------|--------|--------------------------|
| 6      | 16   | ASCII  | ManufacturerDeviceID     |
| 22     | 8    | ASCII  | HardwareVersion          |
| 30     | 8    | ASCII  | SoftwareVersion          |
| 38     | 4    | uint32 | ODDRunTime (seconds)     |
| 42     | 4    | uint32 | PWROnTimes               |
| 46     | 16   | ASCII  | Serial number            |
| 102    | 16   | ASCII  | User data 1              |
| 118    | 16   | ASCII  | PIN                      |
| 134    | 16   | ASCII  | User data 2              |

## Bus Behaviour

### Address Filtering and Cross-Talk

**Summary:** Address filtering works correctly in all controlled tests.
Cross-talk observed in early driver tests  was an artifact
of the test methodology (rapid command bursts), not a Protocol 2
limitation.  Confirmed by JKBMS Monitor test with the same adapter.

**Protocol 1 (FC 0x03):** No cross-talk.  Standard Modbus address
filtering.  Tested on an external host, CH341 adapter.

**Protocol 2 (FC 0x10 trigger / 0x55AA), JKBMS Monitor as master:** No
cross-talk. Tested with the official JKBMS Monitor on a
laptop polling battery addr 3 via FC 0x10 write to reg 0x1620, using
the **same CH341 adapter** previously used in the cross-talk tests.
Only battery 3 responded; zero responses from batteries 1, 2, 4.
Verified over 15 seconds (18 cycles at ~800 ms interval).

**Protocol 2, BMS bus master:** No cross-talk. Verified over 60 seconds
/ 14 full cycles .

**Earlier cross-talk observation :** During driver
development tests using a CH341 adapter, all BMS units appeared to
respond to every FC 0x10 trigger regardless of the address byte. This
was originally attributed to a missing address filter in the bus master
protocol. However, the JKBMS Monitor test  using the
**identical adapter hardware** shows correct address filtering. The
cross-talk was caused by the test software sending rapid command bursts
(two commands within ~50 ms), not by the protocol or the adapter.
Single commands with ≥100 ms gap produce clean, addressed responses.

The bus is completely silent during passive listening when no master
is present (verified: 5 rounds × 5 seconds = zero bytes).

### Why the Driver Uses Protocol 2

Protocol 2 is what the BMS-resident bus master uses, so the slaves are
designed and tuned around it. In practice that means:

- Address filtering works correctly when single commands are sent at
  reasonable intervals (≥100 ms gap between commands).
- The 0x55AA payload does NOT contain the responding BMS's address
  (offset 4–5 is a frame type, not an address). The FC 0x10 ACK that
  follows the payload does contain the correct battery address and is
  used for responder verification by the driver.
- The slaves stay responsive as long as FC 0x10 traffic continues —
  unlike with FC 0x03, where the slaves drop off the bus without
  FC 0x10 priming (see "Why this driver does not use Protocol 1"
  above).

## Checksums

### Modbus CRC-16 (both protocols)

Standard Modbus CRC-16 (polynomial 0xA001), used on all Modbus RTU
frames (FC 0x03, FC 0x10 requests, FC 0x10 ACKs):
```
crc = 0xFFFF
for each byte b in message:
    crc ^= b
    repeat 8 times:
        if crc & 1:  crc = (crc >> 1) ^ 0xA001
        else:        crc >>= 1
result = crc as 2 bytes, little-endian
```

Verified by recomputing CRC for all 54 captured Modbus frames (10s
capture) — all match.

Protocol 1 verifies CRC.  The BMS bus master uses valid CRC in both
directions.  CRC verification of single Protocol 2 commands by the slave
side was not independently tested — earlier driver tests used rapid
command bursts that confounded results.

### 8-bit checksum (0x55AA proprietary responses)

The 0x55AA proprietary payload is 300 bytes (offsets 0–299).  The full
wire response is 310 bytes: payload(300) + 0x00(1) + FC10 ACK(8) +
0x00(1).  Byte 299 of the payload is a simple 8-bit checksum:

```
checksum = sum(bytes[0:299]) & 0xFF
```

Verified on all 4 batteries (3 slaves + bus master), both status
(0x1620) and settings (0x161E) responses, across multiple cycles
.  The checksum position is consistently byte 299 — no
exceptions observed.

## CH341 USB-Serial Quirks

The CH341 chip in the factory RS485 adapter has two issues:

1. **TX echo**: in half-duplex mode, transmitted bytes appear in the RX
   buffer.  Under Protocol 2, this shifts the 0x55AA header by 3–5 bytes.
   Under Protocol 1, the FC 0x03 response is preceded by the echo.

2. **Stale FIFO**: retains bytes across port close/reopen.  Fixed by
   `reset_input_buffer()` before each command.

Neither issue occurs with proper RS485 transceivers with TX/RX control.
Neither issue applies on the BMS-internal bus (BMS-to-BMS bus master,
no external adapter).

## RS485 Adapter Compatibility

Field-tested USB-RS485 adapters with the Protocol 2 driver. "BMS count"
is the number of parallel BMS that consistently detect on first attempt.

| Chip / Adapter | VID:PID | Isolation | Host | BMS count | Result | Notes |
|----------------|---------|-----------|------|-----------|--------|-------|
| CH341 (factory JKBMS adapter) | `1a86:7523` | no | Venus OS / armv7 | 4/4 | OK | TX-echo + stale-FIFO quirks handled by driver |
| CH340 / CH430 generic | `1a86:7523` | no | Linux / RPi-class | 12/12 | OK | Stable across multiple production deployments |
| FT232R single, non-isolated | `0403:6001` | no | Linux / RPi-class | 2–3/4 random | FAIL | Tail-truncated responses (287/288/299 of 300 bytes) and header byte read as `55 A0` instead of `55 AA`. See note below. |
| FT2232H/HL dual, isolated (Waveshare B0D7BLNG75) | `0403:6010` | yes | Venus OS / armv7 | 4/4 | OK | First-try detection, zero warnings over hours; ports A and B used independently for BMS + RS485 meter |
| Waveshare RS485↔TCP + `socat` PTY | n/a (network) | yes | Linux / RPi-class | 4/4 | OK | Bridged into `/dev/ttyVx`, runs in parallel with USB adapter to extend bus count |

Observations:

- The single-channel **FT232R** is the only consistently failing adapter
  observed so far. Failures persist across two units, with or without GND,
  and across the master/PR-#425/PR-#428 driver branches — pointing to
  electrical (drive strength / bias / fail-safe) rather than software.
- **FT2232H** (different FTDI silicon, same vendor) works flawlessly,
  so "FTDI on Linux" is not itself the problem.
- Dual-port adapters expose the unused channel as a second `/dev/ttyUSBn`
  that serial-starter will probe and respawn on. Pin the unused channel
  via udev (e.g. `ENV{VE_SERVICE}="ignore"`) to silence the loop.

### FT232R failure signature

Log captures from a 4-BMS Linux rig show two recurring failure patterns
when an FT232R adapter is used:

- Responses are **tail-truncated** at 287, 288, or 299 of the 300 expected
  payload bytes after the `0x55AA` header.
- The `0x55AA` start-of-frame is occasionally read as `0x55 0xA0` —
  bit-level corruption of a single byte rather than a missing one.

Software mitigations attempted with no effect:

- `echo 1 > /sys/bus/usb-serial/devices/ttyUSBx/latency_timer`
- `COMMAND_GAP` raised from 100 ms up to 300 ms
- Two different FT232R units, with and without RS485 ground tied

No root cause established. The same driver build runs without errors on
the same bus when a CH340/CH341 or FT2232H adapter is substituted.

## Protocol Timing (measured)

### Protocol 2, software client (this driver, external host, 4-battery system)

| Phase              | Duration   | Notes |
|--------------------|------------|-------|
| Command + response | 35–50ms    | 310 bytes at 115200 baud |
| Command gap        | 100ms      | configurable, minimum for CH341 reliability |
| **Total per command** | **~150ms** | with shared port, single command |

### Protocol 2, BMS bus master — 3 active + 12 scanned

| Phase              | Duration   | Notes |
|--------------------|------------|-------|
| Per active battery | ~260ms     | 0x1620 req + ACK + 0x161E req + ACK |
| Per scanned addr   | 220ms      | 0x1620 req, no response, timeout |
| Active poll total  | ~780ms     | 3 batteries × 260ms |
| Scan total         | ~2640ms    | 12 addresses × 220ms |
| Master self-broadcast | ~440ms  | 2 frames in the addr=15 gap |
| **Full cycle**     | **4400ms** | fixed, includes all phases |

## Venus OS / D-Bus Integration Notes

These notes are specific to the `dbus-serialbattery` Venus OS driver.

### D-Bus Performance

Venus OS uses D-Bus (via dbus-python + GLib) for IPC. Each battery
publishes ~100 properties per cycle. Mitigations:

1. **`_CachedDbusProxy`**: suppresses writes when value unchanged.
   Combined with EMA cell voltage filtering (alpha=0.3), reduces actual
   D-Bus writes from ~100 to ~3–10 per battery per cycle.

2. **Poll interval decoupling**: auto-increase logic uses serial+calc
   time only, excluding D-Bus overhead.

### Custom serial port (PTY / network bridge)

Serial-starter only auto-spawns the driver for ports it discovers via
udev (USB serials). To run on a `socat`-bridged PTY or any other
non-USB port, register a manual service entry. The runscripts derive
the port name from the service-directory suffix, so no template
rewriting is needed.

```sh
# 1. Create the PTY (example: Waveshare RS485↔TCP server at <host>:<port>)
socat -d pty,link=/dev/ttyV0,raw,echo=0,b115200,user=root,group=dialout,mode=0660 \
      tcp:<host>:<port> &

# 2. Create a permanent service entry under /data/
PORT=ttyV0
SVC=/data/etc/dbus-serialbattery-custom/dbus-serialbattery.$PORT
mkdir -p "$SVC/log"
cp /data/apps/dbus-serialbattery/service/run     "$SVC/run"
cp /data/apps/dbus-serialbattery/service/log/run "$SVC/log/run"
ln -sf "$SVC" "/service/dbus-serialbattery.$PORT"

# 3. Persist across reboot (Venus wipes /service/ symlinks)
echo "ln -sf $SVC /service/dbus-serialbattery.$PORT" >> /data/rc.local
```

Verify on D-Bus: `com.victronenergy.battery.<port>__<addr>` per
battery, e.g. `com.victronenergy.battery.ttyV0__0x01`.

`socat` lifecycle is the user's responsibility — supervise it with
your tool of choice. If `/dev/$PORT` is missing when runit picks the
service up, the runscript exits and the service stays down until
socat is up and `svc -u /service/dbus-serialbattery.$PORT` is run.

## Reference Documents

- "极空BMS RS485 Modbus通用协议(V1.0)" — `JK_BMS.RS485.Modbus.v1_0.pdf`
- "BMS RS485 Modbus V1.1" — `BMS RS485 Modbus V1.1-1.pdf`
- Driver source: `dbus-serialbattery/bms/jkbms_pb.py`
- Diagnostic tool: `test/jkbms_pb_sniff.py`
