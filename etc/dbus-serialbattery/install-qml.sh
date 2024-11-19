#!/bin/bash

# remove comment for easier troubleshooting
#set -x

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


# count changed files
filesChanged=0


# GUI V1
if [ -d /opt/victronenergy/gui ]; then

    echo ""
    echo "Installing QML files for GUI V1..."

    # backup old PageBattery.qml once. New firmware upgrade will remove the backup
    if [ ! -f /opt/victronenergy/gui/qml/PageBattery.qml.backup ]; then
        echo "Backup old PageBattery.qml..."
        cp /opt/victronenergy/gui/qml/PageBattery.qml /opt/victronenergy/gui/qml/PageBattery.qml.backup
    fi
    # backup old PageBatteryParameters.qml once. New firmware upgrade will remove the backup
    if [ ! -f /opt/victronenergy/gui/qml/PageBatteryParameters.qml.backup ]; then
        echo "Backup old PageBatteryParameters.qml..."
        cp /opt/victronenergy/gui/qml/PageBatteryParameters.qml /opt/victronenergy/gui/qml/PageBatteryParameters.qml.backup
    fi
    # backup old PageBatterySettings.qml once. New firmware upgrade will remove the backup
    if [ ! -f /opt/victronenergy/gui/qml/PageBatterySettings.qml.backup ]; then
        echo "Backup old PageBatterySettings.qml..."
        cp /opt/victronenergy/gui/qml/PageBatterySettings.qml /opt/victronenergy/gui/qml/PageBatterySettings.qml.backup
    fi
    # backup old PageLynxIonIo.qml once. New firmware upgrade will remove the backup
    if [ ! -f /opt/victronenergy/gui/qml/PageLynxIonIo.qml.backup ]; then
        echo "Backup old PageLynxIonIo.qml..."
        cp /opt/victronenergy/gui/qml/PageLynxIonIo.qml /opt/victronenergy/gui/qml/PageLynxIonIo.qml.backup
    fi

    # copy new PageBattery.qml if changed
    if ! cmp -s /data/etc/dbus-serialbattery/qml/gui-v1/PageBattery.qml /opt/victronenergy/gui/qml/PageBattery.qml
    then
        echo "Copying PageBattery.qml..."
        cp /data/etc/dbus-serialbattery/qml/gui-v1/PageBattery.qml /opt/victronenergy/gui/qml/
        ((filesChanged++))
    fi

    # copy new PageBatteryCellVoltages if changed
    if ! cmp -s /data/etc/dbus-serialbattery/qml/gui-v1/PageBatteryCellVoltages.qml /opt/victronenergy/gui/qml/PageBatteryCellVoltages.qml
    then
        echo "Copying PageBatteryCellVoltages.qml..."
        cp /data/etc/dbus-serialbattery/qml/gui-v1/PageBatteryCellVoltages.qml /opt/victronenergy/gui/qml/
        ((filesChanged++))
    fi

    # copy new PageBatteryParameters.qml if changed
    if ! cmp -s /data/etc/dbus-serialbattery/qml/gui-v1/PageBatteryParameters.qml /opt/victronenergy/gui/qml/PageBatteryParameters.qml
    then
        echo "Copying PageBatteryParameters.qml..."
        cp /data/etc/dbus-serialbattery/qml/gui-v1/PageBatteryParameters.qml /opt/victronenergy/gui/qml/
        ((filesChanged++))
    fi

    # copy new PageBatterySettings.qml if changed
    if ! cmp -s /data/etc/dbus-serialbattery/qml/gui-v1/PageBatterySettings.qml /opt/victronenergy/gui/qml/PageBatterySettings.qml
    then
        echo "Copying PageBatterySettings.qml..."
        cp /data/etc/dbus-serialbattery/qml/gui-v1/PageBatterySettings.qml /opt/victronenergy/gui/qml/
        ((filesChanged++))
    fi

    # copy new PageLynxIonIo.qml if changed
    if ! cmp -s /data/etc/dbus-serialbattery/qml/gui-v1/PageLynxIonIo.qml /opt/victronenergy/gui/qml/PageLynxIonIo.qml
    then
        echo "Copying PageLynxIonIo.qml..."
        cp /data/etc/dbus-serialbattery/qml/gui-v1/PageLynxIonIo.qml /opt/victronenergy/gui/qml/
        ((filesChanged++))
    fi


    # get current Venus OS version
    versionStringToNumber $(head -n 1 /opt/victronenergy/version)
    ((venusVersionNumber = $versionNumber))

    # revert to VisualItemModel, if Venus OS older than v3.00~14 (v3.00~14 uses VisibleItemModel)
    versionStringToNumber "v3.00~14"

    # change in Victron directory, else the files are "broken" if upgrading from v2 to v3
    qmlDir="/opt/victronenergy/gui/qml"

    if (( $venusVersionNumber < $versionNumber )); then
        echo -n "Venus OS $(head -n 1 /opt/victronenergy/version) is older than v3.00~14. Replacing VisibleItemModel with VisualItemModel... "
        fileList="$qmlDir/PageBattery.qml"
        fileList+=" $qmlDir/PageBatteryCellVoltages.qml"
        fileList+=" $qmlDir/PageBatteryParameters.qml"
        fileList+=" $qmlDir/PageBatterySettings.qml"
        fileList+=" $qmlDir/PageBatterySetup.qml"
        fileList+=" $qmlDir/PageLynxIonIo.qml"
        for file in $fileList ; do
            sed -i -e 's/VisibleItemModel/VisualItemModel/' "$file"
        done
        echo "done."
    fi

