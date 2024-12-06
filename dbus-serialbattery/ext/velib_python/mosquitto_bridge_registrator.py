#!/usr/bin/python3 -u

import dbus
import fcntl
import threading
import logging
import os
import requests
import subprocess
import traceback
from ve_utils import exit_on_error

VrmNumberOfBrokers = 128
VrmApiServer = 'https://ccgxlogging.victronenergy.com'
CaBundlePath = "/etc/ssl/certs/ccgx-ca.pem"
RpcBroker = 'mqtt-rpc.victronenergy.com'
SettingsPath = os.environ.get('DBUS_MQTT_PATH') or '/data/conf/flashmq.d'
BridgeConfigPath = os.path.join(SettingsPath, 'vrm_bridge.conf')
MosquittoConfig = '/data/conf/mosquitto.d/vrm_bridge.conf'
MqttPasswordFile = "/data/conf/mqtt_password.txt"

BridgeSettingsRPC = '''
bridge {{
  protocol_version mqtt5
  max_outgoing_topic_aliases 5000
  address {3}
  port 443
  tls on
  bridge_protocol_bit true
  publish   P/{0}/out/#
  subscribe P/{0}/in/#
  clientid_prefix GXrpc
  remote_username {5}
  remote_password {1}
  ca_file {4}
}}

'''

BridgeSettingsDbus = '''
bridge {{
  protocol_version mqtt5
  address {2}
  port 443
  tls on
  bridge_protocol_bit true
  publish N/{0}/#
  subscribe R/{0}/#
  subscribe W/{0}/#
  clientid_prefix GXdbus
  remote_username {5}
  remote_password {1}
  ca_file {4}
}}

'''

LockFilePath = "/run/mosquittobridgeregistrator.lock"


def get_setting(path):
	"""Throwing exceptions on fail is desired."""

	bus = dbus.SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else dbus.SystemBus()
	msg = dbus.lowlevel.MethodCallMessage(
			'com.victronenergy.settings', path, 'com.victronenergy.BusItem', 'GetValue')
	reply = bus.send_message_with_reply_and_block(msg)
	answer = reply.get_args_list()[0].real
	return answer

class RepeatingTimer(threading.Thread):
	def __init__(self, callback, interval):
		threading.Thread.__init__(self)
		self.event = threading.Event()
		self.callback = callback
		self.interval = interval

	def run(self):
		while not self.event.is_set():
			if not self.callback():
				self.event.set()

			# either call your function here,
			# or put the body of the function here
			self.event.wait(self.interval)

	def stop(self):
		self.event.set()


