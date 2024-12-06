#!/usr/bin/env python3
# -*- coding: utf-8 -*-

## @package dbus_vrm

import logging
logger = logging.getLogger(__name__)

import codecs
import threading
import subprocess
from time import sleep

# Runs a command, and calls sendfeedback with the statusupdates.
class StreamCommand(object):
	SIGNALS = {
		1: "SIGHUP", 2: "SIGINT", 3: "SIGQUIT", 4: "SIGILL", 6: "SIGABRT", 7: "SIGBUS", 8: "SIGFPE",
		9: "SIGKILL", 10: "SIGBUS", 11: "SIGSEGV", 12: "SIGSYS", 13: "SIGPIPE", 14: "SIGALRM",
		15: "SIGTERM"}

	def run(self, command, timeout, feedbacksender):
		self.feedbacksender = feedbacksender
		self.returncode = None
		self.utf8_decoder = codecs.getdecoder("utf_8")
		self.latin1_decoder = codecs.getdecoder("latin1")

		def target():
			logger.info('Thread started for running %s' % command)
			self.feedbacksender.send({"status": "starting"})

			try:
				self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
			except OSError as e:
				logger.info("Command %s could not be started, errno: %s, msg: %s"
					% (command, e.errno, e.strerror))
				self.feedbacksender.send({"status": "error",
					"errormessage": "Could not start (errno %s, msg %s)" % (e.errno, e.strerror),
					"errorcode": 731}, finished=True)

				self.process = None
				return

			self.readandsend()


		thread = threading.Thread(target=target)
		thread.start()
		thread.join(timeout)

		if self.process is None:
			# Error message has already beent sent
			return None

		# Make sure to send all the output
		self.readandsend()

		if thread.is_alive():
			logger.warning("Command %s will now be terminated because of timeout" % command)
			self.process.terminate()  # TODO or should it be killed?
			thread.join()
			logger.warning("Command %s has been terminated" % command)
			r = {"status": "error", "errormessage": "Stopped by timeout", "errorcode": 732}

		elif self.process.returncode < 0:
			signal = -1 * self.process.returncode
			error = "Stopped with signal %d - %s" % (signal, self.SIGNALS.get(signal, "unknown"))
			logger.warning("Command %s abnormal stop. %s" % (command, error))
			r = {"status": "error", "errorcode": 733, "errormessage": error}

		else:
			logger.info("Command %s execution completed. Exitcode %d" % (command, self.process.returncode))
			r = {"status": "finished", "exitcode": self.process.returncode}

		self.feedbacksender.send(r, finished=True)
		return self.process.returncode

	def readandsend(self):
		# TODO: check that below code works OK with vup stdout encoding (UTF-8), including non-standard ASCII chars

		while True:
			self.process.stdout.flush()
			line = self.process.stdout.readline()
			try:
				unicode_line, _ = self.utf8_decoder(line)
			except UnicodeDecodeError:
				unicode_line, _ = self.latin1_decoder(line)

			# Max length on pubnub is 1800 chars, and output is much better readable with the bare eye
			# when sent per line. So no need to send it alltogether.
			self.feedbacksender.send({"status": "running", "xmloutput": unicode_line})
			if line == b'' and self.process.poll() != None:
				break
			sleep(0.04)
