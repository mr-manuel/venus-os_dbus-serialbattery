#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GObject as gobject
import dbus
import dbus.service
from pprint import pprint
import os
import signal
from time import time

items = {}
total = 0
t_started = time()

class DbusTracker(object):
	def __init__(self): 

		self.items = {}

		# For a PC, connect to the SessionBus, otherwise (Venus device) connect to the systembus
		self.dbusConn = dbus.SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else dbus.SystemBus()

		# subscribe to all signals
		self.dbusConn.add_signal_receiver(self._signal_receive_handler,
			sender_keyword='sender',
			path_keyword='path')

		names = self.dbusConn.list_names()
		for name in names:
			if name.startswith(":"):
				continue

			items[str(self.dbusConn.get_name_owner(name))] = {"_total": 0, "_name": str(name)}


	def _signal_receive_handler(*args, **kwargs):
		global total
		total = total + 1

		sender = str(kwargs['sender'])
		path = str(kwargs['path'])

		d = items.get(sender)
		if d is None:
			items[sender] = {"_total": 1, path: 1}
			return

		d["_total"] = d["_total"] + 1

		p = d.get(path)
		if p is None:
			d[path] = 1
			return

		d[path] = p + 1


def printall():
	t_elapsed = time() - t_started

	print(chr(27) + "[2J" + chr(27) + "[;H")

	row_format = "{:<60} {:>4}  {:>4}%  {:>4.2f} / s"

	print(row_format.format("Total", total, 100, total / t_elapsed))

	for service, values in items.items():
		# skip the services that didn't emit any signals
		if len(values) == 2 and "_name" in values:
			continue

		print(row_format.format(values.get("_name", service), values["_total"], values["_total"] * 100 / total, values["_total"] / t_elapsed))

	# uncomment this to see all the paths as well.
	# print("--------------")
	# pprint(items)
	return True


def main():
	DBusGMainLoop(set_as_default=True)

	d = DbusTracker()

	gobject.timeout_add(2000, printall)

	mainloop = gobject.MainLoop()
	mainloop.run()


if __name__ == "__main__":
	main()
