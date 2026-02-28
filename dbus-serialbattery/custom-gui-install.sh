#!/bin/bash

# remove comment for easier troubleshooting
#set -x

# import functions
source /data/apps/dbus-serialbattery/functions.sh


# get current Venus OS version
venusVersionNumber=$(versionStringToNumber "$(head -n 1 /opt/victronenergy/version)")

# count changed files
filesChanged=0


# Mount overlay-fs
# Check if path for GUIv1 exists
if [ -d "/opt/victronenergy/gui" ]; then
    pathGuiV1="/opt/victronenergy/gui"
elif [ -d "/opt/victronenergy/gui-v1" ]; then
    pathGuiV1="/opt/victronenergy/gui-v1"
fi
if [ "$pathGuiV1" ]; then
    checkOverlay dbus-serialbattery_gui "$pathGuiV1"
    if [ $? -eq 0 ]; then
        overlayGuiV1StatusCode=0
    else
        overlayGuiV1StatusCode=1
    fi
else
    overlayGuiV1StatusCode=2
fi

# Check if path for GUIv2 exists
if [ -d "/opt/victronenergy/gui-v2" ]; then
    pathGuiV2="/opt/victronenergy/gui-v2"
fi
if [ "$pathGuiV2" ]; then
    checkOverlay dbus-serialbattery_gui "$pathGuiV2"
    if [ $? -eq 0 ]; then
        overlayGuiV2StatusCode=0
    else
        overlayGuiV2StatusCode=1
    fi
else
    overlayGuiV2StatusCode=2
fi


checkOverlay dbus-serialbattery_gui /var/www/venus
if [ $? -eq 0 ]; then
    overlayWwwStatusCode=0
else
    overlayWwwStatusCode=1
fi
echo ""


# GUI V1
if [ -d "$pathGuiV1" ]; then

    if [ $overlayGuiV1StatusCode -eq 1 ]; then
        echo "ERROR: Could not mount overlay for $pathGuiV1"
        echo "QML files were not installed."
    elif [ $overlayGuiV1StatusCode -eq 2 ]; then
        echo "GUIv1 is not installed on this system."
        echo "QML files are not needed."
    else

        # Copy QML files for device screen
        echo "Installing QML files for GUI v1..."


        # copy new PageBattery.qml if changed
        if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v1/PageBattery.qml" "$pathGuiV1/qml/PageBattery.qml"
        then
            echo "|- Copying PageBattery.qml..."
            cp "/data/apps/dbus-serialbattery/qml/gui-v1/PageBattery.qml" "$pathGuiV1/qml/"
            ((filesChanged++))
        fi

        # copy new PageBatteryCellVoltages if changed
        if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v1/PageBatteryCellVoltages.qml" "$pathGuiV1/qml/PageBatteryCellVoltages.qml"
        then
            echo "|- Copying PageBatteryCellVoltages.qml..."
            cp "/data/apps/dbus-serialbattery/qml/gui-v1/PageBatteryCellVoltages.qml" "$pathGuiV1/qml/"
            ((filesChanged++))
        fi

        # copy new PageBatteryParameters.qml if changed
        if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v1/PageBatteryParameters.qml" "$pathGuiV1/qml/PageBatteryParameters.qml"
        then
            echo "|- Copying PageBatteryParameters.qml..."
            cp "/data/apps/dbus-serialbattery/qml/gui-v1/PageBatteryParameters.qml" "$pathGuiV1/qml/"
            ((filesChanged++))
        fi

        # copy new PageBatterySettings.qml if changed
        if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v1/PageBatterySettings.qml" "$pathGuiV1/qml/PageBatterySettings.qml"
        then
            echo "|- Copying PageBatterySettings.qml..."
            cp "/data/apps/dbus-serialbattery/qml/gui-v1/PageBatterySettings.qml" "$pathGuiV1/qml/"
            ((filesChanged++))
        fi

        # copy new PageLynxIonIo.qml if changed
        if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v1/PageLynxIonIo.qml" "$pathGuiV1/qml/PageLynxIonIo.qml"
        then
            echo "|- Copying PageLynxIonIo.qml..."
            cp "/data/apps/dbus-serialbattery/qml/gui-v1/PageLynxIonIo.qml" "$pathGuiV1/qml/"
            ((filesChanged++))
        fi


        # change files in the destination folder, else the files are "broken" if upgrading to a the newer Venus OS version
        qmlDir="$pathGuiV1/qml"

        # QtQick version changed with this Venus OS version
        if (( $venusVersionNumber < $(versionStringToNumber "v3.60~18") )); then
            echo "|- Venus OS $(head -n 1 /opt/victronenergy/version) is older than v3.60~18. Fixing QtQuick version... "
            fileList="$qmlDir/PageBattery.qml"
            fileList+=" $qmlDir/PageBatteryCellVoltages.qml"
            fileList+=" $qmlDir/PageBatteryParameters.qml"
            fileList+=" $qmlDir/PageBatterySettings.qml"
            fileList+=" $qmlDir/PageLynxIonIo.qml"
            for file in $fileList ; do
                sed -i -e 's/QtQuick 2/QtQuick 1.1/' "$file"
            done
        fi

        # Some class names changed with this Venus OS version
        if (( $venusVersionNumber < $(versionStringToNumber "v3.00~14") )); then
            echo "|- Venus OS $(head -n 1 /opt/victronenergy/version) is older than v3.00~14. Fixing class names... "
            fileList="$qmlDir/PageBattery.qml"
            fileList+=" $qmlDir/PageBatteryCellVoltages.qml"
            fileList+=" $qmlDir/PageBatteryParameters.qml"
            fileList+=" $qmlDir/PageBatterySettings.qml"
            fileList+=" $qmlDir/PageLynxIonIo.qml"
            for file in $fileList ; do
                sed -i -e 's/VisibleItemModel/VisualItemModel/' "$file"
            done
        fi

        echo "done."

    fi

    echo ""

