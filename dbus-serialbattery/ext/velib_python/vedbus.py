#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import dbus.service
import logging
import traceback
import os
import weakref
from collections import defaultdict
from ve_utils import wrap_dbus_value, unwrap_dbus_value

# vedbus contains three classes:
# VeDbusItemImport -> use this to read data from the dbus, ie import
# VeDbusItemExport -> use this to export data to the dbus (one value)
# VeDbusService -> use that to create a service and export several values to the dbus

# Code for VeDbusItemImport is copied from busitem.py and thereafter modified.
# All projects that used busitem.py need to migrate to this package. And some
# projects used to define there own equivalent of VeDbusItemExport. Better to
# use VeDbusItemExport, or even better the VeDbusService class that does it all for you.

# TODOS
# 1 check for datatypes, it works now, but not sure if all is compliant with
#	com.victronenergy.BusItem interface definition. See also the files in
#	tests_and_examples. And see 'if type(v) == dbus.Byte:' on line 102. Perhaps
#	something similar should also be done in VeDbusBusItemExport?
# 2 Shouldn't VeDbusBusItemExport inherit dbus.service.Object?
# 7 Make hard rules for services exporting data to the D-Bus, in order to make tracking
#   changes possible. Does everybody first invalidate its data before leaving the bus?
#   And what about before taking one object away from the bus, instead of taking the
#   whole service offline?
#   They should! And after taking one value away, do we need to know that someone left
#   the bus? Or we just keep that value in invalidated for ever? Result is that we can't
#   see the difference anymore between an invalidated value and a value that was first on
#   the bus and later not anymore. See comments above VeDbusItemImport as well.
# 9 there are probably more todos in the code below.

# Some thoughts with regards to the data types:
#
#   Text from: http://dbus.freedesktop.org/doc/dbus-python/doc/tutorial.html#data-types
#   ---
#   Variants are represented by setting the variant_level keyword argument in the
#   constructor of any D-Bus data type to a value greater than 0 (variant_level 1
#   means a variant containing some other data type, variant_level 2 means a variant
#   containing a variant containing some other data type, and so on). If a non-variant
#   is passed as an argument but introspection indicates that a variant is expected,
#   it'll automatically be wrapped in a variant.
#   ---
#
#   Also the different dbus datatypes, such as dbus.Int32, and dbus.UInt32 are a subclass
#   of Python int. dbus.String is a subclass of Python standard class unicode, etcetera
#
#   So all together that explains why we don't need to explicitly convert back and forth
#   between the dbus datatypes and the standard python datatypes. Note that all datatypes
#   in python are objects. Even an int is an object.

#   The signature of a variant is 'v'.

