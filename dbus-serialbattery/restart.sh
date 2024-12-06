#!/bin/bash

# remove comment for easier troubleshooting
#set -x

echo

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


# kill driver, if still running
pkill -f "python .*/dbus-serialbattery.py .*"



# get BMS list from config file
bluetooth_bms=$(awk -F "=" '/^BLUETOOTH_BMS/ {print $2}' /data/apps/dbus-serialbattery/config.ini)
# clear whitespaces
bluetooth_bms_clean=$(echo "$bluetooth_bms" | tr -d '[:space:]' | tr -s ',')
# split into array
IFS="," read -r -a bms_array <<< "$bluetooth_bms_clean"
# array length
bluetooth_length=${#bms_array[@]}
# restart bluetooth service, if Bluetooth BMS configured
if [ $bluetooth_length -gt 0 ]; then
    /etc/init.d/bluetooth restart
fi



# get a list of all dbus-serialbattery services and start them
for service in /service/dbus-serialbattery.*; do
    if [ -e "$service" ]; then
        echo "Starting $service..."
        svc -u "$service"
    fi
done
for service in /service/dbus-blebattery.*; do
    if [ -e "$service" ]; then
        echo "Starting $service..."
        svc -u "$service"
    fi
done
for service in /service/dbus-canbattery.*; do
    if [ -e "$service" ]; then
        echo "Starting $service..."
        svc -u "$service"
    fi
done

echo
