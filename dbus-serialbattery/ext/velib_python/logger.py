#!/usr/bin/python3 -u
# -*- coding: utf-8 -*-

import logging
import sys

class LevelFilter(logging.Filter):
	def __init__(self, passlevels, reject):
		self.passlevels = passlevels
		self.reject = reject

	def filter(self, record):
		if self.reject:
			return (record.levelno not in self.passlevels)
		else:
			return (record.levelno in self.passlevels)

# Leave the name set to None to get the root logger. For some reason specifying 'root' has a
# different effect: there will be two root loggers, both with their own handlers...
def setup_logging(debug=False, name=None):
	formatter = logging.Formatter(fmt='%(levelname)s:%(module)s:%(message)s')

	# Make info and debug stream to stdout and the rest to stderr
	h1 = logging.StreamHandler(sys.stdout)
	h1.addFilter(LevelFilter([logging.INFO, logging.DEBUG], False))
	h1.setFormatter(formatter)

	h2 = logging.StreamHandler(sys.stderr)
	h2.addFilter(LevelFilter([logging.INFO, logging.DEBUG], True))
	h2.setFormatter(formatter)

	logger = logging.getLogger(name)
	logger.addHandler(h1)
	logger.addHandler(h2)

	# Set the loglevel and show it
	logger.setLevel(level=(logging.DEBUG if debug else logging.INFO))
	logLevel = {0: 'NOTSET', 10: 'DEBUG', 20: 'INFO', 30: 'WARNING', 40: 'ERROR'}
	logger.info('Loglevel set to ' + logLevel[logger.getEffectiveLevel()])

	return logger
