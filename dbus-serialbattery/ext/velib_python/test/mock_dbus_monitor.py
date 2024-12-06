import dbus
from collections import defaultdict
from functools import partial

# Simulation a DbusMonitor object, without using the D-Bus (intended for unit tests). Instead of changes values
# on the D-Bus you can use the set_value function. set_value will automatically expand the service list. Note
# that all simulated D-Bus paths passed to set_value must be part of the dbusTree passed to the constructor of
# the monitor.
class MockDbusMonitor(object):
    def __init__(self, dbusTree, valueChangedCallback=None, deviceAddedCallback=None,
            deviceRemovedCallback=None, mountEventCallback=None, vebusDeviceInstance0=False, checkPaths=True):
        self._services = {}
        self._tree = {}
        self._seen = defaultdict(set)
        self._watches = defaultdict(dict)
        self._checkPaths = checkPaths
        self._value_changed_callback = valueChangedCallback
        self._device_removed_callback = deviceRemovedCallback
        self._device_added_callback = deviceAddedCallback
        for s, sv in dbusTree.items():
            service = self._tree.setdefault(s, set())
            service.update(['/Connected', '/ProductName', '/Mgmt/Connection', '/DeviceInstance'])
            for p in sv:
                service.add(p)

    # Gets the value for a certain servicename and path, returns the default_value when
    # request service and objectPath combination does not not exists or when it is invalid
    def get_value(self, serviceName, objectPath, default_value=None):
        item = self._get_item(serviceName, objectPath)
        if item is None:
            return default_value
        r = item.get_value()
        return default_value if r is None else r

    def _get_item(self, serviceName, objectPath):
        service = self._services.get(serviceName)
        if service is None:
            return None
        if objectPath not in self._tree[_class_name(serviceName)]:
            return None
        item = service.get(objectPath)
        if item is None:
            item = MockImportItem(None, valid=False)
            service[objectPath] = item
        return item

    def exists(self, serviceName, objectPath):
        if serviceName not in self._services:
            return False
        if objectPath not in self._tree[_class_name(serviceName)]:
            return False
        return True

    def set_seen(self, serviceName, path):
        self._seen[serviceName].add(path)

    def seen(self, serviceName, objectPath):
        return objectPath in self._seen[serviceName]

    # returns a dictionary, keys are the servicenames, value the instances
    # optionally use the classfilter to get only a certain type of services, for
    # example com.victronenergy.battery.
    def get_service_list(self, classfilter=None):
        r = {}
        for servicename,items in self._services.items():
            if not classfilter or _class_name(servicename) == classfilter:
                item = items.get('/DeviceInstance')
                r[servicename] = None if item is None else item.get_value()
        return r

    def add_value(self, service, path, value):
        class_name = _class_name(service)
        s = self._tree.get(class_name, None)
        if s is None:
            raise Exception('service not found')
        if self._checkPaths and path not in s:
            raise Exception('Path not found: {}{} (check dbusTree passed to __init__)'.format(service, path))
        s = self._services.setdefault(service, {})
        s[path] = MockImportItem(value)
        self.set_seen(service, path)

    def set_value(self, serviceName, objectPath, value):
        item = self._get_item(serviceName, objectPath)
        if item is None:
            return -1
        item.set_value(value)
        self.set_seen(serviceName, objectPath)
        if self._value_changed_callback != None:
            self._value_changed_callback(serviceName, objectPath, None, {'Value': value, 'Text': str(value)}, None)
        if serviceName in self._watches:
            if objectPath in self._watches[serviceName]:
                self._watches[serviceName][objectPath]({'Value': value, 'Text': str(value)})
            elif None in self._watches[serviceName]:
                self._watches[serviceName][None]({'Value': value, 'Text': str(value)})
        return 0

    def set_value_async(self, serviceName, objectPath, value,
            reply_handler=None, error_handler=None):
        item = self._get_item(serviceName, objectPath)

        if item is not None and item.exists:
            item.set_value(value)
            if reply_handler is not None:
                reply_handler(0)
            return

        if error_handler is not None:
            error_handler(TypeError('Service or path not found, '
                        'service=%s, path=%s' % (serviceName, objectPath)))

    def add_service(self, service, values):
        if service in self._services:
            raise Exception('Service already exists: {}'.format(service))
        self._services[service] = {}
        for k,v in values.items():
            self.add_value(service, k, v)
        if self._device_added_callback != None:
            self._device_added_callback(service, values.get('/DeviceInstance', 0))

    def remove_service(self, service):
        s = self._services.get(service)
        if s is None:
            return
        item = s.get('/DeviceInstance')
        instance = 0 if item is None else item.get_value()
        for item in s.values():
            item.set_service_exists(False)
        self._services.pop(service)
        if self._device_removed_callback != None:
            self._device_removed_callback(service, instance)
        if service in self._watches:
            del self._watches[service]

    def track_value(self, serviceName, objectPath, callback, *args, **kwargs):
        self._watches[serviceName][objectPath] = partial(callback, *args, **kwargs)

    @property
    def dbusConn(self):
        raise dbus.DBusException("No Connection")


class MockImportItem(object):
    def __init__(self, value, valid=True, service_exists=True):
        self._value = value
        self._valid = valid
        self._service_exists = service_exists

    def set_service_exists(self, service_exists):
        self._service_exists = service_exists

    def get_value(self):
        return self._value

    @property
    def exists(self):
        return self._valid

    def set_value(self, value):
        if not self._service_exists:
            raise dbus.exceptions.DBusException('org.freedesktop.DBus.Error.ServiceUnknown')
        if not self._valid:
            raise dbus.exceptions.DBusException('org.freedesktop.DBus.Error.UnknownObject')
        self._value = value


def _class_name(service):
    return '.'.join(service.split('.')[:3])
