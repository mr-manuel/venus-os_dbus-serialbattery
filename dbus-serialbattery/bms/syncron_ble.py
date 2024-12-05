from utils import logger
import threading
import asyncio
import time
from bleak import BleakClient

class Syncron_Ble:

    ble_async_thread_ready = threading.Event()
    ble_connection_ready = threading.Event()
    ble_async_thread_event_loop = False
    client = False
    address = None
    response_event = False
    response_data = False
    main_thread = False

    write_characteristic = None
    read_characteristic = None

    def __init__(self, address, read_characteristic, write_characteristic):
        self.write_characteristic = write_characteristic
        self.read_characteristic = read_characteristic
        self.address = address

        self.main_thread = threading.current_thread()
        ble_async_thread = threading.Thread(name="BMS_bluetooth_async_thread", target=self.initiate_ble_thread_main, daemon=True)
        ble_async_thread.start()
        thread_start_ok = self.ble_async_thread_ready.wait(2)
        connected_ok = self.ble_connection_ready.wait(10)
        if not thread_start_ok:
            logger.error("thread took to long to start")
        if not connected_ok:
            logger.error("BLE connection to BMS took to long to inititate")

    def initiate_ble_thread_main(self):
        asyncio.run(self.async_main(self.address))

    async def async_main(self, address):
        self.ble_async_thread_event_loop = asyncio.get_event_loop()
        self.ble_async_thread_ready.set()

        #try to connect over and over if the connection fails
        while self.main_thread.is_alive():
            await self.connect_to_bms(self.address)
            await asyncio.sleep(1)#sleep one second before trying to reconnecting

    def client_disconnected(self, client):
        logger.error("BMS disconnected")

    async def connect_to_bms(self, address):
        self.client = BleakClient(address, disconnected_callback=self.client_disconnected)
        try:
            logger.info("initiate BLE connection to: "+address)
            await self.client.connect()
            logger.info("connected")
            await self.client.start_notify(self.read_characteristic, self.notify_read_callback)

        except Exception as e:
            logger.error("Failed when trying to connect", e)
            return False
        finally:
            self.ble_connection_ready.set()
            while self.client.is_connected and self.main_thread.is_alive():
                await asyncio.sleep(0.1)
            await self.client.disconnect()

    #saves response and tells the command sender that the response has arived
    def notify_read_callback(self, sender, data: bytearray):
        self.response_data = data
        self.response_event.set()

    async def ble_thread_send_com(self, command):
        self.response_event = asyncio.Event()
        self.response_data = False
        await self.client.write_gatt_char(self.write_characteristic, command, True)
        await asyncio.wait_for(self.response_event.wait(), timeout=1)#Wait for the response notification
        self.response_event = False
        return self.response_data

    async def send_coroutine_to_ble_thread_and_wait_for_result(self, coroutine):
        bt_task = asyncio.run_coroutine_threadsafe(coroutine, self.ble_async_thread_event_loop)
        result = await asyncio.wait_for(asyncio.wrap_future(bt_task), timeout=1.5)
        return result

    def send_data(self, data):
        data = asyncio.run(self.send_coroutine_to_ble_thread_and_wait_for_result(self.ble_thread_send_com(data)))
        return data
