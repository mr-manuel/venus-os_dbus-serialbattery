#!/usr/bin/env python3
# -*- coding: utf-8 -*-

## @package dbus_vrm
# This code takes care of the D-Bus interface (not all of below is implemented yet):
# - on startup it scans the dbus for services we know. For each known service found, it searches for
#   objects/paths we know. Everything we find is stored in items{}, and an event is registered: if a
#   value changes weĺl be notified and can pass that on to our owner. For example the vrmLogger.
#   we know.
# - after startup, it continues to monitor the dbus:
#		1) when services are added we do the same check on that
#		2) when services are removed, we remove any items that we had that referred to that service
#		3) if an existing services adds paths we update ourselves as well: on init, we make a
#		   VeDbusItemImport for a non-, or not yet existing objectpaths as well1
#
# Code is used by the vrmLogger, and also the pubsub code. Both are other modules in the dbus_vrm repo.

from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
import dbus
import dbus.service
import inspect
import logging
import argparse
import pprint
import traceback
import os
from collections import defaultdict
from functools import partial

# our own packages
from ve_utils import exit_on_error, wrap_dbus_value, unwrap_dbus_value, add_name_owner_changed_receiver

# dbus interface
VE_INTERFACE = "com.victronenergy.BusItem"

# For lookups where None is a valid result
notfound = object()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
class SystemBus(dbus.bus.BusConnection):
	def __new__(cls):
		return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SYSTEM)

class SessionBus(dbus.bus.BusConnection):
	def __new__(cls):
		return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SESSION)

class MonitoredValue(object):
	def __init__(self, value, text, options):
		super(MonitoredValue, self).__init__()
		self.value = value
		self.text = text
		self.options = options

	# For legacy code, allow treating this as a tuple/list
	def __iter__(self):
		return iter((self.value, self.text, self.options))

class Service(object):
	def __init__(self, id, serviceName, deviceInstance):
		super(Service, self).__init__()
		self.id = id
		self.name = serviceName
		self.paths = {}
		self._seen = set()
		self.deviceInstance = deviceInstance

	# For legacy code, attributes can still be accessed as if keys from a
	# dictionary.
	def __setitem__(self, key, value):
		self.__dict__[key] = value
	def __getitem__(self, key):
		return self.__dict__[key]

	def set_seen(self, path):
		self._seen.add(path)

	def seen(self, path):
		return path in self._seen

	@property
	def service_class(self):
		return '.'.join(self.name.split('.')[:3])