class MosquittoBridgeRegistrator(object):
	"""
	The MosquittoBridgeRegistrator manages a bridge connection between the local
	MQTT server, and the global VRM broker. It can be called
	concurrently by different processes; efforts will be synchronized using an
	advisory lock file.

	It now also supports registering the API key and getting it and the password without
	restarting the MQTT server. This allows using the API key, but not use the local broker
	and instead connect directly to the VRM broker url.
	"""

	def __init__(self, system_id):
		self._init_broker_timer = None
		self._aborted = threading.Event()
		self._system_id = system_id
		self._global_broker_username = "ccgxapikey_" + self._system_id
		self._global_broker_password = None
		self._requests_log_level = logging.getLogger("requests").getEffectiveLevel()

	def _get_vrm_broker_url(self):
		"""To allow scaling, the VRM broker URL is generated based on the system identifier
		The function returns a numbered broker URL between 0 and VrmNumberOfBrokers, which makes sure
		that broker connections are distributed equally between all VRM brokers
		"""
		sum = 0
		for character in self._system_id.lower().strip():
			sum += ord(character)
		broker_index = sum % VrmNumberOfBrokers
		return "mqtt{}.victronenergy.com".format(broker_index)


	def load_or_generate_mqtt_password(self):
		"""In case posting the password to storemqttpassword.php was processed
		by the server, but we never saw the response, we need to keep it around
		for the next time (don't post a random new one).

		This way of storing the password was incepted later, and makes it
		backwards compatible.

		The MQTT password is now stored in the EEPROM on some devices and it is written
		to the mqtt_password file during boot. Note that not all devices have
		an EEPROM and this file is added later one. So while it is leading now, it
		might not be there...
		"""

		password = None

		if os.path.exists(MqttPasswordFile):
			with open(MqttPasswordFile, "r") as f:
				logging.info("Using {}".format(MqttPasswordFile))
				password = f.read().strip()
				return password

		# before FlashMQ, mosquitto was used. Check if it has a password.
		elif os.path.exists(MosquittoConfig):
			try:
				with open(MosquittoConfig, 'rt') as in_file:
					config = in_file.read()
					for l in config.split('\n'):
						if l.startswith("remote_password"):
							password = l.split(' ')[1]
							print("Using mosquitto password")
							break
			except:
				pass

		if password == None:
			password = get_random_string(32)

		with open(MqttPasswordFile + ".tmp", "w") as f:
			logging.info("Writing new {}".format(MqttPasswordFile))

			# make sure the password is on the disk
			f.write(password)
			f.flush()
			os.fsync(f.fileno())

			os.rename(MqttPasswordFile + ".tmp", MqttPasswordFile)

			# update the directory meta-info
			fd = os.open(os.path.dirname(MqttPasswordFile), 0)
			os.fsync(fd)
			os.close(fd)

			if os.path.exists(MosquittoConfig):
				self._delete_silently(MosquittoConfig)

			return password

	def register(self):
		if self._init_broker_timer is not None:
			return
		if self._init_broker(quiet=False, timeout=5):
			if not self._aborted.is_set():
				logging.info("[InitBroker] Registration failed. Retrying in thread, silently.")
				logging.getLogger("requests").setLevel(logging.WARNING)
				# Not using gobject to keep these blocking operations out of the event loop
				self._init_broker_timer = RepeatingTimer(self._init_broker, 60)
				self._init_broker_timer.start()

	def abort_gracefully(self):
		self._aborted.set()
		if self._init_broker_timer:
			self._init_broker_timer.stop()
			self._init_broker_timer.join()

	def _write_config_atomically(self, path, contents):

		config_dir = os.path.dirname(path)
		if not os.path.exists(config_dir):
			os.makedirs(config_dir)

		with open(path + ".tmp", 'wt') as out_file:
			# make sure the new config is on the disk
			out_file.write(contents)
			out_file.flush()
			os.fsync(out_file.fileno())

			# make sure there is either the old file or the new one
			os.rename(path + ".tmp", path)

			# update the directory meta-info
			fd = os.open(os.path.dirname(path), 0)
			os.fsync(fd)
			os.close(fd)

	def _delete_silently(self, path):
		try:
			os.remove(path)
		except:
			pass

	def _init_broker(self, quiet=True, timeout=5):
		try:
			with open(LockFilePath, "a") as lockFile:
				fcntl.flock(lockFile, fcntl.LOCK_EX)

				orig_config = None
				# Read the current config file (if present)
				try:
					if not quiet:
						logging.info('[InitBroker] Reading config file')
					with open(BridgeConfigPath, 'rt') as in_file:
						orig_config = in_file.read()
				except IOError:
					if not quiet:
						logging.info('[InitBroker] Reading config file failed.')
				# We need a guarantee an empty file, otherwise Mosquitto crashes on load.
				if not os.path.exists(BridgeConfigPath):
					self._write_config_atomically(BridgeConfigPath, "");
				self._global_broker_password = self.load_or_generate_mqtt_password()

				# Get to the actual registration
				if not quiet:
					logging.info('[InitBroker] Registering CCGX at VRM portal')
				with requests.Session() as session:
					headers = {'content-type': 'application/x-www-form-urlencoded', 'User-Agent': 'dbus-mqtt'}
					r = session.post(
						VrmApiServer + '/log/storemqttpassword.php',
						data=dict(identifier=self._global_broker_username, mqttPassword=self._global_broker_password),
						headers=headers,
						verify=CaBundlePath,
						timeout=(timeout,timeout))
					if r.status_code == requests.codes.ok:
						vrm_portal_mode = get_setting('/Settings/Network/VrmPortal')

						config_rpc = ""
						config_dbus = ""

						if vrm_portal_mode == 2:
							config_rpc = BridgeSettingsRPC.format(self._system_id,
								self._global_broker_password,
								self._get_vrm_broker_url(), RpcBroker, CaBundlePath,
								self._global_broker_username)
						if vrm_portal_mode >= 1:
							config_dbus = BridgeSettingsDbus.format(self._system_id,
								self._global_broker_password,
								self._get_vrm_broker_url(), RpcBroker, CaBundlePath,
								self._global_broker_username)

						config = "# Generated by BridgeRegistrator. Any changes will be overwritten on service start.\n"
						config += config_rpc
						config += config_dbus
						# Do we need to adjust the settings file?
						changed = config != orig_config
						if changed:
							logging.info('[InitBroker] Writing new config file')
							self._write_config_atomically(BridgeConfigPath, config)
						else:
							logging.info('[InitBroker] Not updating the config file, because config is correct.')
						self._init_broker_timer = None
						logging.getLogger("requests").setLevel(self._requests_log_level)
						logging.info('[InitBroker] Registration successful')
						if changed:
							os._exit(100)
						return False
					if not quiet:
						logging.error('VRM registration failed. Http status was: {}'.format(r.status_code))
						logging.error('Message was: {}'.format(r.text))
		except:
			if not quiet:
				traceback.print_exc()
		# Notify the timer we want to be called again
		return True

	def get_password(self):
		assert self._global_broker_password is not None
		return self._global_broker_password

	def get_apikey(self):
		return self._global_broker_username


def get_random_string(size=32):
	"""Creates a random (hex) string which contains 'size' characters."""
	return ''.join("{0:02x}".format(b) for b in open('/dev/urandom', 'rb').read(int(size/2)))

def main():
	from ve_utils import get_vrm_portal_id
	vrmid = get_vrm_portal_id()

	registrator = MosquittoBridgeRegistrator(vrmid)
	registrator.register()

if __name__ == "__main__":
    main()

# vim: noexpandtab:shiftwidth=4:tabstop=4:softtabstop=0
