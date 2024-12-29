#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Daly CAN BMS Simulator
----------------------
This simulator listens on a virtual CAN interface (vcan0 by default) for
requests from a Python driver that implements the Daly CAN protocol. When
it receives a recognized command arbitration ID, it sends back a realistic
but static response frame.

The simulator is based on the message layout and logic from the daly_can.py
driver (shown in the prompt). Use it for testing or development when real
Daly hardware is not available.

Requirements:
- python-can library
- A virtual CAN interface (e.g., vcan0) set up on your system.

Usage:
- python daly_can_simulator.py
- The simulator will run indefinitely, printing received messages and
  sending responses to recognized command frames.

Author:
- ChatGPT (prompt by user: "you are a embedded software engineer and python expert...")
"""
import sys
import os
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "../ext"))

import can  # noqa: E402
import struct  # noqa: E402


# -------------------------------------------------------------------------------------
# The driver daly_can.py defines these command -> response arbitration IDs:
# (See the CAN_FRAMES dictionary in daly_can.py)
#
# COMMAND_SOC                -> 0x18900140
# RESPONSE_SOC               -> 0x18904001
# COMMAND_MINMAX_CELL_VOLTS  -> 0x18910140
# RESPONSE_MINMAX_CELL_VOLTS -> 0x18914001
# COMMAND_MINMAX_TEMP        -> 0x18920140
# RESPONSE_MINMAX_TEMP       -> 0x18924001
# COMMAND_FET                -> 0x18930140
# RESPONSE_FET               -> 0x18934001
# COMMAND_STATUS             -> 0x18940140
# RESPONSE_STATUS            -> 0x18944001
# COMMAND_CELL_VOLTS         -> 0x18950140
# RESPONSE_CELL_VOLTS        -> 0x18954001
# COMMAND_TEMP               -> 0x18960140  # not actively used in the driver
# RESPONSE_TEMP              -> 0x18964001
# COMMAND_CELL_BALANCE       -> 0x18970140
# RESPONSE_CELL_BALANCE      -> 0x18974001
# COMMAND_ALARM              -> 0x18980140
# RESPONSE_ALARM             -> 0x18984001
#
# The driver expects responses with specific data layouts as described in daly_can.py.
# We'll send data that fits those layouts and falls within "realistic" ranges.
# -------------------------------------------------------------------------------------

REQUEST_BASE = 0x18900040  # insert id at byte 3
RESPONSE_BASE = 0x18904000  # insert id at byte 4

# Offsets/constants used in daly_can.py
CURRENT_ZERO_CONSTANT = 30000
TEMP_ZERO_CONSTANT = 40


class DalyCanSimulator:
    def __init__(self, channel='vcan0', bustype='socketcan'):
        """
        Initialize the simulator with a given CAN interface (defaults to vcan0).
        """
        self.bus = can.interface.Bus(channel=channel, bustype=bustype)
        print(f"Initialized Daly CAN BMS Simulator on interface '{channel}'.")

        # Store any stateful information here if needed, e.g., changing SoC over time.
        # If you want to simulate a different number of cells, adapt this to match your scenario.
        self.simulated_soc = 75.0  # 75%
        self.simulated_current = 0.0   # 0 A (idle)
        self.simulated_cycle_count = 123
        self.simulated_cells = [3.25, 3.27, 3.30, 3.28, 3.30, 3.27, 3.26, 3.29]
        self.simulated_voltage = sum(self.simulated_cells)

    def run(self):
        """
        Main loop: read incoming CAN frames and respond if they match known commands.
        """
        print("Daly CAN Simulator is running. Waiting for request frames...\n"
              "Press Ctrl+C to quit.\n")
        while True:
            # Read a message from the bus (blocking).
            msg = self.bus.recv(timeout=1.0)
            if msg is None:
                # No message arrived in 1 second, loop again.
                continue

            # Print the incoming message (for debugging).
            print(f"RX: ID=0x{msg.arbitration_id:08X}, data={msg.data.hex().upper()}")

            # Check if the arbitration ID is one of the recognized command IDs.
            response = self.process_request(msg.arbitration_id, msg.data)
            if response is not None:
                # response is a list of (arbitration_id, data_bytes) we want to send
                for arb_id, data_bytes in response:
                    out_msg = can.Message(arbitration_id=arb_id, data=data_bytes, is_extended_id=True)
                    try:
                        self.bus.send(out_msg)
                        print(f"TX: ID=0x{arb_id:08X}, data={data_bytes.hex().upper()}")
                    except can.CanError as e:
                        print(f"ERROR sending response: {e}")

    def process_request(self, arbitration_id, data):
        """
        Given a command arbitration ID, return the corresponding response
        frames (arbitration_id, data_bytes) or None if not recognized.
        """
        # We'll match the known command arbitration IDs to produce responses.
        # Some commands in the driver might not be used or might not require immediate response.
        responses = []
        id = (arbitration_id & 0x0000ff00) >> 8
        arbitration_id = arbitration_id & 0xffff00ff  # clear out id for simpler matching

        if arbitration_id == 0x18900040:  # COMMAND_SOC
            # The driver expects an 8-byte response with layout: >HHHH
            #   voltage (uint16, deci-volts)
            #   tmp (uint16, unknown usage)
            #   current (uint16, offset by CURRENT_ZERO_CONSTANT)
            #   soc (uint16, tenths of %)
            #
            # We'll create some realistic values for demonstration:
            # voltage = e.g. 52.0 V => 520 in deci-volts
            # tmp = 0 (not used by the driver)
            # current = e.g. 30000 means 0 A. If we want -5 A => 29950
            # soc = 750 => 75.0%
            voltage_int = int(self.simulated_voltage * 10)       # e.g. 52.0 -> 520
            tmp_int = 0
            current_int = CURRENT_ZERO_CONSTANT + int(self.simulated_current * -10)
            soc_int = int(self.simulated_soc * 10)               # e.g. 75.0 -> 750

            payload = struct.pack(">HHHH", voltage_int, tmp_int, current_int, soc_int)
            responses.append((0x18904000 | id, payload))  # RESPONSE_SOC

        elif arbitration_id == 0x18910040:  # COMMAND_MINMAX_CELL_VOLTS
            # Response is 6 bytes:  >hbhb
            # cell_max_voltage (int16, mV), cell_max_no (int8), cell_min_voltage (int16, mV), cell_min_no (int8)
            # The driver divides by 1000 for each voltage, and subtracts 1 from the cell indices.
            cell_min = min(self.simulated_cells)
            cell_max = max(self.simulated_cells)
            min_idx = self.simulated_cells.index(cell_min) + 1  # driver expects 1-based
            max_idx = self.simulated_cells.index(cell_max) + 1
            cell_max_mv = int(cell_max * 1000)
            cell_min_mv = int(cell_min * 1000)
            # pack that into >hbhb
            payload = struct.pack(">hbhb", cell_max_mv, max_idx, cell_min_mv, min_idx)
            responses.append((0x18914000 | id, payload))  # RESPONSE_MINMAX_CELL_VOLTS

        elif arbitration_id == 0x18920040:  # COMMAND_MINMAX_TEMP
            # The driver expects 4 bytes: >BBBB
            # max_temp, max_no, min_temp, min_no
            # each is offset by TEMP_ZERO_CONSTANT in the driver.
            # If we want to simulate e.g. 25°C for min, 30°C for max,
            # then stored_value = actual_temp + 40 in the driver,
            # but we must provide driver_value = actual_temp + 40 here.
            min_temp_c = 25
            max_temp_c = 30
            min_no = 1
            max_no = 2
            payload = struct.pack(">BBBB",
                                  max_temp_c + TEMP_ZERO_CONSTANT,
                                  max_no,
                                  min_temp_c + TEMP_ZERO_CONSTANT,
                                  min_no)
            responses.append((0x18924000 | id, payload))  # RESPONSE_MINMAX_TEMP

        elif arbitration_id == 0x18930040:  # COMMAND_FET
            # The driver expects 8 bytes: >b??BL
            # (status, charge_fet, discharge_fet, charge_cycles(uint16?), capacity_remain(uint32?))
            #
            # We'll keep it simple:
            # status = 0
            # charge_fet = True
            # discharge_fet = True
            # cycles = self.simulated_cycle_count
            # capacity_remain = e.g. 50000 => 50.0Ah (since driver does capacity_remain/1000)
            status = 0
            charge_fet = True
            discharge_fet = True
            cycles = self.simulated_cycle_count
            capacity_remain = 50000  # 50.0 Ah

            # Pack into >b??BL
            # b = int8, ?? = two bools, B = uint8, L = uint32
            # Note: in many Python versions, 'struct.pack' won't pack bools natively as single bits,
            # but this is how the driver unpacks. We'll pack them as 1 byte each for True/False.
            payload = struct.pack(">b??BL", status, charge_fet, discharge_fet, cycles, capacity_remain)
            responses.append((0x18934000 | id, payload))  # RESPONSE_FET

        elif arbitration_id == 0x18940040:  # COMMAND_STATUS
            # The driver expects 8 bytes: >BB??BHx
            # cell_count, temp_sensors, charger_connected, load_connected, status(?), charge_cycles
            #
            # We'll say:
            #  cell_count = len(self.simulated_cells)
            #  temp_sensors = 2
            #  charger_connected = True
            #  load_connected = True
            #  status = 0
            #  charge_cycles = self.simulated_cycle_count
            #
            # The trailing 'x' in the struct means 1 byte of padding that we can set to 0.
            cell_count = len(self.simulated_cells)
            temp_sensors = 2
            charger_connected = True
            load_connected = True
            status = 0
            cycles = self.simulated_cycle_count

            # Pack into >BB??BHx
            # B, B = two 8-bit
            # ?? = two bools (1 byte each)
            # B = 8-bit
            # H = 16-bit
            # x = 1 byte padding
            payload = struct.pack(">BB??BHx",
                                  cell_count,
                                  temp_sensors,
                                  charger_connected,
                                  load_connected,
                                  status,
                                  cycles)
            responses.append((0x18944000 | id, payload))  # RESPONSE_STATUS

        elif arbitration_id == 0x18950040:  # COMMAND_CELL_VOLTS
            # The driver expects multiple 8-byte frames for cell voltages: >BHHHx
            #
            # The driver parses them in increments of 8 bytes:
            #   1 byte => frame number
            #   3 x 2 bytes => cell voltages in mV
            #   1 byte => leftover
            #
            # We'll send enough frames for all SIMULATED_CELL_COUNT cells.
            # Each frame can hold up to 3 cell voltages. We'll build them in a loop.
            frames = []
            num_cells = len(self.simulated_cells)
            cells_per_frame = 3
            frame_number = 1

            idx = 0
            while idx < num_cells:
                # For each frame, we can have up to 3 cells
                cell_vals = [0, 0, 0]
                for i in range(cells_per_frame):
                    cell_index = idx + i
                    if cell_index < num_cells:
                        cell_vals[i] = int(self.simulated_cells[cell_index] * 1000)  # convert V -> mV
                    else:
                        cell_vals[i] = 0
                # BHHHx => 1 + 2 + 2 + 2 + 1 = 8 bytes
                # We put frame_number in the first byte, then the 3 cell voltages.
                # The last 'x' is just pad (1 byte).
                frame_payload = struct.pack(">BHHHx",
                                            frame_number,
                                            cell_vals[0],
                                            cell_vals[1],
                                            cell_vals[2]
                                            )
                frames.append(frame_payload)
                frame_number += 1
                idx += cells_per_frame

            # We'll produce separate CAN messages for each 8-byte chunk.
            # The driver lumps them together in its cache.
            for fp in frames:
                responses.append((0x18954000 | id, fp))  # RESPONSE_CELL_VOLTS

        elif arbitration_id == 0x18970040:  # COMMAND_CELL_BALANCE
            # The driver doesn't do anything with the cell balance response
            # aside from reading it, but let's send an 8-byte frame of zeros.
            # The driver might ignore it. In the real hardware it's used to
            # indicate which cells are balancing, etc.
            payload = bytes([0] * 8)
            responses.append((0x18974000 | id, payload))  # RESPONSE_CELL_BALANCE

        elif arbitration_id == 0x18980040:  # COMMAND_ALARM
            # The driver expects 8 bytes: >BBBBBBBB
            # e.g. alarm bits for voltage, temperature, current, etc.
            # We'll send zero for all to simulate "no alarms".
            payload = bytes([0] * 8)
            responses.append((0x18984000 | id, payload))  # RESPONSE_ALARM

        # If arbitration_id is recognized, return the list of responses; otherwise None.
        if responses:
            return responses
        else:
            return None


if __name__ == "__main__":
    simulator = DalyCanSimulator(channel='vcan0', bustype='socketcan')
    try:
        simulator.run()
    except KeyboardInterrupt:
        print("\nShutting down Daly CAN Simulator.")