class DbusMonitor(object):
	## Constructor
	def __init__(self, dbusTree, valueChangedCallback=None, deviceAddedCallback=None,
					deviceRemovedCallback=None, namespace="com.victronenergy", ignoreServices=[]):
		# valueChangedCallback is the callback that we call when something has changed.
		# def value_changed_on_dbus(dbusServiceName, dbusPath, options, changes, deviceInstance):
		# in which changes is a tuple with GetText() and GetValue()
		self.valueChangedCallback = valueChangedCallback
		self.deviceAddedCallback = deviceAddedCallback
		self.deviceRemovedCallback = deviceRemovedCallback
		self.dbusTree = dbusTree
		self.ignoreServices = ignoreServices

		# Lists all tracked services. Stores name, id, device instance, value per path, and whenToLog info
		# indexed by service name (eg. com.victronenergy.settings).
		self.servicesByName = {}

		# Same values as self.servicesByName, but indexed by service id (eg. :1.30)
		self.servicesById = {}

		# Keep track of services by class to speed up calls to get_service_list
		self.servicesByClass = defaultdict(list)

		# Keep track of any additional watches placed on items
		self.serviceWatches = defaultdict(list)

		# For a PC, connect to the SessionBus
		# For a CCGX, connect to the SystemBus
		self.dbusConn = SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else SystemBus()

		# subscribe to NameOwnerChange for bus connect / disconnect events.
		# NOTE: this is on a different bus then the one above!
		standardBus = (dbus.SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ \
			else dbus.SystemBus())

		add_name_owner_changed_receiver(standardBus, self.dbus_name_owner_changed)

		# Subscribe to PropertiesChanged for all services
		self.dbusConn.add_signal_receiver(self.handler_value_changes,
			dbus_interface='com.victronenergy.BusItem',
			signal_name='PropertiesChanged', path_keyword='path',
			sender_keyword='senderId')

		# Subscribe to ItemsChanged for all services
		self.dbusConn.add_signal_receiver(self.handler_item_changes,
			dbus_interface='com.victronenergy.BusItem',
			signal_name='ItemsChanged', path='/',
			sender_keyword='senderId')

		logger.info('===== Search on dbus for services that we will monitor starting... =====')
		serviceNames = self.dbusConn.list_names()
		for serviceName in serviceNames:
			self.scan_dbus_service(serviceName)

		logger.info('===== Search on dbus for services that we will monitor finished =====')

	@staticmethod
	def make_service(serviceId, serviceName, deviceInstance):
		""" Override this to use a different kind of service object. """
		return Service(serviceId, serviceName, deviceInstance)

	def make_monitor(self, service, path, value, text, options):
		""" Override this to do more things with monitoring. """
		return MonitoredValue(unwrap_dbus_value(value), unwrap_dbus_value(text), options)

	def dbus_name_owner_changed(self, name, oldowner, newowner):
		if not name.startswith("com.victronenergy."):
			return

		#decouple, and process in main loop
		GLib.idle_add(exit_on_error, self._process_name_owner_changed, name, oldowner, newowner)

	def _process_name_owner_changed(self, name, oldowner, newowner):
		if newowner != '':
			# so we found some new service. Check if we can do something with it.
			newdeviceadded = self.scan_dbus_service(name)
			if newdeviceadded and self.deviceAddedCallback is not None:
				self.deviceAddedCallback(name, self.get_device_instance(name))

		elif name in self.servicesByName:
			# it disappeared, we need to remove it.
			logger.info("%s disappeared from the dbus. Removing it from our lists" % name)
			service = self.servicesByName[name]
			del self.servicesById[service.id]
			del self.servicesByName[name]
			for watch in self.serviceWatches[name]:
				watch.remove()
			del self.serviceWatches[name]
			self.servicesByClass[service.service_class].remove(service)
			if self.deviceRemovedCallback is not None:
				self.deviceRemovedCallback(name, service.deviceInstance)

	def scan_dbus_service(self, serviceName):
		try:
			return self.scan_dbus_service_inner(serviceName)
		except:
			logger.error("Ignoring %s because of error while scanning:" % (serviceName))
			traceback.print_exc()
			return False

			# Errors 'org.freedesktop.DBus.Error.ServiceUnknown' and
			# 'org.freedesktop.DBus.Error.Disconnected' seem to happen when the service
			# disappears while its being scanned. Which might happen, but is not really
			# normal either, so letting them go into the logs.

	# Scans the given dbus service to see if it contains anything interesting for us. If it does, add
	# it to our list of monitored D-Bus services.
	def scan_dbus_service_inner(self, serviceName):

		# make it a normal string instead of dbus string
		serviceName = str(serviceName)

		if (len(self.ignoreServices) != 0 and any(serviceName.startswith(x) for x in self.ignoreServices)):
			logger.debug("Ignoring service %s" % serviceName)
			return False

		paths = self.dbusTree.get('.'.join(serviceName.split('.')[0:3]), None)
		if paths is None:
			logger.debug("Ignoring service %s, not in the tree" % serviceName)
			return False

		logger.info("Found: %s, scanning and storing items" % serviceName)
		serviceId = self.dbusConn.get_name_owner(serviceName)

		# we should never be notified to add a D-Bus service that we already have. If this assertion
		# raises, check process_name_owner_changed, and D-Bus workings.
		assert serviceName not in self.servicesByName
		assert serviceId not in self.servicesById

		# Try to fetch everything with a GetItems, then fall back to older
		# methods if that fails
		try:
			values = self.dbusConn.call_blocking(serviceName, '/', VE_INTERFACE, 'GetItems', '', [])
		except dbus.exceptions.DBusException:
			logger.info("GetItems failed, trying legacy methods")
		else:
			return self.scan_dbus_service_getitems_done(serviceName, serviceId, values)

		if serviceName == 'com.victronenergy.settings' or serviceName == 'com.victronenergy.platform':
			di = 0
		elif serviceName.startswith('com.victronenergy.vecan.'):
			di = 0
		else:
			try:
				di = self.dbusConn.call_blocking(serviceName,
					'/DeviceInstance', VE_INTERFACE, 'GetValue', '', [])
			except dbus.exceptions.DBusException:
				logger.info("       %s was skipped because it has no device instance" % serviceName)
				return False # Skip it
			else:
				di = int(di)

		logger.info("       %s has device instance %s" % (serviceName, di))
		service = self.make_service(serviceId, serviceName, di)

		# Let's try to fetch everything in one go
		values = {}
		texts = {}
		try:
			values.update(self.dbusConn.call_blocking(serviceName, '/', VE_INTERFACE, 'GetValue', '', []))
			texts.update(self.dbusConn.call_blocking(serviceName, '/', VE_INTERFACE, 'GetText', '', []))
		except:
			pass

		for path, options in paths.items():
			# path will be the D-Bus path: '/Ac/ActiveIn/L1/V'
			# options will be a dictionary: {'code': 'V', 'whenToLog': 'onIntervalAlways'}

			# Try to obtain the value we want from our bulk fetch. If we
			# cannot find it there, do an individual query.
			value = values.get(path[1:], notfound)
			if value != notfound:
				service.set_seen(path)
			text = texts.get(path[1:], notfound)
			if value is notfound or text is notfound:
				try:
					value = self.dbusConn.call_blocking(serviceName, path, VE_INTERFACE, 'GetValue', '', [])
					service.set_seen(path)
					text = self.dbusConn.call_blocking(serviceName, path, VE_INTERFACE, 'GetText', '', [])
				except dbus.exceptions.DBusException as e:
					if e.get_dbus_name() in (
							'org.freedesktop.DBus.Error.ServiceUnknown',
							'org.freedesktop.DBus.Error.Disconnected'):
						raise # This exception will be handled below

					# TODO org.freedesktop.DBus.Error.UnknownMethod really
					# shouldn't happen but sometimes does.
					logger.debug("%s %s does not exist (yet)" % (serviceName, path))
					value = None
					text = None

			service.paths[path] = self.make_monitor(service, path, unwrap_dbus_value(value), unwrap_dbus_value(text), options)


		logger.debug("Finished scanning and storing items for %s" % serviceName)

		# Adjust self at the end of the scan, so we don't have an incomplete set of
		# data if an exception occurs during the scan.
		self.servicesByName[serviceName] = service
		self.servicesById[serviceId] = service
		self.servicesByClass[service.service_class].append(service)

		return True

	def scan_dbus_service_getitems_done(self, serviceName, serviceId, values):
		# Keeping these exceptions for legacy reasons
		if serviceName == 'com.victronenergy.settings' or serviceName == 'com.victronenergy.platform':
			di = 0
		elif serviceName.startswith('com.victronenergy.vecan.'):
			di = 0
		else:
			try:
				di = values['/DeviceInstance']['Value']
			except KeyError:
				logger.info("       %s was skipped because it has no device instance" % serviceName)
				return False
			else:
				di = int(di)

		logger.info("       %s has device instance %s" % (serviceName, di))
		service = self.make_service(serviceId, serviceName, di)

		paths = self.dbusTree.get('.'.join(serviceName.split('.')[0:3]), {})
		for path, options in paths.items():
			item = values.get(path, notfound)
			if item is notfound:
				service.paths[path] = self.make_monitor(service, path, None, None, options)
			else:
				service.set_seen(path)
				value = item.get('Value', None)
				text = item.get('Text', None)
				service.paths[path] = self.make_monitor(service, path, unwrap_dbus_value(value), unwrap_dbus_value(text), options)

		self.servicesByName[serviceName] = service
		self.servicesById[serviceId] = service
		self.servicesByClass[service.service_class].append(service)
		return True

	def handler_item_changes(self, items, senderId):
		if not isinstance(items, dict):
			return

		try:
			service = self.servicesById[senderId]
		except KeyError:
			# senderId isn't there, which means it hasn't been scanned yet.
			return

		for path, changes in items.items():
			try:
				v = unwrap_dbus_value(changes['Value'])
			except (KeyError, TypeError):
				continue

			try:
				t = changes['Text']
			except KeyError:
				t = str(v)
			self._handler_value_changes(service, path, v, t)

	def handler_value_changes(self, changes, path, senderId):
		# If this properyChange does not involve a value, our work is done.
		if 'Value' not in changes:
			return

		try:
			service = self.servicesById[senderId]
		except KeyError:
			# senderId isn't there, which means it hasn't been scanned yet.
			return

		v = unwrap_dbus_value(changes['Value'])
		# Some services don't send Text with their PropertiesChanged events.
		try:
			t = changes['Text']
		except KeyError:
			t = str(v)
		self._handler_value_changes(service, path, v, t)

	def _handler_value_changes(self, service, path, value, text):
		try:
			a = service.paths[path]
		except KeyError:
			# path isn't there, which means it hasn't been scanned yet.
			return

		service.set_seen(path)

		# First update our store to the new value
		if a.value == value:
			return

		a.value = value
		a.text = text

		# And do the rest of the processing in on the mainloop
		if self.valueChangedCallback is not None:
			GLib.idle_add(exit_on_error, self._execute_value_changes, service.name, path, {
				'Value': value, 'Text': text}, a.options)

	def _execute_value_changes(self, serviceName, objectPath, changes, options):
		# double check that the service still exists, as it might have
		# disappeared between scheduling-for and executing this function.
		if serviceName not in self.servicesByName:
			return

		self.valueChangedCallback(serviceName, objectPath,
			options, changes, self.get_device_instance(serviceName))

	# Gets the value for a certain servicename and path
	# The default_value is returned when:
	# 1. When the service doesn't exist.
	# 2. When the path asked for isn't being monitored.
	# 3. When the path exists, but has dbus-invalid, ie an empty byte array.
	# 4. When the path asked for is being monitored, but doesn't exist for that service.
	def get_value(self, serviceName, objectPath, default_value=None):
		service = self.servicesByName.get(serviceName, None)
		if service is None:
			return default_value

		value = service.paths.get(objectPath, None)
		if value is None or value.value is None:
			return default_value

		return value.value

	# returns if a dbus exists now, by doing a blocking dbus call.
	# Typically seen will be sufficient and doesn't need access to the dbus.
	def exists(self, serviceName, objectPath):
		try:
			self.dbusConn.call_blocking(serviceName, objectPath, VE_INTERFACE, 'GetValue', '', [])
			return True
		except dbus.exceptions.DBusException as e:
			return False

	# Returns if there ever was a successful GetValue or valueChanged event.
	# Unlike get_value this return True also if the actual value is invalid.
	#
	# Note: the path might no longer exists anymore, but that doesn't happen in
	# practice. If a service really wants to reconfigure itself typically it should
	# reconnect to the dbus which causes it to be rescanned and seen will be updated.
	# If it is really needed to know if a path still exists, use exists.
	def seen(self, serviceName, objectPath):
		try:
			return self.servicesByName[serviceName].seen(objectPath)
		except KeyError:
			return False

	# Sets the value for a certain servicename and path, returns the return value of the D-Bus SetValue
	# method. If the underlying item does not exist (the service does not exist, or the objectPath was not
	# registered) the function will return -1
	def set_value(self, serviceName, objectPath, value):
		# Check if the D-Bus object referenced by serviceName and objectPath is registered. There is no
		# necessity to do this, but it is in line with previous implementations which kept VeDbusItemImport
		# objects for registers items only.
		service = self.servicesByName.get(serviceName, None)
		if service is None:
			return -1
		if objectPath not in service.paths:
			return -1
		# We do not catch D-Bus exceptions here, because the previous implementation did not do that either.
		return self.dbusConn.call_blocking(serviceName, objectPath,
				   dbus_interface=VE_INTERFACE,
				   method='SetValue', signature=None,
				   args=[wrap_dbus_value(value)])

	# Similar to set_value, but operates asynchronously
	def set_value_async(self, serviceName, objectPath, value,
			reply_handler=None, error_handler=None):
		service = self.servicesByName.get(serviceName, None)
		if service is not None:
			if objectPath in service.paths:
				self.dbusConn.call_async(serviceName, objectPath,
					dbus_interface=VE_INTERFACE,
					method='SetValue', signature=None,
					args=[wrap_dbus_value(value)],
					reply_handler=reply_handler, error_handler=error_handler)
				return

		if error_handler is not None:
			error_handler(TypeError('Service or path not found, '
						'service=%s, path=%s' % (serviceName, objectPath)))

	# returns a dictionary, keys are the servicenames, value the instances
	# optionally use the classfilter to get only a certain type of services, for
	# example com.victronenergy.battery.
	def get_service_list(self, classfilter=None):
		if classfilter is None:
			return { servicename: service.deviceInstance \
				for servicename, service in self.servicesByName.items() }

		if classfilter not in self.servicesByClass:
			return {}

		return { service.name: service.deviceInstance \
			for service in self.servicesByClass[classfilter] }

	def get_device_instance(self, serviceName):
		return self.servicesByName[serviceName].deviceInstance

	def track_value(self, serviceName, objectPath, callback, *args, **kwargs):
		""" A DbusMonitor can watch specific service/path combos for changes
		    so that it is not fully reliant on the global handler_value_changes
		    in this class. Additional watches are deleted automatically when
		    the service disappears from dbus. """
		cb = partial(callback, *args, **kwargs)

		def root_tracker(items):
			# Check if objectPath in dict
			try:
				v = items[objectPath]
				_v = unwrap_dbus_value(v['Value'])
			except (KeyError, TypeError):
				return # not in this dict

			try:
				t = v['Text']
			except KeyError:
				cb({'Value': _v })
			else:
				cb({'Value': _v, 'Text': t})

		# Track changes on the path, and also on root
		self.serviceWatches[serviceName].extend((
			self.dbusConn.add_signal_receiver(cb,
				dbus_interface='com.victronenergy.BusItem',
				signal_name='PropertiesChanged',
				path=objectPath, bus_name=serviceName),
			self.dbusConn.add_signal_receiver(root_tracker,
				dbus_interface='com.victronenergy.BusItem',
				signal_name='ItemsChanged',
				path="/", bus_name=serviceName),
		))


