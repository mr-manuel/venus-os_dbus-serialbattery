#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Python
import logging
import os
import sqlite3
import sys
import unittest
import subprocess
import time
import dbus
import threading
import fcntl
from dbus.mainloop.glib import DBusGMainLoop

# Local
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../'))
from settingsdevice import SettingsDevice

logger = logging.getLogger(__file__)

class CreateSettingsTest(unittest.TestCase):
	# The actual code calling VeDbusItemExport is in fixture_vedbus.py, which is ran as a subprocess. That
	# code exports several values to the dbus. And then below test cases check if the exported values are
	# what the should be, by using the bare dbus import objects and functions.

	def setUp(self):
		pass

	def tearDown(self):
		pass

	def test_adding_new_settings(self):
		# to make sure that we make new settings, put something random in its name:
		rnd = os.urandom(16).encode('hex')

		# ofcourse below could be simplified, for now just use all settings from the example:
		settings = SettingsDevice(
			bus=dbus.SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else dbus.SystemBus(),
			supportedSettings={
				'loggingenabled': ['/Settings/' + rnd + '/Logscript/Enabled', 1, 0, 1],
				'proxyaddress': ['/Settings/' + rnd + '/Logscript/Http/Proxy', '', 0, 0],
				'proxyport': ['/Settings/' + rnd + '/Logscript/Http/ProxyPort', '', 0, 0],
				'backlogenabled': ['/Settings/' + rnd + '/Logscript/LogFlash/Enabled', 1, 0, 1],
				'backlogpath': ['/Settings/' + rnd + '/Logscript/LogFlash/Path', '', 0, 0],  # When empty, default path will be used.
				'interval': ['/Settings/' + rnd + '/Logscript/LogInterval', 900, 0, 0],
				'url': ['/Settings/' + rnd + '/Logscript/Url', '', 0, 0]  # When empty, the default url will be used.
				},
			eventCallback=self.handle_changed_setting)

		"""
		self.assertIs(type(v), dbus.Double)
		self.assertEqual(self.dbusConn.get_object('com.victronenergy.dbusexample', '/Float').GetText(), '1.5')
		"""

	def handle_changed_setting(setting, oldvalue, newvalue):
		pass

if __name__ == "__main__":
	logging.basicConfig(stream=sys.stderr)
	logging.getLogger('').setLevel(logging.WARNING)
	DBusGMainLoop(set_as_default=True)
	unittest.main()
