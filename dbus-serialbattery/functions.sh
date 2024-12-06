#!/bin/bash

# elaborate version string for better comparing
# https://github.com/kwindrem/SetupHelper/blob/ebaa65fcf23e2bea6797f99c1c41174143c1153c/updateFileSets#L56-L81
function versionStringToNumber ()
{
    local p4="" ; local p5="" ; local p5=""
    local major=""; local minor=""

	# first character should be 'v' so first awk parameter will be empty and is not prited into the read command
	#
	# version number formats: v2.40, v2.40~6, v2.40-large-7, v2.40~6-large-7
	# so we must adjust how we use paramters read from the version string
	# and parsed by awk
	# if no beta make sure release is greater than any beta (i.e., a beta portion of 999)

    read major minor p4 p5 p6 <<< $(echo $1 | awk -v FS='[v.~-]' '{print $2, $3, $4, $5, $6}')
	((versionNumber = major * 1000000000 + minor * 1000000))
	if [ -z $p4 ] || [ $p4 = "large" ]; then
        ((versionNumber += 999))
	else
		((versionNumber += p4))
    fi
	if [ ! -z $p4 ] && [ $p4 = "large" ]; then
		((versionNumber += p5 * 1000))
		large=$p5
	elif [ ! -z $p6 ]; then
		((versionNumber += p6 * 1000))
	fi
}


function checkOverlay ()
{
    if [ ! -d "/data/apps/overlay-fs" ]; then
        echo "ERROR: The overlay-fs app does not exist! Please run \"bash /data/apps/dbus-serialbattery/ext/venus-os_overlay-fs/install.sh\" once."
        exit 1
    fi


    # if ! bash /data/apps/overlay-fs/check-folder.sh "$2"; then
        if ! bash /data/apps/overlay-fs/add-app-and-directory.sh "$1" "$2"; then
            echo "ERROR: Could not add \"$2\" to overlay-fs!"
            exit 1
        fi
    # fi
}


function removeOverlay ()
{
    if [ ! -d "/data/apps/overlay-fs" ]; then
        echo "ERROR: The overlay-fs app does not exist! Please run \"bash /data/apps/dbus-serialbattery/ext/venus-os_overlay-fs/install.sh\" once."
        exit 1
    fi

    if ! bash /data/apps/overlay-fs/remove-app.sh "$1"; then
        echo "ERROR: Could not remove \"$1\" from overlay-fs!"
        exit 1
    fi
}