# ====== ALL CODE BELOW THIS LINE IS PURELY FOR DEVELOPING THIS CLASS ======

# Example function that can be used as a starting point to use this code
def value_changed_on_dbus(dbusServiceName, dbusPath, dict, changes, deviceInstance):
	logger.debug("0 ----------------")
	logger.debug("1 %s%s changed" % (dbusServiceName, dbusPath))
	logger.debug("2 vrm dict     : %s" % dict)
	logger.debug("3 changes-text: %s" % changes['Text'])
	logger.debug("4 changes-value: %s" % changes['Value'])
	logger.debug("5 deviceInstance: %s" % deviceInstance)
	logger.debug("6 - end")


def nameownerchange(a, b):
	# used to find memory leaks in dbusmonitor and VeDbusItemImport
	import gc
	gc.collect()
	objects = gc.get_objects()
	print (len([o for o in objects if type(o).__name__ == 'VeDbusItemImport']))
	print (len([o for o in objects if type(o).__name__ == 'SignalMatch']))
	print (len(objects))


def print_values(dbusmonitor):
	a = dbusmonitor.get_value('wrongservice', '/DbusInvalid', default_value=1000)
	b = dbusmonitor.get_value('com.victronenergy.dummyservice.ttyO1', '/NotInTheMonitorList', default_value=1000)
	c = dbusmonitor.get_value('com.victronenergy.dummyservice.ttyO1', '/DbusInvalid', default_value=1000)
	d = dbusmonitor.get_value('com.victronenergy.dummyservice.ttyO1', '/NonExistingButMonitored', default_value=1000)

	print ("All should be 1000: Wrong Service: %s, NotInTheMonitorList: %s, DbusInvalid: %s, NonExistingButMonitored: %s" % (a, b, c, d))
	return True