# Export ourselves as a D-Bus service.
class VeDbusService(object):
	def __init__(self, servicename, bus=None, register=None):
		# dict containing the VeDbusItemExport objects, with their path as the key.
		self._dbusobjects = {}
		self._dbusnodes = {}
		self._ratelimiters = []
		self._dbusname = None
		self.name = servicename

		# dict containing the onchange callbacks, for each object. Object path is the key
		self._onchangecallbacks = {}

		# Connect to session bus whenever present, else use the system bus
		self._dbusconn = bus or (dbus.SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else dbus.SystemBus())

		# make the dbus connection available to outside, could make this a true property instead, but ach..
		self.dbusconn = self._dbusconn

		# Add the root item that will return all items as a tree
		self._dbusnodes['/'] = VeDbusRootExport(self._dbusconn, '/', self)

		# Immediately register the service unless requested not to
		if register is None:
			logging.warning("USING OUTDATED REGISTRATION METHOD!")
			logging.warning("Please set register=False, then call the register method "
				"after adding all mandatory paths. See "
				"https://github.com/victronenergy/venus/wiki/dbus-api")
			self.register()
		elif register:
			self.register()

	def register(self):
		# Register ourselves on the dbus, trigger an error if already in use (do_not_queue)
		self._dbusname = dbus.service.BusName(self.name, self._dbusconn, do_not_queue=True)
		logging.info("registered ourselves on D-Bus as %s" % self.name)

	# To force immediate deregistering of this dbus service and all its object paths, explicitly
	# call __del__().
	def __del__(self):
		for node in list(self._dbusnodes.values()):
			node.__del__()
		self._dbusnodes.clear()
		for item in list(self._dbusobjects.values()):
			item.__del__()
		self._dbusobjects.clear()
		if self._dbusname:
			self._dbusname.__del__()  # Forces call to self._bus.release_name(self._name), see source code
		self._dbusname = None

	def get_name(self):
		return self._dbusname.get_name()

	# @param callbackonchange	function that will be called when this value is changed. First parameter will
	#							be the path of the object, second the new value. This callback should return
	#							True to accept the change, False to reject it.
	def add_path(self, path, value, description="", writeable=False,
					onchangecallback=None, gettextcallback=None, valuetype=None, itemtype=None):

		if onchangecallback is not None:
			self._onchangecallbacks[path] = onchangecallback

		itemtype = itemtype or VeDbusItemExport
		item = itemtype(self._dbusconn, path, value, description, writeable,
				self._value_changed, gettextcallback, deletecallback=self._item_deleted, valuetype=valuetype)

		spl = path.split('/')
		for i in range(2, len(spl)):
			subPath = '/'.join(spl[:i])
			if subPath not in self._dbusnodes and subPath not in self._dbusobjects:
				self._dbusnodes[subPath] = VeDbusTreeExport(self._dbusconn, subPath, self)
		self._dbusobjects[path] = item
		logging.debug('added %s with start value %s. Writeable is %s' % (path, value, writeable))
		return item

	# Add the mandatory paths, as per victron dbus api doc
	def add_mandatory_paths(self, processname, processversion, connection,
			deviceinstance, productid, productname, firmwareversion, hardwareversion, connected):
		self.add_path('/Mgmt/ProcessName', processname)
		self.add_path('/Mgmt/ProcessVersion', processversion)
		self.add_path('/Mgmt/Connection', connection)

		# Create rest of the mandatory objects
		self.add_path('/DeviceInstance', deviceinstance)
		self.add_path('/ProductId', productid)
		self.add_path('/ProductName', productname)
		self.add_path('/FirmwareVersion', firmwareversion)
		self.add_path('/HardwareVersion', hardwareversion)
		self.add_path('/Connected', connected)

	# Callback function that is called from the VeDbusItemExport objects when a value changes. This function
	# maps the change-request to the onchangecallback given to us for this specific path.
	def _value_changed(self, path, newvalue):
		if path not in self._onchangecallbacks:
			return True

		return self._onchangecallbacks[path](path, newvalue)

	def _item_deleted(self, path):
		self._dbusobjects.pop(path)
		for np in list(self._dbusnodes.keys()):
			if np != '/':
				for ip in self._dbusobjects:
					if ip.startswith(np + '/'):
						break
				else:
					self._dbusnodes[np].__del__()
					self._dbusnodes.pop(np)

	def __getitem__(self, path):
		return self._dbusobjects[path].local_get_value()

	def __setitem__(self, path, newvalue):
		self._dbusobjects[path].local_set_value(newvalue)

	def __delitem__(self, path):
		self._dbusobjects[path].__del__()  # Invalidates and then removes the object path
		assert path not in self._dbusobjects

	def __contains__(self, path):
		return path in self._dbusobjects

	def __enter__(self):
		l = ServiceContext(self)
		self._ratelimiters.append(l)
		return l

	def __exit__(self, *exc):
		# pop off the top one and flush it. If with statements are nested
		# then each exit flushes its own part.
		if self._ratelimiters:
			self._ratelimiters.pop().flush()

