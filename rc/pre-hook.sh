#!/bin/bash

# executed before archive extraction on USB install
# see https://github.com/victronenergy/meta-victronenergy/blob/15fa33c3e5430f7c08a688dc02171f5be9a81c84/meta-venus/recipes-core/initscripts/files/update-data.sh#L42


# import functions
source "$(dirname $0)/functions.sh"



# search for venus-data.tar.gz in USB root and copy it, if found
for dir in /media/*; do
    if [ -f "$dir/venus-data.tar.gz" ]; then
        break
    fi
done



# Initialize log
echo -e "\n\n\n" >> "$dir/venus-data_install.log" 2>&1
echo "$(date +%Y-%m-%d\ %H:%M:%S) INFO: *** Starting dbus-serialbattery installation! ***" >> "$dir/venus-data_install.log" 2>&1



# disable character display
disableCharacterDisplay

# Show notification to user
# LCD has 2 lines, 16 characters
# Installing dbus-
# serialbattery...
notify "Installing dbus-serialbattery..." --no-beep
