## IMPORTANT NOTE - MVA 2015-2-5 
# This file is  deprecated. Use the standard logging package of Python instead

## @package tracing
# The tracing module for debug-purpose.

log = None

## Setup the debug traces.
# The traces can be logged to console and/or file.
# When logged to file a logrotate is used.
# @param enabled When True traces are enabled.
# @param path The path for the trace-file.
# @param fileName The trace-file-name.
# @param toConsole When True show traces to console.
# @param debugOn When True show debug-traces.
def setupTraces(enabled, path, fileName, toConsole, toFile, debugOn):
	global log

	if enabled:
		import logging
		import logging.handlers

		log = logging.getLogger(fileName)
		if debugOn == True:
			level = logging.DEBUG
		else:
			level = logging.INFO
		log.setLevel(level)
		log.disabled = not enabled
		if toConsole == True:
			sth = logging.StreamHandler()
			fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
			sth.setFormatter(fmt)
			sth.setLevel(level)
			log.addHandler(sth)
		if toFile == True:
			fd = logging.handlers.RotatingFileHandler(path + fileName, maxBytes=1048576, backupCount=5)
			fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
			fd.setFormatter(fmt)
			fd.setLevel(level)
			log.addHandler(fd)
	else:
		log = LogDummy()

class LogDummy(object):
	def __init__(self):
		self._str = ''
		
	def info(self, str, *args):
		self._str = str
		
	def debug(self, str, *args):
		self._str = str
	
	def warning(self, str, *args):
		print("Warning: " + (str % args))

	def error(self, str, *args):
		print("Error: " + (str % args))