fi


# GUI V2
if [ -d /opt/victronenergy/gui-v2 ]; then

    # COPY QML FILES for device screen
    echo ""
    echo "Installing QML files for GUI V2..."

    # backup old PageBattery.qml once. New firmware upgrade will remove the backup
    if [ ! -f /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBattery.qml.backup ]; then
        echo "Backup old PageBattery.qml..."
        cp /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBattery.qml /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBattery.qml.backup
    fi
    # backup old PageBatteryParameters.qml once. New firmware upgrade will remove the backup
    if [ ! -f /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBatteryParameters.qml.backup ]; then
        echo "Backup old PageBatteryParameters.qml..."
        cp /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBatteryParameters.qml /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBatteryParameters.qml.backup
    fi
    # backup old PageBatterySettings.qml once. New firmware upgrade will remove the backup
    if [ ! -f /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBatterySettings.qml.backup ]; then
        echo "Backup old PageBatterySettings.qml..."
        cp /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBatterySettings.qml /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBatterySettings.qml.backup
    fi
    # backup old PageLynxIonIo.qml once. New firmware upgrade will remove the backup
    if [ ! -f /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageLynxIonIo.qml.backup ]; then
        echo "Backup old PageLynxIonIo.qml..."
        cp /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageLynxIonIo.qml /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageLynxIonIo.qml.backup
    fi

    # copy new PageBattery.qml if changed
    if ! cmp -s /data/etc/dbus-serialbattery/qml/gui-v2/PageBattery.qml /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBattery.qml
    then
        echo "Copying PageBattery.qml..."
        cp /data/etc/dbus-serialbattery/qml/gui-v2/PageBattery.qml /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/
        ((filesChanged++))
    fi

    # copy new PageBatteryCellVoltages if changed
    if ! cmp -s /data/etc/dbus-serialbattery/qml/gui-v2/PageBatteryCellVoltages.qml /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/PageBatteryCellVoltages.qml
    then
        echo "Copying PageBatteryCellVoltages.qml..."
        cp /data/etc/dbus-serialbattery/qml/gui-v2/PageBatteryCellVoltages.qml /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/
        ((filesChanged++))
    fi

    # copy new PageBatteryParameters.qml if changed
    if ! cmp -s /data/etc/dbus-serialbattery/qml/gui-v2/PageBatteryParameters.qml /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/PageBatteryParameters.qml
    then
        echo "Copying PageBatteryParameters.qml..."
        cp /data/etc/dbus-serialbattery/qml/gui-v2/PageBatteryParameters.qml /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/
        ((filesChanged++))
    fi

    # copy new PageBatterySettings.qml if changed
    if ! cmp -s /data/etc/dbus-serialbattery/qml/gui-v2/PageBatterySettings.qml /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/PageBatterySettings.qml
    then
        echo "Copying PageBatterySettings.qml..."
        cp /data/etc/dbus-serialbattery/qml/gui-v2/PageBatterySettings.qml /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/
        ((filesChanged++))
    fi

    # copy new PageLynxIonIo.qml if changed
    if ! cmp -s /data/etc/dbus-serialbattery/qml/gui-v2/PageLynxIonIo.qml /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/PageLynxIonIo.qml
    then
        echo "Copying PageLynxIonIo.qml..."
        cp /data/etc/dbus-serialbattery/qml/gui-v2/PageLynxIonIo.qml /opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/
        ((filesChanged++))
    fi

