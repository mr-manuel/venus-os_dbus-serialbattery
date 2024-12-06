import dbus
import logging
import time
from functools import partial

# Local imports
from vedbus import VeDbusItemImport

## Indexes for the setting dictonary.
PATH = 0
VALUE = 1
MINIMUM = 2
MAXIMUM = 3
SILENT = 4

## The Settings Device class.
# Used by python programs, such as the vrm-logger, to read and write settings they
# need to store on disk. And since these settings might be changed from a different
# source, such as the GUI, the program can pass an eventCallback that will be called
# as soon as some setting is changed.
#
# The settings are stored in flash via the com.victronenergy.settings service on dbus.
# See https://github.com/victronenergy/localsettings for more info.
#
# If there are settings in de supportSettings list which are not yet on the dbus, 
# and therefore not yet in the xml file, they will be added through the dbus-addSetting
# interface of com.victronenergy.settings.
class SettingsDevice(object):
	## The constructor processes the tree of dbus-items.
	# @param bus the system-dbus object
	# @param name the dbus-service-name of the settings dbus service, 'com.victronenergy.settings'
	# @param supportedSettings dictionary with all setting-names, and their defaultvalue, min, max and whether
	# the setting is silent. The 'silent' entry is optional. If set to true, no changes in the setting will
	# be logged by localsettings.
	# @param eventCallback function that will be called on changes on any of these settings
	# @param timeout Maximum interval to wait for localsettings. An exception is thrown at the end of the
	# interval if the localsettings D-Bus service has not appeared yet.
	def __init__(self, bus, supportedSettings, eventCallback, name='com.victronenergy.settings', timeout=0):
		logging.debug("===== Settings device init starting... =====")
		self._bus = bus
		self._dbus_name = name
		self._eventCallback = eventCallback
		self._values = {} # stored the values, used to pass the old value along on a setting change
		self._settings = {}

		count = 0
		while True:
			if 'com.victronenergy.settings' in self._bus.list_names():
				break
			if count == timeout:
				raise Exception("The settings service com.victronenergy.settings does not exist!")
			count += 1
			logging.info('waiting for settings')
			time.sleep(1)

		# Add the items.
		self.addSettings(supportedSettings)

		logging.debug("===== Settings device init finished =====")

	def addSettings(self, settings):
		for setting, options in settings.items():
			silent = len(options) > SILENT and options[SILENT]
			busitem = self.addSetting(options[PATH], options[VALUE],
				options[MINIMUM], options[MAXIMUM], silent, callback=partial(self.handleChangedSetting, setting))
			self._settings[setting] = busitem
			self._values[setting] = busitem.get_value()

	def addSetting(self, path, value, _min, _max, silent=False, callback=None):
		busitem = VeDbusItemImport(self._bus, self._dbus_name, path, callback)
		if busitem.exists and (value, _min, _max, silent) == busitem._proxy.GetAttributes():
			logging.debug("Setting %s found" % path)
		else:
			logging.info("Setting %s does not exist yet or must be adjusted" % path)

			# Prepare to add the setting. Most dbus types extend the python
			# type so it is only necessary to additionally test for Int64.
			if isinstance(value, (int, dbus.Int64)):
				itemType = 'i'
			elif isinstance(value, float):
				itemType = 'f'
			else:
				itemType = 's'

			# Add the setting
			# TODO, make an object that inherits VeDbusItemImport, and complete the D-Bus settingsitem interface
			settings_item = VeDbusItemImport(self._bus, self._dbus_name, '/Settings', createsignal=False)
			setting_path = path.replace('/Settings/', '', 1)
			if silent:
				settings_item._proxy.AddSilentSetting('', setting_path, value, itemType, _min, _max)
			else:
				settings_item._proxy.AddSetting('', setting_path, value, itemType, _min, _max)

			busitem = VeDbusItemImport(self._bus, self._dbus_name, path, callback)

		return busitem

	def handleChangedSetting(self, setting, servicename, path, changes):
		oldvalue = self._values[setting] if setting in self._values else None
		self._values[setting] = changes['Value']

		if self._eventCallback is None:
			return

		self._eventCallback(setting, oldvalue, changes['Value'])

	def setDefault(self, path):
                item = VeDbusItemImport(self._bus, self._dbus_name, path, createsignal=False)
                item.set_default()

	def __getitem__(self, setting):
		return self._settings[setting].get_value()

	def __setitem__(self, setting, newvalue):
		result = self._settings[setting].set_value(newvalue)
		if result != 0:
			# Trying to make some false change to our own settings? How dumb!
			assert False
