#!/bin/bash
#
# MIT License
#
# Copyright (c) 2024 github.com/mr-manuel
#
# Version: 0.0.1 (20241128)


echo
echo "Disabling overlay-fs app..."


path="/data/apps/overlay-fs/data"
resource_busy=0

# Read the config file and loop through each line
while IFS= read -r line; do
    # Ensure the line starts with /
    if [[ "$line" =~ ^\/ ]]; then
        # split $line on the first space, get the first two variables and ignore the rest
        IFS=' ' read -r lowerDir appNames other <<< "$line"

        overlayName="$(basename "$lowerDir")"

        if mountpoint -q "$lowerDir"; then
            echo "Unmounting bind overlay for ${lowerDir}"
            umount "$lowerDir"
            if [ $? -ne 0 ]; then
                resource_busy=1
            fi
        fi
        if mountpoint -q "${path}/$overlayName/merged"; then
            echo "Unmounting overlay for ${lowerDir}"
            umount "${path}/$overlayName/merged"
            if [ $? -ne 0 ]; then
                resource_busy=1
            fi
        fi

    fi
done < /data/apps/overlay-fs/overlay-fs.conf


# remove install script from rc.local
sed -i "/bash \/data\/apps\/overlay-fs\/enable.sh > \/data\/apps\/overlay-fs\/startup.log 2>&1/d" /data/rcS.local

echo "The overlay-fs was disabled".
echo

if [ $resource_busy -eq 1 ]; then
    echo "*** Some resources are busy and could not be unmounted. Please reboot to complete."
    echo
fi