fi


# DOWNLOAD AND INSTALL WASM BUILD
if [ -f "/var/www/venus/gui-v2/commit-sha" ]; then
    # check if latest version is already installed
    hash_local=$(cat /var/www/venus/gui-v2/commit-sha)
    hash_online=$(curl -s https://api.github.com/repos/mr-manuel/venus-os_dbus-serialbattery_gui-v2/commits?path=venus-webassembly.zip | grep "sha" | head -n 1 | cut -d : -f 2,3 | tr -d "\ " | tr -d \" | tr -d \,)

    if [ "$hash_local" != "$hash_online" ]; then
        install_wasm=1
    else
        install_wasm=0
    fi
else
    install_wasm=1
fi

if [ $install_wasm -eq 1 ]; then

    echo ""
    echo "Installing GUIv2 WASM build..."

    wget -q -O /tmp/venus-webassembly.zip https://raw.githubusercontent.com/mr-manuel/venus-os_dbus-serialbattery_gui-v2/master/venus-webassembly.zip

    # check if download was successful
    if [ ! -f "/tmp/venus-webassembly.zip" ]; then
        echo "** Download of GUIv2 failed! Skip installation. **"
        echo "For offline installing see https://github.com/mr-manuel/venus-os_dbus-serialbattery_gui-v2"
    else

        unzip -o /tmp/venus-webassembly.zip -d /tmp > /dev/null

        # remove unneeded files
        if [ -f "/tmp/wasm/Makefile" ]; then
            rm -f /tmp/wasm/Makefile
        fi

        # add commit-sha file
        echo $hash_online > /tmp/wasm/commit-sha

        # move original wasm build, if it's a folder
        if [ -d "/var/www/venus/gui-v2" ] && [ ! -L "/var/www/venus/gui-v2" ]; then
            mv /var/www/venus/gui-v2 /var/www/venus/gui-v2.bak
        # remove if it's a symlink
        elif [ -L "/var/www/venus/gui-v2" ]; then
            rm -f /var/www/venus/gui-v2
        fi
        mv /tmp/wasm /var/www/venus/gui-v2

        cd /var/www/venus/gui-v2

        # create missing files for VRM portal check
        if [ ! -f "venus-gui-v2.wasm.gz" ]; then
            echo "GZip WASM build..."
            gzip -k venus-gui-v2.wasm
            echo "Create SHA256 checksum..."
            sha256sum /var/www/venus/gui-v2/venus-gui-v2.wasm > /var/www/venus/gui-v2/venus-gui-v2.wasm.sha256
        fi

        rm -f /tmp/venus-webassembly.zip

    fi

fi


# if files changed, restart gui
if [ $filesChanged -gt 0 ]; then

    # check if /service/gui exists
    if [ -d "/service/gui" ]; then
        # nanopi, raspberrypi
        servicePath="/service/gui"
    else
        # cerbo gx
        servicePath="/service/start-gui"
    fi

    # stop gui
    svc -d $servicePath
    # sleep 1 sec
    sleep 1
    # start gui
    svc -u $servicePath
    echo "New QML files were installed and the GUI was restarted."
fi
