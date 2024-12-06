PATH = 0
VALUE = 1
MINIMUM = 2
MAXIMUM = 3
SILENT = 4

class MockSettingsItem(object):
    def __init__(self, parent, path):
        self._parent = parent
        self.path = path

    def get_value(self):
        setting = 'addSetting'+self.path
        if setting in self._parent._settings:
            return self._parent[setting]
        return None

    def set_value(self, value):
        self._parent['addSetting'+self.path] = value

    @property
    def exists(self):
        return 'addSetting'+self.path in self._parent._settings

# Simulates the SettingsSevice object without using the D-Bus (intended for unit tests). Values passed to
# __setitem__ (or the [] operator) will be stored in memory for later retrieval by __getitem__.
class MockSettingsDevice(object):
    def __init__(self, supported_settings, event_callback, name='com.victronenergy.settings', timeout=0):
        self._dbus_name = name
        self._settings = supported_settings
        self._event_callback = event_callback
        self._settings_items = {}

    def addSetting(self, path, value, _min, _max, silent=False, callback=None):
        # Persist in our settings stash so the settings is available through
        # the mock item
        self._settings['addSetting'+path] = [path, value, _min, _max, silent]
        return MockSettingsItem(self, path)

    def addSettings(self, settings):
        for setting, options in settings.items():
            silent = len(options) > SILENT and options[SILENT]
            self._settings[setting] = [options[PATH], options[VALUE], options[MINIMUM], options[MAXIMUM], silent, None]

    def get_short_name(self, path):
        for k,v in self._settings.items():
            if v[PATH] == path:
                return k
        return None

    def __getitem__(self, setting):
        return self._settings[setting][VALUE]

    def __setitem__(self, setting, new_value):
        s = self._settings.get(setting, None)
        if s is None:
            raise Exception('setting not found') 
        old_value = s[VALUE] 
        if old_value == new_value:
            return
        s[VALUE] = new_value
        if self._event_callback is not None:
            self._event_callback(setting, old_value, new_value)
