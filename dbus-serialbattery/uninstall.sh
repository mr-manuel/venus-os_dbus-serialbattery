#!/bin/bash

# remove comment for easier troubleshooting
#set -x

# disable driver
bash /data/apps/dbus-serialbattery/disable.sh



read -r -p "Do you want to delete the install and configuration files in \"/data/apps/dbus-serialbattery\" and also the logs? If unsure, just press enter. [y/N] " response
echo
response=${response,,} # tolower
if [[ $response =~ ^([yY][eE][sS]|[yY])$ ]]; then
    # remove dbus-serialbattery folder
    rm -rf /data/apps/dbus-serialbattery

    # remove logs
    rm -rf /var/log/dbus-serialbattery.*
    rm -rf /var/log/dbus-blebattery.*
    rm -rf /var/log/dbus-canbattery.*

    echo "The folder \"/data/apps/dbus-serialbattery\" and the logs were removed."
    echo
fi


echo "Disabling or removing the overlay-fs app could cause other apps to stop working correctly. Please ensure that no other app is using it."

read -r -p "Do you want to disable the overlay-fs app? If unsure, just press enter. [y/N] " response
echo
response=${response,,} # tolower
if [[ $response =~ ^([yY][eE][sS]|[yY])$ ]]; then
    # remove dbus-serialbattery overlay-fs
    bash /data/apps/overlay-fs/uninstall.sh
fi



echo "The dbus-serialbattery driver was uninstalled. Please reboot."
echo