fi


# GUI V2
if [ -d "$pathGuiV2" ]; then

    if [ $overlayGuiV2StatusCode -eq 1 ]; then
        echo "ERROR: Could not mount overlay for /opt/victronenergy/gui-v2"
        echo "QML files were not installed."
    elif [ $overlayGuiV2StatusCode -eq 2 ]; then
        echo "GUIv2 is not installed on this system."
        echo "QML files are not needed."
    else

        # Copy QML files for device screen
        echo "Installing QML files for GUI v2..."

        # Check if Venus OS version is supported
        if (( $venusVersionNumber <= $(versionStringToNumber "v3.59") )); then
            # echo "|- Venus OS $(head -n 1 /opt/victronenergy/version) is equal or older than v3.59."
            sourceQmlDir="3.5x"
            installGuiV2Check=0
        elif (( $venusVersionNumber <= $(versionStringToNumber "v3.69") )); then
            # echo "|- Venus OS $(head -n 1 /opt/victronenergy/version) is part of v3.6x."
            sourceQmlDir="3.6x"
            installGuiV2Check=0
        elif (( $venusVersionNumber <= $(versionStringToNumber "v3.79") )); then
            # echo "|- Venus OS $(head -n 1 /opt/victronenergy/version) is part of v3.7x."
            sourceQmlDir="3.7x"
            installGuiV2Check=0
        elif (( $venusVersionNumber <= $(versionStringToNumber "v3.89") )); then
            # echo "|- Venus OS $(head -n 1 /opt/victronenergy/version) is part of v3.8x."
            sourceQmlDir="3.8x"
            installGuiV2Check=0
        else
            echo "|- >>> WARNING: GUIv2 installation for local display NOT SUPPORTED"
            echo "|- >>>          Your Venus OS version $(head -n 1 /opt/victronenergy/version) is NOT SUPPORTED by this version of the driver."
            echo "|- >>>          Update to the latest available driver to solve this issue. If you are using"
            echo "|- >>>          Venus OS beta, please use the latest nightly or beta version of the driver."
            installGuiV2Check=1
        fi

        if [ $installGuiV2Check -eq 0 ]; then
            # copy new PageBattery.qml if changed
            if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v2/${sourceQmlDir}/PageBattery.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBattery.qml"
            then
                echo "|- Copying PageBattery.qml..."
                cp "/data/apps/dbus-serialbattery/qml/gui-v2/${sourceQmlDir}/PageBattery.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/"
                ((filesChanged++))
            fi

            # copy new PageBatteryDbusSerialbattery if changed
            if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v2/${sourceQmlDir}/PageBatteryDbusSerialbattery.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBatteryDbusSerialbattery.qml"
            then
                echo "|- Copying PageBatteryDbusSerialbattery.qml..."
                cp "/data/apps/dbus-serialbattery/qml/gui-v2/${sourceQmlDir}/PageBatteryDbusSerialbattery.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/"
                ((filesChanged++))
            fi

            # copy new PageBatteryDbusSerialbatteryCellVoltages if changed
            if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v2/${sourceQmlDir}/PageBatteryDbusSerialbatteryCellVoltages.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBatteryDbusSerialbatteryCellVoltages.qml"
            then
                echo "|- Copying PageBatteryDbusSerialbatteryCellVoltages.qml..."
                cp "/data/apps/dbus-serialbattery/qml/gui-v2/${sourceQmlDir}/PageBatteryDbusSerialbatteryCellVoltages.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/"
                ((filesChanged++))
            fi

            # copy new PageBatteryDbusSerialbatterySettings if changed
            if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v2/${sourceQmlDir}/PageBatteryDbusSerialbatterySettings.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBatteryDbusSerialbatterySettings.qml"
            then
                echo "|- Copying PageBatteryDbusSerialbatterySettings.qml..."
                cp "/data/apps/dbus-serialbattery/qml/gui-v2/${sourceQmlDir}/PageBatteryDbusSerialbatterySettings.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/"
                ((filesChanged++))
            fi

            # copy new PageBatteryDbusSerialbatteryTimeToSoc if changed
            if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v2/${sourceQmlDir}/PageBatteryDbusSerialbatteryTimeToSoc.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBatteryDbusSerialbatteryTimeToSoc.qml"
            then
                echo "|- Copying PageBatteryDbusSerialbatteryTimeToSoc.qml..."
                cp "/data/apps/dbus-serialbattery/qml/gui-v2/${sourceQmlDir}/PageBatteryDbusSerialbatteryTimeToSoc.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/"
                ((filesChanged++))
            fi

            # delete old PageBatteryCellVoltages if present
            if [ -f "/data/apps/overlay-fs/data/gui-v2/upper/Victron/VenusOS/pages/settings/devicelist/battery/PageBatteryCellVoltages.qml" ]; then
                echo "|- Deleting old PageBatteryCellVoltages.qml..."
                rm -f "/data/apps/overlay-fs/data/gui-v2/upper/Victron/VenusOS/pages/settings/devicelist/battery/PageBatteryCellVoltages.qml"
            fi

            # delete old PageBatteryParameters.qml if present
            if [ -f "/data/apps/overlay-fs/data/gui-v2/upper/Victron/VenusOS/pages/settings/devicelist/battery/PageBatteryParameters.qml" ]; then
                echo "|- Deleting old PageBatteryParameters.qml..."
                rm -f "/data/apps/overlay-fs/data/gui-v2/upper/Victron/VenusOS/pages/settings/devicelist/battery/PageBatteryParameters.qml"
            fi

            # delete old PageBatterySettings.qml if present
            if [ -f "/data/apps/overlay-fs/data/gui-v2/upper/Victron/VenusOS/pages/settings/devicelist/battery/PageBatterySettings.qml" ]; then
                echo "|- Deleting old PageBatterySettings.qml..."
                rm -f "/data/apps/overlay-fs/data/gui-v2/upper/Victron/VenusOS/pages/settings/devicelist/battery/PageBatterySettings.qml"
            fi

            # delete old PageLynxIonIo.qml if present
            if [ -f "/data/apps/overlay-fs/data/gui-v2/upper/Victron/VenusOS/pages/settings/devicelist/battery/PageLynxIonIo.qml" ]; then
                echo "|- Deleting old PageLynxIonIo.qml..."
                rm -f "/data/apps/overlay-fs/data/gui-v2/upper/Victron/VenusOS/pages/settings/devicelist/battery/PageLynxIonIo.qml"
            fi


            # change files in the destination folder, else the files are "broken" if upgrading to a the newer Venus OS version
            qmlDir="$pathGuiV2/Victron/VenusOS/pages/settings/devicelist/battery"

            # Some property names changed with this Venus OS version
            # NOTE: currently only preserved for future use and not reachable in code
            if (( $venusVersionNumber < $(versionStringToNumber "v0.10~1") )); then
                echo "|- Venus OS $(head -n 1 /opt/victronenergy/version) is older than v3.60~25. Fixing object names... "
                fileList="$qmlDir/PageBattery.qml"
                fileList+=" $qmlDir/PageBatteryDbusSerialbattery.qml"
                fileList+=" $qmlDir/PageBatteryDbusSerialbatteryCellVoltages.qml"
                fileList+=" $qmlDir/PageBatteryDbusSerialbatterySettings.qml"
                fileList+=" $qmlDir/PageBatteryDbusSerialbatteryTimeToSoc.qml"
                for file in $fileList ; do
                    sed -i -e 's/model: ObjectModel/model: VisibleItemModel/' "$file"
                done
            fi

            echo "done."

        fi

    fi

    echo ""

