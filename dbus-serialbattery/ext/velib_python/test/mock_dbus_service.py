# Simulates the busService object without using the D-Bus (intended for unit tests). Data usually stored in
# D-Bus items is now stored in memory.
class MockDbusService(object):
    def __init__(self, servicename):
        self._dbusobjects = {}
        self._callbacks = {}
        self._service_name = servicename

    def add_path(self, path, value, description="", writeable=False, onchangecallback=None,
                 gettextcallback=None, itemtype=None):
        self._dbusobjects[path] = value
        if onchangecallback is not None:
            self._callbacks[path] = onchangecallback

    def register(self):
        # Nothing to do when mocking
        pass

    # Add the mandatory paths, as per victron dbus api doc
    def add_mandatory_paths(self, processname, processversion, connection,
            deviceinstance, productid, productname, firmwareversion, hardwareversion, connected):
        self.add_path('/Management/ProcessName', processname)
        self.add_path('/Management/ProcessVersion', processversion)
        self.add_path('/Management/Connection', connection)

        # Create rest of the mandatory objects
        self.add_path('/DeviceInstance', deviceinstance)
        self.add_path('/ProductId', productid)
        self.add_path('/ProductName', productname)
        self.add_path('/FirmwareVersion', firmwareversion)
        self.add_path('/HardwareVersion', hardwareversion)
        self.add_path('/Connected', connected)

    # Simulates a SetValue from the D-Bus, if avaible the onchangecallback associated with the path will
    # be called before the data is changed.
    def set_value(self, path, newvalue):
        callback = self._callbacks.get(path)
        if callback is None or callback(path, newvalue):
            self._dbusobjects[path] = newvalue

    def __getitem__(self, path):
        return self._dbusobjects[path]

    def __setitem__(self, path, newvalue):
        if path not in self._dbusobjects:
            raise Exception('Path not registered in service: {}{} (use add_path to register)'.\
                format(self._service_name, path))
        self._dbusobjects[path] = newvalue

    def __delitem__(self, path):
        del self._dbusobjects[path]

    def __contains__(self, path):
        return path in self._dbusobjects

    def __enter__(self):
        # No batching done in mock object, and we already
        # support the required dict interface.
        return self

    def __exit__(self, *exc):
        pass
