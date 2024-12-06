#!/bin/bash

# remove comment for easier troubleshooting
#set -x

# import functions
source /data/apps/dbus-serialbattery/functions.sh


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


# GUI V1
if [ -d "$pathGuiV1" ]; then

    if [ $overlayGuiV1StatusCode -eq 1 ]; then
        echo "ERROR: Could not mount overlay for $pathGuiV1"
        echo "QML files were not installed."
    elif [ $overlayGuiV1StatusCode -eq 2 ]; then
        echo "GUIv1 is not installed on this system."
        echo "QML files are not needed."
    else

        echo ""
        echo "Installing QML files for GUI V1..."

        # copy new PageBattery.qml if changed
        if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v1/PageBattery.qml" "$pathGuiV1/qml/PageBattery.qml"
        then
            echo "Copying PageBattery.qml..."
            cp "/data/apps/dbus-serialbattery/qml/gui-v1/PageBattery.qml" "$pathGuiV1/qml/"
            ((filesChanged++))
        fi

        # copy new PageBatteryCellVoltages if changed
        if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v1/PageBatteryCellVoltages.qml" "$pathGuiV1/qml/PageBatteryCellVoltages.qml"
        then
            echo "Copying PageBatteryCellVoltages.qml..."
            cp "/data/apps/dbus-serialbattery/qml/gui-v1/PageBatteryCellVoltages.qml" "$pathGuiV1/qml/"
            ((filesChanged++))
        fi

        # copy new PageBatteryParameters.qml if changed
        if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v1/PageBatteryParameters.qml" "$pathGuiV1/qml/PageBatteryParameters.qml"
        then
            echo "Copying PageBatteryParameters.qml..."
            cp "/data/apps/dbus-serialbattery/qml/gui-v1/PageBatteryParameters.qml" "$pathGuiV1/qml/"
            ((filesChanged++))
        fi

        # copy new PageBatterySettings.qml if changed
        if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v1/PageBatterySettings.qml" "$pathGuiV1/qml/PageBatterySettings.qml"
        then
            echo "Copying PageBatterySettings.qml..."
            cp "/data/apps/dbus-serialbattery/qml/gui-v1/PageBatterySettings.qml" "$pathGuiV1/qml/"
            ((filesChanged++))
        fi

        # copy new PageLynxIonIo.qml if changed
        if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v1/PageLynxIonIo.qml" "$pathGuiV1/qml/PageLynxIonIo.qml"
        then
            echo "Copying PageLynxIonIo.qml..."
            cp "/data/apps/dbus-serialbattery/qml/gui-v1/PageLynxIonIo.qml" "$pathGuiV1/qml/"
            ((filesChanged++))
        fi


        # get current Venus OS version
        versionStringToNumber $(head -n 1 /opt/victronenergy/version)
        ((venusVersionNumber = $versionNumber))

        # Some class names changed with this Venus OS version
        versionStringToNumber "v3.00~14"

        # change files in the destination folder, else the files are "broken" if upgrading to a the newer Venus OS version
        qmlDir="$pathGuiV1/qml"

        if (( $venusVersionNumber < $versionNumber )); then
            echo -n "Venus OS $(head -n 1 /opt/victronenergy/version) is older than v3.00~14. Fixing class names... "
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

        # COPY QML FILES for device screen
        echo ""
        echo "Installing QML files for GUI V2..."

        # copy new PageBattery.qml if changed
        if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v2/PageBattery.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBattery.qml"
        then
            echo "Copying PageBattery.qml..."
            cp "/data/apps/dbus-serialbattery/qml/gui-v2/PageBattery.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/"
            ((filesChanged++))
        fi

        # copy new PageBatteryCellVoltages if changed
        if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v2/PageBatteryCellVoltages.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBatteryCellVoltages.qml"
        then
            echo "Copying PageBatteryCellVoltages.qml..."
            cp "/data/apps/dbus-serialbattery/qml/gui-v2/PageBatteryCellVoltages.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/"
            ((filesChanged++))
        fi

        # copy new PageBatteryParameters.qml if changed
        if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v2/PageBatteryParameters.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBatteryParameters.qml"
        then
            echo "Copying PageBatteryParameters.qml..."
            cp "/data/apps/dbus-serialbattery/qml/gui-v2/PageBatteryParameters.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/"
            ((filesChanged++))
        fi

        # copy new PageBatterySettings.qml if changed
        if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v2/PageBatterySettings.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageBatterySettings.qml"
        then
            echo "Copying PageBatterySettings.qml..."
            cp "/data/apps/dbus-serialbattery/qml/gui-v2/PageBatterySettings.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/"
            ((filesChanged++))
        fi

        # copy new PageLynxIonIo.qml if changed
        if ! cmp -s "/data/apps/dbus-serialbattery/qml/gui-v2/PageLynxIonIo.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/PageLynxIonIo.qml"
        then
            echo "Copying PageLynxIonIo.qml..."
            cp "/data/apps/dbus-serialbattery/qml/gui-v2/PageLynxIonIo.qml" "/opt/victronenergy/gui-v2/Victron/VenusOS/pages/settings/devicelist/battery/"
            ((filesChanged++))
        fi


        # get current Venus OS version
        versionStringToNumber $(head -n 1 /opt/victronenergy/version)
        ((venusVersionNumber = $versionNumber))

        # Some class names changed with this Venus OS version
        versionStringToNumber "v3.60~8"

        # change files in the destination folder, else the files are "broken" if upgrading to a the newer Venus OS version
        qmlDir="$pathGuiV2/Victron/VenusOS/pages/settings/devicelist/battery"

        if (( $venusVersionNumber < $versionNumber )); then
            echo -n "Venus OS $(head -n 1 /opt/victronenergy/version) is older than v3.60~8. Fixing class names... "
            fileList="$qmlDir/PageBattery.qml"
            fileList+=" $qmlDir/PageBatteryCellVoltages.qml"
            fileList+=" $qmlDir/PageBatteryParameters.qml"
            fileList+=" $qmlDir/PageBatterySettings.qml"
            fileList+=" $qmlDir/PageLynxIonIo.qml"
            for file in $fileList ; do
                sed -i -e 's/ListText {/ListTextItem {/' "$file"
                sed -i -e 's/ListQuantity {/ListQuantityItem {/' "$file"
                sed -i -e 's/ListTemperature {/ListTemperatureItem {/' "$file"
                sed -i -e 's/ListNavigation {/ListNavigationItem {/' "$file"
                sed -i -e 's/PrimaryListLabel {/ListLabel {/' "$file"
                sed -i -e 's/ListText {/ListTextItem {/' "$file"
            done
        fi

        echo "done."

    fi