fi


# if files changed, restart gui
if [ $filesChanged -gt 0 ]; then

    # check if /service/gui exists
    if [ -d "/service/gui" ]; then
        # Nanopi, Raspberrypi
        servicePath="/service/gui"
    else
        # Cerbo GX, Ekrano GX
        servicePath="/service/start-gui"
    fi

    # stop gui
    svc -d $servicePath
    # sleep 1 sec
    sleep 1
    # start gui
    svc -u $servicePath
    echo "New QML files were installed and the GUI was restarted."
    echo ""
fi


# INSTALL WASM BUILD
if [ -d "/var/www/venus/gui-v2" ] && [ ! -L "/var/www/venus/gui-v2" ]; then
    pathGuiWww="/var/www/venus/gui-v2"
elif [ -d "/var/www/venus/gui-beta" ] && [ ! -L "/var/www/venus/gui-beta" ]; then
    pathGuiWww="/var/www/venus/gui-beta"
else
    echo "GUIv2 web version not compatible with current Venus OS version. Skipping installation."
    echo ""
    exit
fi

# Get current hash of installed GUIv2 web version
if [ -f "$pathGuiWww/venus-gui-v2.wasm.sha256" ]; then
    hash_installed=$(cat "$pathGuiWww/venus-gui-v2.wasm.sha256")