class ServiceContext(object):
	def __init__(self, parent):
		self.parent = parent
		self.changes = {}

	def __contains__(self, path):
		return path in self.parent

	def __getitem__(self, path):
		return self.parent[path]

	def __setitem__(self, path, newvalue):
		c = self.parent._dbusobjects[path]._local_set_value(newvalue)
		if c is not None:
			self.changes[path] = c

	def __delitem__(self, path):
		if path in self.changes:
			del self.changes[path]
		del self.parent[path]

	def flush(self):
		if self.changes:
			self.parent._dbusnodes['/'].ItemsChanged(self.changes)
			self.changes.clear()

	def add_path(self, path, value, *args, **kwargs):
		self.parent.add_path(path, value, *args, **kwargs)
		self.changes[path] = {
			'Value': wrap_dbus_value(value),
			'Text': self.parent._dbusobjects[path].GetText()
		}

	def del_tree(self, root):
		root = root.rstrip('/')
		for p in list(self.parent._dbusobjects.keys()):
			if p == root or p.startswith(root + '/'):
				self[p] = None
				self.parent._dbusobjects[p].__del__()

	def get_name(self):
		return self.parent.get_name()

class TrackerDict(defaultdict):
	""" Same as defaultdict, but passes the key to default_factory. """
	def __missing__(self, key):
		self[key] = x = self.default_factory(key)
		return x

class VeDbusRootTracker(object):
	""" This tracks the root of a dbus path and listens for PropertiesChanged
	    signals. When a signal arrives, parse it and unpack the key/value changes
	    into traditional events, then pass it to the original eventCallback
	    method. """
	def __init__(self, bus, serviceName):
		self.importers = defaultdict(weakref.WeakSet)
		self.serviceName = serviceName
		self._match = bus.get_object(serviceName, '/', introspect=False).connect_to_signal(
			"ItemsChanged", weak_functor(self._items_changed_handler))

	def __del__(self):
		self._match.remove()
		self._match = None

	def add(self, i):
		self.importers[i.path].add(i)

	def _items_changed_handler(self, items):
		if not isinstance(items, dict):
			return

		for path, changes in items.items():
			try:
				v = changes['Value']
			except KeyError:
				continue

			try:
				t = changes['Text']
			except KeyError:
				t = str(unwrap_dbus_value(v))

			for i in self.importers.get(path, ()):
				i._properties_changed_handler({'Value': v, 'Text': t})

