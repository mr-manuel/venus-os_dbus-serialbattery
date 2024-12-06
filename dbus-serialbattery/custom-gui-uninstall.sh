#!/bin/bash

# remove comment for easier troubleshooting
#set -x

# import functions
source /data/apps/dbus-serialbattery/functions.sh


# check if /service/gui exists
if [ -d "/service/gui" ]; then
    # nanopi, raspberrypi
    servicePath="/service/gui"
else
    # cerbo gx
    servicePath="/service/start-gui"
fi


echo "Restarting GUI..."

# stop gui
svc -d $servicePath

# sleep 1 sec
sleep 1

# unmount overlay filesystem
echo "Unmounting overlay filesystems..."
removeOverlay dbus-serialbattery_gui

# start gui
svc -u $servicePath
