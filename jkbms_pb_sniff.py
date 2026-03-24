#!/usr/bin/env python3
"""
Diagnostic script for JKBMS PB RS485 communication.
Sends commands and prints raw hex response.
Usage: python3 jkbms_pb_sniff.py /dev/ttyUSB1 [address]
  address: DIP switch ID as hex, e.g. 0x03 (default)
"""

import sys
import time
import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB1"
ADDR = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x03
BAUD = 115200
TIMEOUT = 1.0  # seconds to wait for response


def modbus_crc(msg: bytes) -> bytes:
    crc = 0xFFFF
    for b in msg:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc.to_bytes(2, "little")


def build_cmd(addr: int, cmd_body: bytes) -> bytes:
    msg = bytes([addr]) + cmd_body
    return msg + modbus_crc(msg)


def send_and_read(ser: serial.Serial, cmd: bytes, label: str) -> bytes:
    print(f"\n=== {label} ===")
    print(f"TX ({len(cmd)} bytes): {cmd.hex(' ').upper()}")
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    ser.write(cmd)
    time.sleep(TIMEOUT)
    data = ser.read(ser.in_waiting or 1)
    if data:
        print(f"RX ({len(data)} bytes): {data.hex(' ').upper()}")
        # ASCII printable overlay
        printable = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
        print(f"    ASCII: {printable}")
    else:
        print("RX: (no response)")
    return data


# Known commands from driver (function 0x10 = write-multiple-registers)
CMD_SETTINGS = b"\x10\x16\x1e\x00\x01\x02\x00\x00"  # get_settings
CMD_STATUS = b"\x10\x16\x20\x00\x01\x02\x00\x00"  # get_status
CMD_ABOUT = b"\x10\x16\x1c\x00\x01\x02\x00\x00"  # get_about

# Alternative: Modbus read holding registers (fn 0x03) variants to probe
CMD_READ_REG_0000 = b"\x03\x00\x00\x00\x01"  # read 1 reg at 0x0000
CMD_READ_REG_1000 = b"\x03\x10\x00\x00\x01"  # read 1 reg at 0x1000
CMD_READ_REG_1620 = b"\x03\x16\x20\x00\x01"  # read 1 reg at 0x1620
# broadcast / address 0x00
CMD_BROADCAST_SETTINGS = b"\x10\x16\x1e\x00\x01\x02\x00\x00"

print(f"Port: {PORT}  Baud: {BAUD}  BMS address: 0x{ADDR:02X}")

with serial.Serial(PORT, baudrate=BAUD, timeout=TIMEOUT) as ser:
    time.sleep(0.5)  # let port settle

    # Try existing driver commands
    send_and_read(ser, build_cmd(ADDR, CMD_SETTINGS), f"get_settings  addr=0x{ADDR:02X}")
    send_and_read(ser, build_cmd(ADDR, CMD_STATUS), f"get_status    addr=0x{ADDR:02X}")
    send_and_read(ser, build_cmd(ADDR, CMD_ABOUT), f"get_about     addr=0x{ADDR:02X}")

    # Try broadcast address 0x00
    send_and_read(ser, build_cmd(0x00, CMD_SETTINGS), "get_settings  addr=0x00 (broadcast)")
    send_and_read(ser, build_cmd(0x00, CMD_STATUS), "get_status    addr=0x00 (broadcast)")

    # Try Modbus read-holding-registers variants
    send_and_read(ser, build_cmd(ADDR, CMD_READ_REG_0000), f"read-regs 0x0000 addr=0x{ADDR:02X}")
    send_and_read(ser, build_cmd(ADDR, CMD_READ_REG_1620), f"read-regs 0x1620 addr=0x{ADDR:02X}")

    # Listen passively for 3s – battery may broadcast unsolicited data
    print("\n=== Passive listen 3s ===")
    ser.reset_input_buffer()
    time.sleep(3)
    data = ser.read(ser.in_waiting or 1)
    if data:
        print(f"Unsolicited ({len(data)} bytes): {data.hex(' ').upper()}")
    else:
        print("Unsolicited: (nothing)")