fi


# INSTALL WASM BUILD

hash_installed=$(cat /var/www/venus/gui-v2/venus-gui-v2.wasm.sha256)
hash_online=$(curl -s https://raw.githubusercontent.com/mr-manuel/venus-os_dbus-serialbattery_gui-v2/refs/heads/master/venus-gui-v2.wasm.sha256)

# Check if hash_online contains "venus-gui-v2.wasm", if not the online request failed
if [[ "$hash_online" == *"venus-gui-v2.wasm"* ]]; then

    # Check if latest version is already available offline
    if [ "$hash_installed" != "$hash_online" ]; then

        # Download new version
        echo "New version of GUIv2 web version available. Downloading..."
        if [ ! -d "/data/apps/dbus-serialbattery/ext/venus-os_dbus-serialbattery_gui-v2" ]; then
            mkdir -p /data/apps/dbus-serialbattery/ext/venus-os_dbus-serialbattery_gui-v2
        fi

        wget -q -O /data/apps/dbus-serialbattery/ext/venus-os_dbus-serialbattery_gui-v2/venus-webassembly.zip https://raw.githubusercontent.com/mr-manuel/venus-os_dbus-serialbattery_gui-v2/refs/heads/master/venus-webassembly.zip

        # check if download was successful
        if [ $? -ne 0 ]; then
            echo "ERROR: Download of GUIv2 web version failed."
        else
            wget -q -O /data/apps/dbus-serialbattery/ext/venus-os_dbus-serialbattery_gui-v2/venus-gui-v2.wasm.sha256 https://raw.githubusercontent.com/mr-manuel/venus-os_dbus-serialbattery_gui-v2/refs/heads/master/venus-gui-v2.wasm.sha256

            # check if download was successful
            if [ $? -ne 0 ]; then
                echo "ERROR: Download of hash file for GUIv2 web version failed."
            fi
        fi

    fi

fi

# Check if offline version is already installed
hash_available=$(cat /data/apps/dbus-serialbattery/ext/venus-os_dbus-serialbattery_gui-v2/venus-gui-v2.wasm.sha256)
if [ "$hash_installed" != "$hash_available" ]; then

    if [ $overlayWwwStatusCode -eq 1 ]; then
        echo "ERROR: Could not mount overlay for /var/www/venus"
        echo "GUIv2 web version was not installed."
    else

        echo ""
        echo "Installing GUIv2 web version..."

        # Check if file is available
        if [ ! -f "/data/apps/dbus-serialbattery/ext/venus-os_dbus-serialbattery_gui-v2/venus-webassembly.zip" ]; then
            echo "ERROR: GUIv2 web version not found."
        else

            unzip -o /data/apps/dbus-serialbattery/ext/venus-os_dbus-serialbattery_gui-v2/venus-webassembly.zip -d /tmp > /dev/null

            # remove unneeded files
            if [ -f "/tmp/wasm/Makefile" ]; then
                rm -f /tmp/wasm/Makefile
            fi

            if [ -d "/var/www/venus/gui-v2" ] && [ ! -L "/var/www/venus/gui-v2" ]; then
                pathGuiWww="/var/www/venus/gui-v2"
            elif [ -d "/var/www/venus/gui-beta" ] && [ ! -L "/var/www/venus/gui-beta" ]; then
                pathGuiWww="/var/www/venus/gui-beta"
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

            echo "done."

        fi

    fi

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
fi

echo
