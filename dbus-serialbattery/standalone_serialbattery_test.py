#!/usr/bin/env python3

# NOTES
# This part is maintained by https://github.com/MacGH23

# Reading bms via uni-bms lib

# macGH 20.08.2024  Version 0.1.0

import sys
import signal
import atexit
import datetime
from time import sleep
import standalone_serialbattery
import logging


# "" = default = "/dev/ttyUSB0"
# if you have another device specify here
DEVPATH = "/dev/ttyAMA0"  # with Waveshare CAN/RS485 HAT
# DEVPATH = "/dev/ttyUSB0"
USEDIDADR = 1

# Enter Loglevel 0,10,20,30,40,50
# CRITICAL   50
# ERROR      40
# WARNING    30
# INFO       20
# DEBUG      10
# NOTSET      0
LOGLEVEL = 20
logtofile = 0
logtoconsole = 1
logpath = "jkbms.log"

##################################################################
##################################################################


def on_exit():
    print("CLEAN UP ...")
    Ubms.bms_close()


def handle_exit(signum, frame):
    sys.exit(0)


# ### Main
atexit.register(on_exit)
signal.signal(signal.SIGTERM, handle_exit)
signal.signal(signal.SIGINT, handle_exit)

mylogs = logging.getLogger("UNIBMSTEST")
mylogs.setLevel(LOGLEVEL)

if logtofile == 1:
    file = logging.FileHandler(logpath, mode="a")
    file.setLevel(LOGLEVEL)
    fileformat = logging.Formatter("%(asctime)s:%(module)s:%(levelname)s:%(message)s", datefmt="%H:%M:%S")
    file.setFormatter(fileformat)
    mylogs.addHandler(file)

if logtoconsole == 1:
    stream = logging.StreamHandler()
    stream.setLevel(LOGLEVEL)
    streamformat = logging.Formatter("%(asctime)s:%(module)s:%(levelname)s:%(message)s", datefmt="%H:%M:%S")
    stream.setFormatter(streamformat)
    mylogs.addHandler(stream)


Ubms = standalone_serialbattery(DEVPATH, 0, "", LOGLEVEL)
Ubms.bms_open()
sleep(0.5)
time1 = datetime.datetime.now()
ST = Ubms.bms_read()
print("Runtime: " + str((datetime.datetime.now() - time1).total_seconds()))

i = 0
print("Cellcount: " + str(Ubms.cell_count))
for i in range(Ubms.cell_count):
    print("CellVolt" + str(i) + ": " + str(Ubms.cells[i] / 1000))

print("Temperature_Fet : " + str(Ubms.temperature_fet))
print("Temperature_1   : " + str(Ubms.temperature_1))
print("temperature_2   : " + str(Ubms.temperature_2))
print("BatVolt         : " + str(Ubms.voltage / 100))
print("Current         : " + str(Ubms.act_current / 100))
print("SOC             : " + str(Ubms.soc))
print("WATT            : " + str(int((Ubms.voltage * Ubms.act_current) / 10000)))
sleep(1)
"""
print("Cellcount: " + str(ST[0]))
for i in range(ST[0]) :
    print("CellVolt" + str(i) + ": " + str(ST[i+1]/1000))

i=ST[0]+1 #first is the cellscount and cells
print("Temperature_Fet : " + str(ST[i]))
print("Temperature_1   : " + str(ST[i+1]))
print("temperature_2   : " + str(ST[i+2]))
print("BatVolt         : " + str(ST[i+3]))
print("Current         : " + str(ST[i+4]))
print("SOC             : " + str(ST[i+5]))
"""

sys.exit(0)
