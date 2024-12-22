# dbus-serialbattery - standalone for BMS communication

The driver will communicate with a Battery Management System (BMS) that support serial (RS232, RS485 or TTL UART) and Bluetooth communication (see [BMS feature comparison](https://mr-manuel.github.io/venus-os_dbus-serialbattery_docs/general/features#bms-feature-comparison) for details). The data have to procced with your applicaiton. <br> The main purpose is to provide the BMS data of the supported BMS for other usage beside VenosOS.
Also for standalone BMS test (reading value) it can be useded.

A Test script is avalible
 
#### How it works
All voltages and currents in 100 notation: 27,41V = 2741 or 51.42A = 5142<br>
include <br>
from standalone_serialbattery import *<br>
in your project<br>
create an object with the parameters:<br>
sasb = standalone_serialbattery(DEVPATH, 0, "", LOGLEVEL)<br>

` __init__(self, devpath, driverOption, devadr, loglevel):` <br>
 devpath:  Add the /dev/tty device here, mostly .../dev/ttyUSB0, if empty default path /dev/ttyUSB0 is used

driverOption:
0 : autotetect for all non BT / CAN devices<br>
1 : JKBMS bluettooth - Jkbms_Ble<br>
2 : JDB bluetooth    - LltJbd_Ble<br>
3 : LiTime bluetooth - LiTime_Ble<br>
10: CAN devices for JKBAMS and DALY<br>

devadr: bluetooth address as string or "" empty for all non bluetooth devices

`sasb.bms_open()` <br>
`ST = sasb.bms_read()` <br>

Access the values directly:<br>
`sasb.cell_count`<br> 
`sasb.cells[Nr_of_Cell]`<br> 
`sasb.temperature_fet`<br>
`sasb.temperature_1`<br>
`sasb.temperature_2`<br>
`sasb.voltage`<br>
`sasb.act_current`<br>
`sasb.soc`<br>

or

access via list<br>
`ST[0]` = cellcount<br>
`ST[1]` = Cellvoltage of cell 1<br>
`ST[0..cellcount]` = Cellvoltage of cell x<br>
`ST[cellcount + 1]` = Temperature_Fet<br>
`ST[cellcount + 2]` = Temperature_1<br>
`ST[cellcount + 3]` = Temperature_2<br>
`ST[cellcount + 4]` = BatVolt<br>
`ST[cellcount + 5]` = Current<br>
`ST[cellcount + 6]` = SOC<br>

