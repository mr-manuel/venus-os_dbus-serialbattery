Place test drivers and tools in this folder

Current options:
* Test Daly CAN by simulating a virtual device

## Daly CAN Simulator

Steps to start the simulator:
Add a virtual can port with
```
ip link add dev vcan0 type vcan
ip link set vcan0 down
ip link set vcan0 mtu 16
ip link set vcan0 up
```
start a manual run by 
```
cd /data/apps/dbus-serialbattery
./dbus-serialbattery.py vcan0
```
or add the vcan port in the config.ini and run enable.sh
```
CAN_PORT = vcan0
BATTERY_ADDRESSES =
BMS_TYPE = Daly_Can
./enable.sh
```
check log output
```
 tail -f /var/log/dbus-canbattery.vcan0/current | tai64nlocal
 ```
The simulator will show some static values to proof that the driver is working

## Add more here
...

