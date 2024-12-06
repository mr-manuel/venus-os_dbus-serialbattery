# This module contains mock functions for some of the functionality in gobject.
# You can use this to create unit tests on code using gobject timers without having to wait for those timer.
# Use the patch functions to replace the original gobject functions. The timer_manager object defined here
# allows you to set a virtual time stamp, which will invoke all timers that would normally run in the 
# specified interval.

from datetime import datetime as dt
import time

class MockTimer(object):
	def __init__(self, start, timeout, callback, *args, **kwargs):
		self._timeout = timeout
		self._next = start + timeout
		self._callback = callback
		self._args = args
		self._kwargs = kwargs

	def run(self):
		self._next += self._timeout
		return self._callback(*self._args, **self._kwargs)

	@property
	def next(self):
		return self._next


class MockTimerManager(object):
	def __init__(self, start_time=None):
		self._resources = []
		self._time = 0
		self._id = 0
		self._timestamp = start_time or time.time()

	def add_timer(self, timeout, callback, *args, **kwargs):
		return self._add_resource(MockTimer(self._time, timeout, callback, *args, **kwargs))

	def add_idle(self, callback, *args, **kwargs):
		return self.add_timer(self._time, callback, *args, **kwargs)

	def remove_resouce(self, id):
		for rid, rr in self._resources:
			if rid == id:
				self._resources.remove((rid, rr))
				return
		raise Exception('Resource not found: {}'.format(id))

	def _add_resource(self, resource):
		self._id += 1
		self._resources.append((self._id, resource))
		return self._id

	def _terminate(self):
		raise StopIteration()

	@property
	def time(self):
		return self._time

	@property
	def datetime(self):
		return dt.fromtimestamp(self._timestamp + self._time / 1000.0)

	def run(self, interval=None):
		'''
		Simulate the given interval. Starting from the current (mock) time until time + interval, all timers
		will be triggered. The timers will be triggered in chronological order. Timer removal (calling
		source_remove or a False/None return value) and addition within the callback function is supported.
		If interval is None or not supplied, the function will run until there are no timers left.
		'''
		if interval != None:
			self.add_timer(interval, self._terminate)
		try:
			while True:
				next_timer = None
				next_id = None
				for id,t in self._resources:
					if next_timer == None or t.next < next_timer.next:
						next_timer = t
						next_id = id
				if next_timer == None:
					return
				self._time = next_timer.next
				if not next_timer.run():
					self._resources.remove((next_id, next_timer))
		except StopIteration:
			self._resources.remove((next_id, next_timer))
			pass

	def reset(self):
		self._resources = []
		self._time = 0


timer_manager = MockTimerManager()


def idle_add(callback, *args, **kwargs):
	return timer_manager.add_idle(callback, *args, **kwargs)


def timeout_add(timeout, callback, *args, **kwargs):
	return timer_manager.add_timer(timeout, callback, *args, **kwargs)


def timeout_add_seconds(timeout, callback, *args, **kwargs):
	return timeout_add(timeout * 1000, callback, *args, **kwargs)


class datetime(object):
	@staticmethod
	def now():
		return timer_manager.datetime

	@staticmethod
	def strptime(*args, **kwargs):
		return dt.strptime(*args, **kwargs)


def source_remove(id):
	timer_manager.remove_resouce(id)


def test_function(m, name):
	print(m.time, m.datetime, name)
	return True


def patch_gobject(dest):
	'''
	Use this function to replace the original gobject/GLib functions with the
	mocked versions in this file.  Suppose your source files being tested uses
	'from gi.repository import GLib' and the unit test uses 'import tested' you
	should call path(tested.GLib).
	'''
	dest.timeout_add = timeout_add
	dest.timeout_add_seconds = timeout_add_seconds
	dest.idle_add = idle_add
	dest.source_remove = source_remove


def patch_datetime(dest):
	dest.datetime = datetime


if __name__ == '__main__':
	m = MockTimerManager()
	id1 = m.add_timer(100, test_function, m, 'F1')
	id2 = m.add_timer(30, test_function, m, 'F2')
	m.run(5000)
	m.remove_resouce(id1)
	m.run(2000)
	m.remove_resouce(id2)
	m.run(2000)