else
    hash_installed="no hash installed"
fi

# Install if there is a matching Venus OS version
if (( $venusVersionNumber <= $(versionStringToNumber "v3.59") )); then
    # echo "Venus OS $(head -n 1 /opt/victronenergy/version) is equal or older than v3.59."
    webAssemblyPath="/data/apps/dbus-serialbattery/ext/venus-os_dbus-serialbattery_gui-v2/archive/venus-os_v3.5x"
    webAssemblyBeta=0
    installGuiV2WasmCheck=0
elif (( $venusVersionNumber <= $(versionStringToNumber "v3.69") )); then
    # echo "Venus OS $(head -n 1 /opt/victronenergy/version) is part of v3.6x."
    webAssemblyPath="/data/apps/dbus-serialbattery/ext/venus-os_dbus-serialbattery_gui-v2/archive/venus-os_v3.6x"
    webAssemblyBeta=0
    installGuiV2WasmCheck=0
elif (( $venusVersionNumber <= $(versionStringToNumber "v3.79") )); then
    # echo "Venus OS $(head -n 1 /opt/victronenergy/version) is part of v3.7x."
    webAssemblyPath="/data/apps/dbus-serialbattery/ext/venus-os_dbus-serialbattery_gui-v2/archive/venus-os_v3.7x"
    webAssemblyBeta=0
    installGuiV2WasmCheck=0
elif (( $venusVersionNumber <= $(versionStringToNumber "v3.89") )); then
    # echo "Venus OS $(head -n 1 /opt/victronenergy/version) is part of v3.8x."
    webAssemblyPath="/data/apps/dbus-serialbattery/ext/venus-os_dbus-serialbattery_gui-v2/"
    webAssemblyBeta=1
    installGuiV2WasmCheck=0
else
    installGuiV2WasmCheck=1
fi


