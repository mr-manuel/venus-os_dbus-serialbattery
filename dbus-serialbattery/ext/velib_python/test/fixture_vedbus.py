#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from dbus.mainloop.glib import DBusGMainLoop
import dbus
import dbus.service
import inspect
import platform
import pprint
import sys
import os

# our own packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../'))
from gi.repository import GLib
from vedbus import VeDbusItemExport

# Dictionary containing all objects exported to dbus
dbusObjects = {}

def changerequest(path, newvalue):
	if newvalue < 100:
		return True
	else:
		return False

def gettext(path, value):
	return 'gettexted %s %s' % (path, value)

def main(argv):
		global dbusObjects

		# Have a mainloop, so we can send/receive asynchronous calls to and from dbus
		DBusGMainLoop(set_as_default=True)

		# Connect to session bus whenever present, else use the system bus
		dbusConn = dbus.SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else dbus.SystemBus()

		# Register ourserves on the dbus as a service
		name = dbus.service.BusName("com.victronenergy.dbusexample", dbusConn)

		# Create the management objects, as specified in the ccgx dbus-api document

		# Keep a reference in the global dictionary. Without this they would be removed by
		# garbage collector again.
		dbusObjects['string'] = VeDbusItemExport(dbusConn, '/String', 'this is a string')
		dbusObjects['int'] = VeDbusItemExport(dbusConn, '/Int', 40000)
		dbusObjects['negativeInt'] = VeDbusItemExport(dbusConn, '/NegativeInt', -10)
		dbusObjects['float'] = VeDbusItemExport(dbusConn, '/Float', 1.5)
		dbusObjects['invalid'] = VeDbusItemExport(dbusConn, '/Invalid', None)
		dbusObjects['byte'] = VeDbusItemExport(dbusConn, '/Byte', dbus.Byte(84))
		dbusObjects['writeable'] = VeDbusItemExport(dbusConn, '/Writeable', 'original', writeable=True)
		dbusObjects['not-writeable'] = VeDbusItemExport(dbusConn, '/NotWriteable', 'original', writeable=False)

		dbusObjects['not-writeable with cb'] = VeDbusItemExport(dbusConn, '/WriteableUpTo100',
			'original', writeable=True, onchangecallback=changerequest)

		dbusObjects['gettextcallback'] = VeDbusItemExport(dbusConn, '/Gettextcallback',
			'10', gettextcallback=gettext, writeable=True)

		mainloop = GLib.MainLoop()
		print("up and running")
		sys.stdout.flush()

		mainloop.run()

main("")