"""
Importing basics:
	- If when we power up, the D-Bus service does not exist, or it does exist and the path does not
	  yet exist, still subscribe to a signal: as soon as it comes online it will send a signal with its
	  initial value, which VeDbusItemImport will receive and use to update local cache. And, when set,
	  call the eventCallback.
	- If when we power up, save it
	- When using get_value, know that there is no difference between services (or object paths) that don't
	  exist and paths that are invalid (= empty array, see above). Both will return None. In case you do
	  really want to know ifa path exists or not, use the exists property.
	- When a D-Bus service leaves the D-Bus, it will first invalidate all its values, and send signals
	  with that update, and only then leave the D-Bus. (or do we need to subscribe to the NameOwnerChanged-
	  signal!?!) To be discussed and make sure. Not really urgent, since all existing code that uses this
	  class already subscribes to the NameOwnerChanged signal, and subsequently removes instances of this
	  class.

Read when using this class:
Note that when a service leaves that D-Bus without invalidating all its exported objects first, for
example because it is killed, VeDbusItemImport doesn't have a clue. So when using VeDbusItemImport,
make sure to also subscribe to the NamerOwnerChanged signal on bus-level. Or just use dbusmonitor,
because that takes care of all of that for you.
"""
class VeDbusItemImport(object):
	def __new__(cls, bus, serviceName, path, eventCallback=None, createsignal=True):
		instance = object.__new__(cls)

		# If signal tracking should be done, also add to root tracker
		if createsignal:
			if "_roots" not in cls.__dict__:
				cls._roots = TrackerDict(lambda k: VeDbusRootTracker(bus, k))

		return instance

	## Constructor
	# @param bus			the bus-object (SESSION or SYSTEM).
	# @param serviceName	the dbus-service-name (string), for example 'com.victronenergy.battery.ttyO1'
	# @param path			the object-path, for example '/Dc/V'
	# @param eventCallback	function that you want to be called on a value change
	# @param createSignal   only set this to False if you use this function to one time read a value. When
	#						leaving it to True, make sure to also subscribe to the NameOwnerChanged signal
	#						elsewhere. See also note some 15 lines up.
	def __init__(self, bus, serviceName, path, eventCallback=None, createsignal=True):
		# TODO: is it necessary to store _serviceName and _path? Isn't it
		# stored in the bus_getobjectsomewhere?
		self._serviceName = serviceName
		self._path = path
		self._match = None
		# TODO: _proxy is being used in settingsdevice.py, make a getter for that
		self._proxy = bus.get_object(serviceName, path, introspect=False)
		self.eventCallback = eventCallback

		assert eventCallback is None or createsignal == True
		if createsignal:
			self._match = self._proxy.connect_to_signal(
				"PropertiesChanged", weak_functor(self._properties_changed_handler))
			self._roots[serviceName].add(self)

		# store the current value in _cachedvalue. When it doesn't exists set _cachedvalue to
		# None, same as when a value is invalid
		self._cachedvalue = None
		try:
			v = self._proxy.GetValue()
		except dbus.exceptions.DBusException:
			pass
		else:
			self._cachedvalue = unwrap_dbus_value(v)

	def __del__(self):
		if self._match is not None:
			self._match.remove()
			self._match = None
		self._proxy = None

	def _refreshcachedvalue(self):
		self._cachedvalue = unwrap_dbus_value(self._proxy.GetValue())

	## Returns the path as a string, for example '/AC/L1/V'
	@property
	def path(self):
		return self._path

	## Returns the dbus service name as a string, for example com.victronenergy.vebus.ttyO1
	@property
	def serviceName(self):
		return self._serviceName

	## Returns the value of the dbus-item.
	# the type will be a dbus variant, for example dbus.Int32(0, variant_level=1)
	# this is not a property to keep the name consistant with the com.victronenergy.busitem interface
	# returns None when the property is invalid
	def get_value(self):
		return self._cachedvalue

	## Writes a new value to the dbus-item
	def set_value(self, newvalue):
		r = self._proxy.SetValue(wrap_dbus_value(newvalue))

		# instead of just saving the value, go to the dbus and get it. So we have the right type etc.
		if r == 0:
			self._refreshcachedvalue()

		return r

	## Resets the item to its default value
	def set_default(self):
		self._proxy.SetDefault()
		self._refreshcachedvalue()

	## Returns the text representation of the value.
	# For example when the value is an enum/int GetText might return the string
	# belonging to that enum value. Another example, for a voltage, GetValue
	# would return a float, 12.0Volt, and GetText could return 12 VDC.
	#
	# Note that this depends on how the dbus-producer has implemented this.
	def get_text(self):
		return self._proxy.GetText()

	## Returns true of object path exists, and false if it doesn't
	@property
	def exists(self):
		# TODO: do some real check instead of this crazy thing.
		r = False
		try:
			r = self._proxy.GetValue()
			r = True
		except dbus.exceptions.DBusException:
			pass

		return r

	## callback for the trigger-event.
	# @param eventCallback the event-callback-function.
	@property
	def eventCallback(self):
		return self._eventCallback

	@eventCallback.setter
	def eventCallback(self, eventCallback):
		self._eventCallback = eventCallback

	## Is called when the value of the imported bus-item changes.
	# Stores the new value in our local cache, and calls the eventCallback, if set.
	def _properties_changed_handler(self, changes):
		if "Value" in changes:
			changes['Value'] = unwrap_dbus_value(changes['Value'])
			self._cachedvalue = changes['Value']
			if self._eventCallback:
				# The reason behind this try/except is to prevent errors silently ending up the an error
				# handler in the dbus code.
				try:
					self._eventCallback(self._serviceName, self._path, changes)
				except:
					traceback.print_exc()
					os._exit(1)  # sys.exit() is not used, since that also throws an exception