# Only check for online version, if the Venus OS version matches the v3.8x (current Venus OS beta)
if [ $webAssemblyBeta -eq 1 ]; then
    hash_online=$(curl -s "https://raw.githubusercontent.com/mr-manuel/venus-os_dbus-serialbattery_gui-v2/refs/heads/master/venus-gui-v2.wasm.sha256")

    # Check if hash_online contains "venus-gui-v2.wasm", if not the online request failed
    if [[ "$hash_online" == *"venus-gui-v2.wasm"* ]]; then

        # Check if latest version is already available offline
        if [ "$hash_installed" != "$hash_online" ]; then

            # Download new version
            echo "New version of GUIv2 web version available. Downloading..."
            if [ ! -d "${webAssemblyPath}" ]; then
                mkdir -p "${webAssemblyPath}"
            fi

            wget -q -O "${webAssemblyPath}/venus-webassembly.zip" "https://raw.githubusercontent.com/mr-manuel/venus-os_dbus-serialbattery_gui-v2/refs/heads/master/venus-webassembly.zip"

            # check if download was successful
            if [ $? -ne 0 ]; then
                echo "ERROR: Download of GUIv2 web version failed."
            else
                wget -q -O "${webAssemblyPath}/venus-gui-v2.wasm.sha256" "https://raw.githubusercontent.com/mr-manuel/venus-os_dbus-serialbattery_gui-v2/refs/heads/master/venus-gui-v2.wasm.sha256"

                # check if download was successful
                if [ $? -ne 0 ]; then
                    echo "ERROR: Download of hash file for GUIv2 web version failed."
                else
                    echo "Download of GUIv2 web version successful."
                fi
            fi

        else
            echo "Latest version of GUIv2 web version is already downloaded."
        fi

    else
        echo "WARNING: Download of hash file for GUIv2 web version failed. Are you connected to the internet? If you are offline, you can ignore this message."
    fi

    echo ""

fi


# Install GUIv2 web version if Venus OS version matches
if [ $installGuiV2WasmCheck -eq 0 ]; then
    # Check if version is already installed
    if [ -f "${webAssemblyPath}/venus-gui-v2.wasm.sha256" ]; then
        hash_available=$(cat "${webAssemblyPath}/venus-gui-v2.wasm.sha256")
    else
        hash_available="no hash available"
    fi
    if [ "$hash_installed" != "$hash_available" ]; then

        if [ $overlayWwwStatusCode -eq 1 ]; then
            echo "ERROR: Could not mount overlay for /var/www/venus"
            echo "GUIv2 web version was not installed."
        else

            echo "Installing GUIv2 web version..."

            # Check if file is available
            if [ ! -f "${webAssemblyPath}/venus-webassembly.zip" ]; then
                echo "ERROR: GUIv2 web version not found."
            else

                unzip -o ${webAssemblyPath}/venus-webassembly.zip -d /tmp > /dev/null

                # remove unneeded files
                if [ -f "/tmp/wasm/Makefile" ]; then
                    rm -f /tmp/wasm/Makefile
                fi

                # "remove" old files
                if [ -d "$pathGuiWww" ]; then
                    rm -rf "$pathGuiWww"
                fi
                mv /tmp/wasm "$pathGuiWww"

                cd "$pathGuiWww"

                # create missing files for VRM portal check
                if [ ! -f "venus-gui-v2.wasm.gz" ]; then
                    echo "GZip WASM build..."
                    gzip -k venus-gui-v2.wasm
                    # echo "Create SHA256 checksum..."
                    # sha256sum venus-gui-v2.wasm > venus-gui-v2.wasm.sha256
                    rm -f venus-gui-v2.wasm
                fi

                rm -f /tmp/venus-webassembly.zip

                echo "Restart vrmlogger to make GUIv2 changes visible in VRM Portal..."
                svc -t /service/vrmlogger

                echo "done."

            fi

        fi
    else
        echo "Latest version of GUIv2 web version is already installed."
    fi
else
    echo ">>> ERROR: GUIv2 installation for local display FAILED"
    echo ">>>        Your Venus OS version $(head -n 1 /opt/victronenergy/version) is NOT SUPPORTED by this version of the driver."
    echo ">>>        Update to the latest available driver to solve this issue. If you are using"
    echo ">>>        Venus OS beta, please use the latest beta or nightly version of driver."
fi

echo ""


# FOR TESTING PURPOSES ONLY
#
# echo $venusVersionNumber
# venusVersionNumber=3055000999
# venusVersionNumber=3063000999
# venusVersionNumber=3070000011
# venusVersionNumber=3080000001
