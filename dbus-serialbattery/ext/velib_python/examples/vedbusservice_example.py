#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
import dbus
import dbus.service
import inspect
import pprint
import os
import sys

# our own packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../'))
from vedbus import VeDbusService

softwareVersion = '1.0'

def validate_new_value(path, newvalue):
	# Max RPM setpoint = 1000
	return newvalue <= 1000

def get_text_for_rpm(path, value):
	return('%d rotations per minute' % value)

def main(argv):
		global dbusObjects

		print(__file__ + " starting up")

		# Have a mainloop, so we can send/receive asynchronous calls to and from dbus
		DBusGMainLoop(set_as_default=True)

		# Put ourselves on to the dbus
		dbusservice = VeDbusService('com.victronenergy.example', register=False)

		# Most simple and short way to add an object with an initial value of 5.
		dbusservice.add_path('/Position', value=5)

		# Most advanced way to add a path
		dbusservice.add_path('/RPM', value=100, description='RPM setpoint', writeable=True,
			onchangecallback=validate_new_value, gettextcallback=get_text_for_rpm)

		# Many types supported
		dbusservice.add_path('/String', 'this is a string')
		dbusservice.add_path('/Int', 0)
		dbusservice.add_path('/NegativeInt', -10)
		dbusservice.add_path('/Float', 1.5)

		# Call register after adding paths. More paths can be added later.
		# This claims the service name on dbus.
		dbusservice.register()

		# You can access the paths as if the dbusservice is a dictionary
		print('/Position value is %s' % dbusservice['/Position'])

		# Same for changing it
		dbusservice['/Position'] = 10

		print('/Position value is now %s' % dbusservice['/Position'])

		# To invalidate a value (see com.victronenergy.BusItem specs for definition of invalid), set to None
		dbusservice['/Position'] = None

		print('try changing our RPM by executing the following command from a terminal\n')
		print('dbus-send --print-reply --dest=com.victronenergy.example /RPM com.victronenergy.BusItem.SetValue int32:1200')
		print('Reply will be <> 0 for values > 1000: not accepted. And reply will be 0 for values < 1000: accepted.')
		mainloop = GLib.MainLoop()
		mainloop.run()

main("")