# We have a mainloop, but that is just for developing this code. Normally above class & code is used from
# some other class, such as vrmLogger or the pubsub Implementation.
def main():
	# Init logging
	logging.basicConfig(level=logging.DEBUG)
	logger.info(__file__ + " is starting up")

	# Have a mainloop, so we can send/receive asynchronous calls to and from dbus
	DBusGMainLoop(set_as_default=True)

	import os
	import sys
	sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../../'))

	dummy = {'code': None, 'whenToLog': 'configChange', 'accessLevel': None}
	monitorlist = {'com.victronenergy.dummyservice': {
				'/Connected': dummy,
				'/ProductName': dummy,
				'/Mgmt/Connection': dummy,
				'/Dc/0/Voltage': dummy,
				'/Dc/0/Current': dummy,
				'/Dc/0/Temperature': dummy,
				'/Load/I': dummy,
				'/FirmwareVersion': dummy,
				'/DbusInvalid': dummy,
				'/NonExistingButMonitored': dummy}}

	d = DbusMonitor(monitorlist, value_changed_on_dbus,
		deviceAddedCallback=nameownerchange, deviceRemovedCallback=nameownerchange)

	GLib.timeout_add(1000, print_values, d)

	# Start and run the mainloop
	logger.info("Starting mainloop, responding on only events")
	mainloop = GLib.MainLoop()
	mainloop.run()

if __name__ == "__main__":
	main()
