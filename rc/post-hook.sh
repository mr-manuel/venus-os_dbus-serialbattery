#!/bin/bash

# executed after archive extraction on USB install
# see https://github.com/victronenergy/meta-victronenergy/blob/15fa33c3e5430f7c08a688dc02171f5be9a81c84/meta-venus/recipes-core/initscripts/files/update-data.sh#L43


# import functions
source "$(dirname $0)/functions.sh"



# search for venus-data.tar.gz in USB root and copy it, if found
for dir in /media/*; do
    if [ -f "$dir/venus-data.tar.gz" ]; then
        cp -f "$dir/venus-data.tar.gz" "/tmp/venus-data.tar.gz"
        break
    fi
done



# launch install script
if [ -f "/data/dbus-serialbattery/install.sh" ]; then
    # backup config.ini
    bash /data/dbus-serialbattery/install.sh --local >> "$dir/venus-data_install.log" 2>&1
    # remove temporary folder
    rm -rf "/data/dbus-serialbattery"
else
    echo "$(date +%Y-%m-%d\ %H:%M:%S) ERROR: install script not found!" >> "$dir/venus-data_install.log" 2>&1
    exit 1
fi



# search for config.ini in USB root and copy it, if found
for dir in /media/*; do
    if [ -f "$dir/config.ini" ]; then
        echo "$(date +%Y-%m-%d\ %H:%M:%S) INFO: Found config.ini on USB root!" >> "$dir/venus-data_install.log" 2>&1
        cp -f "$dir/config.ini" "/data/apps/dbus-serialbattery/config.ini"
        mv "$dir/config.ini" "$dir/config_installed.ini"
    fi
done



# rename the venus-data.tar.gz else the data is overwritten, if the USB is not removed
for dir in /media/*; do
    if [ -f "$dir/venus-data.tar.gz" ]; then
        echo "$(date +%Y-%m-%d\ %H:%M:%S) INFO: Renaming venus-data.tar.gz to venus-data_installed.tar.gz to prevent looping" >> "$dir/venus-data_install.log" 2>&1
        mv "$dir/venus-data.tar.gz" "$dir/venus-data_installed.tar.gz"
    fi
done



# Show notification to user
# Install finish!
# dbus-serialbatt
notify "Install finish!dbus-serialbatt" --count 2
sleep 60

# Enable character display
enableCharacterDisplay