class VeDbusTreeExport(dbus.service.Object):
	def __init__(self, bus, objectPath, service):
		dbus.service.Object.__init__(self, bus, objectPath)
		self._service = service
		logging.debug("VeDbusTreeExport %s has been created" % objectPath)

	def __del__(self):
		# self._get_path() will raise an exception when retrieved after the call to .remove_from_connection,
		# so we need a copy.
		path = self._get_path()
		if path is None:
			return
		self.remove_from_connection()
		logging.debug("VeDbusTreeExport %s has been removed" % path)

	def _get_path(self):
		if len(self._locations) == 0:
			return None
		return self._locations[0][1]

	def _get_value_handler(self, path, get_text=False):
		logging.debug("_get_value_handler called for %s" % path)
		r = {}
		px = path
		if not px.endswith('/'):
			px += '/'
		for p, item in self._service._dbusobjects.items():
			if p.startswith(px):
				v = item.GetText() if get_text else wrap_dbus_value(item.local_get_value())
				r[p[len(px):]] = v
		logging.debug(r)
		return r

	@dbus.service.method('com.victronenergy.BusItem', out_signature='v')
	def GetValue(self):
		value = self._get_value_handler(self._get_path())
		return dbus.Dictionary(value, signature=dbus.Signature('sv'), variant_level=1)

	@dbus.service.method('com.victronenergy.BusItem', out_signature='v')
	def GetText(self):
		return self._get_value_handler(self._get_path(), True)

	def local_get_value(self):
		return self._get_value_handler(self.path)

class VeDbusRootExport(VeDbusTreeExport):
	@dbus.service.signal('com.victronenergy.BusItem', signature='a{sa{sv}}')
	def ItemsChanged(self, changes):
		pass

	@dbus.service.method('com.victronenergy.BusItem', out_signature='a{sa{sv}}')
	def GetItems(self):
		return {
			path: {
				'Value': wrap_dbus_value(item.local_get_value()),
				'Text': item.GetText() }
			for path, item in self._service._dbusobjects.items()
		}


