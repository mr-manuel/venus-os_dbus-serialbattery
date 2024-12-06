#!/bin/bash

# remove comment for easier troubleshooting
#set -x

# import functions
source /data/apps/dbus-serialbattery/functions.sh

echo
echo "Disabling dbus-serialbattery driver..."

echo "Remove serial starter configuration..."
# remove driver from serial starter
rm -f /data/conf/serial-starter.d/dbus-serialbattery.conf
# remove serial-starter.d if empty
if [ -d "/data/conf/serial-starter.d" ] && [ ! "$(ls -A "/data/conf/serial-starter.d")" ]; then
    rmdir "/data/conf/serial-starter.d"
fi



# stop serial starter to not block files
svc -d /service/serial-starter
sleep 1

# remove overlay-fs for service-templates
echo "Unmounting overlay filesystem for dbus-serialbattery..."
removeOverlay dbus-serialbattery

# start serial starter
svc -u /service/serial-starter



# restore GUI changes
bash /data/apps/dbus-serialbattery/custom-gui-uninstall.sh


# get a list of all dbus-serialbattery services and stop them
for service in /service/dbus-serialbattery.*; do
    if [ -e "$service" ]; then
        echo "Stopping $service..."
        svc -d "$service"
    fi
done
for service in /service/dbus-blebattery.*; do
    if [ -e "$service" ]; then
        echo "Stopping $service..."
        svc -d "$service"
    fi
done
for service in /service/dbus-canbattery.*; do
    if [ -e "$service" ]; then
        echo "Stopping $service..."
        svc -d "$service"
    fi
done


# wait shortly
sleep 1


# remove services
rm -rf /service/dbus-serialbattery.*
rm -rf /service/dbus-blebattery.*
rm -rf /service/dbus-canbattery.*


# kill driver, if still running
# serial
pkill -f "supervise dbus-serialbattery.*"
pkill -f "multilog .* /var/log/dbus-serialbattery.*"
pkill -f "python .*/dbus-serialbattery.py /dev/tty.*"
# bluetooth
pkill -f "supervise dbus-blebattery.*"
pkill -f "multilog .* /var/log/dbus-blebattery.*"
pkill -f "python .*/dbus-serialbattery.py .*_Ble.*"
# can
pkill -f "supervise dbus-canbattery.*"
pkill -f "multilog .* /var/log/dbus-canbattery.*"
pkill -f "python .*/dbus-serialbattery.py can.*"


# remove enable script from rc.local
sed -i "\;bash /data/apps/dbus-serialbattery/enable.sh > /data/apps/dbus-serialbattery/startup.log 2>&1 &;d" /data/rc.local


### needed for upgrading from older versions | start ###
# remove old drivers before changing from dbus-blebattery-$1 to dbus-blebattery.$1
rm -rf /service/dbus-blebattery-*
# remove old install script from rc.local
sed -i "/sh \/data\/etc\/dbus-serialbattery\/reinstalllocal.sh/d" /data/rc.local
sed -i "/sh \/data\/etc\/dbus-serialbattery\/reinstall-local.sh/d" /data/rc.local
sed -i "/bash \/data\/etc\/dbus-serialbattery\/reinstall-local.sh/d" /data/rc.local
# remove old entry from rc.local
sed -i "/sh \/data\/etc\/dbus-serialbattery\/installble.sh/d" /data/rc.local
### needed for upgrading from older versions | end ###

echo "The dbus-serialbattery driver was disabled".
echo
