#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# This file has some tests, to do type checking of vedbus.py
# This file makes it easy to compare the values put on the dbus through
# Python (vedbus.VeDbusItemExport) with items exported in C (the mk2dbus process)

# Note that this file requires vedbusitemexport_examples to be running.

import dbus
import pprint
import os
import sys
from dbus.mainloop.glib import DBusGMainLoop

# our own packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../'))
from vedbus import VeDbusItemExport, VeDbusItemImport

DBusGMainLoop(set_as_default=True)

# Connect to the sessionbus. Note that on ccgx we use systembus instead.
dbusConn = dbus.SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else dbus.SystemBus()


# dictionary containing the different items
dbusObjects = {}

# check if the vbus.ttyO1 exists (it normally does on a ccgx, and for linux a pc, there is
# some emulator.
hasVEBus = 'com.victronenergy.vebus.ttyO1' in dbusConn.list_names()

dbusObjects['PyString'] = VeDbusItemImport(dbusConn, 'com.victronenergy.example', '/String')
if hasVEBus: dbusObjects['C_string'] = VeDbusItemImport(dbusConn, 'com.victronenergy.vebus.ttyO1', '/Mgmt/ProcessName')

dbusObjects['PyFloat'] = VeDbusItemImport(dbusConn, 'com.victronenergy.example', '/Float')
if hasVEBus: dbusObjects['C_float'] = VeDbusItemImport(dbusConn, 'com.victronenergy.vebus.ttyO1', '/Dc/V')

dbusObjects['PyInt'] = VeDbusItemImport(dbusConn, 'com.victronenergy.example', '/Int')
if hasVEBus: dbusObjects['C_int'] = VeDbusItemImport(dbusConn, 'com.victronenergy.vebus.ttyO1', '/State')

dbusObjects['PyNegativeInt'] = VeDbusItemImport(dbusConn, 'com.victronenergy.example', '/NegativeInt')
if hasVEBus: dbusObjects['C_negativeInt'] = VeDbusItemImport(dbusConn, 'com.victronenergy.vebus.ttyO1', '/Dc/I')

# print the results
print('----')
for key, o in dbusObjects.items():
	print(key + ' at ' + o.serviceName + o.path)
	pprint.pprint(dbusObjects[key])
	print('pprint veBusItem.get_value(): ')
	pprint.pprint(dbusObjects[key].get_value())
	print('pprint veBusItem.get_text(): ')
	pprint.pprint(dbusObjects[key].get_text())
	print('----')