class VeDbusItemExport(dbus.service.Object):
	## Constructor of VeDbusItemExport
	#
	# Use this object to export (publish), values on the dbus
	# Creates the dbus-object under the given dbus-service-name.
	# @param bus		  The dbus object.
	# @param objectPath	  The dbus-object-path.
	# @param value		  Value to initialize ourselves with, defaults to None which means Invalid
	# @param description  String containing a description. Can be called over the dbus with GetDescription()
	# @param writeable	  what would this do!? :).
	# @param callback	  Function that will be called when someone else changes the value of this VeBusItem
	#                     over the dbus. First parameter passed to callback will be our path, second the new
	#					  value. This callback should return True to accept the change, False to reject it.
	def __init__(self, bus, objectPath, value=None, description=None, writeable=False,
					onchangecallback=None, gettextcallback=None, deletecallback=None,
					valuetype=None):
		dbus.service.Object.__init__(self, bus, objectPath)
		self._onchangecallback = onchangecallback
		self._gettextcallback = gettextcallback
		self._value = value
		self._description = description
		self._writeable = writeable
		self._deletecallback = deletecallback
		self._type = valuetype

	# To force immediate deregistering of this dbus object, explicitly call __del__().
	def __del__(self):
		# self._get_path() will raise an exception when retrieved after the
		# call to .remove_from_connection, so we need a copy.
		path = self._get_path()
		if path == None:
			return
		if self._deletecallback is not None:
			self._deletecallback(path)
		self.remove_from_connection()
		logging.debug("VeDbusItemExport %s has been removed" % path)

	def _get_path(self):
		if len(self._locations) == 0:
			return None
		return self._locations[0][1]

	## Sets the value. And in case the value is different from what it was, a signal
	# will be emitted to the dbus. This function is to be used in the python code that
	# is using this class to export values to the dbus.
	# set value to None to indicate that it is Invalid
	def local_set_value(self, newvalue):
		changes = self._local_set_value(newvalue)
		if changes is not None:
			self.PropertiesChanged(changes)

	def _local_set_value(self, newvalue):
		if self._value == newvalue:
			return None

		self._value = newvalue
		return {
			'Value': wrap_dbus_value(newvalue),
			'Text': self.GetText()
		}

	def local_get_value(self):
		return self._value

	# ==== ALL FUNCTIONS BELOW THIS LINE WILL BE CALLED BY OTHER PROCESSES OVER THE DBUS ====

	## Dbus exported method SetValue
	# Function is called over the D-Bus by other process. It will first check (via callback) if new
	# value is accepted. And it is, stores it and emits a changed-signal.
	# @param value The new value.
	# @return completion-code When successful a 0 is return, and when not a -1 is returned.
	@dbus.service.method('com.victronenergy.BusItem', in_signature='v', out_signature='i')
	def SetValue(self, newvalue):
		if not self._writeable:
			return 1  # NOT OK

		newvalue = unwrap_dbus_value(newvalue)

		# If value type is enforced, cast it. If the type can be coerced
		# python will do it for us. This allows ints to become floats,
		# or bools to become ints. Additionally also allow None, so that
		# a path may be invalidated.
		if self._type is not None and newvalue is not None:
			try:
				newvalue = self._type(newvalue)
			except (ValueError, TypeError):
				return 1 # NOT OK

		if newvalue == self._value:
			return 0  # OK

		# call the callback given to us, and check if new value is OK.
		if (self._onchangecallback is None or
				(self._onchangecallback is not None and self._onchangecallback(self.__dbus_object_path__, newvalue))):

			self.local_set_value(newvalue)
			return 0  # OK

		return 2  # NOT OK

	## Dbus exported method GetDescription
	#
	# Returns the a description.
	# @param language A language code (e.g. ISO 639-1 en-US).
	# @param length Lenght of the language string.
	# @return description
	@dbus.service.method('com.victronenergy.BusItem', in_signature='si', out_signature='s')
	def GetDescription(self, language, length):
		return self._description if self._description is not None else 'No description given'

	## Dbus exported method GetValue
	# Returns the value.
	# @return the value when valid, and otherwise an empty array
	@dbus.service.method('com.victronenergy.BusItem', out_signature='v')
	def GetValue(self):
		return wrap_dbus_value(self._value)

	## Dbus exported method GetText
	# Returns the value as string of the dbus-object-path.
	# @return text A text-value. '---' when local value is invalid
	@dbus.service.method('com.victronenergy.BusItem', out_signature='s')
	def GetText(self):
		if self._value is None:
			return '---'

		# Default conversion from dbus.Byte will get you a character (so 'T' instead of '84'), so we
		# have to convert to int first. Note that if a dbus.Byte turns up here, it must have come from
		# the application itself, as all data from the D-Bus should have been unwrapped by now.
		if self._gettextcallback is None and type(self._value) == dbus.Byte:
			return str(int(self._value))

		if self._gettextcallback is None and self.__dbus_object_path__ == '/ProductId':
			return "0x%X" % self._value

		if self._gettextcallback is None:
			return str(self._value)

		return self._gettextcallback(self.__dbus_object_path__, self._value)

	## The signal that indicates that the value has changed.
	# Other processes connected to this BusItem object will have subscribed to the
	# event when they want to track our state.
	@dbus.service.signal('com.victronenergy.BusItem', signature='a{sv}')
	def PropertiesChanged(self, changes):
		pass

## This class behaves like a regular reference to a class method (eg. self.foo), but keeps a weak reference
## to the object which method is to be called.
## Use this object to break circular references.
class weak_functor:
	def __init__(self, f):
		self._r = weakref.ref(f.__self__)
		self._f = weakref.ref(f.__func__)

	def __call__(self, *args, **kargs):
		r = self._r()
		f = self._f()
		if r == None or f == None:
			return
		f(r, *args, **kargs)
