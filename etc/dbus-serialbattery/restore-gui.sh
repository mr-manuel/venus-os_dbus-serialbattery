#!/bin/bash

# remove comment for easier troubleshooting
#set -x

# restore original backup
if [ -f /opt/victronenergy/gui/qml/PageBattery.qml.backup ]; then
    cp -f /opt/victronenergy/gui/qml/PageBattery.qml.backup /opt/victronenergy/gui/qml/PageBattery.qml
    echo "PageBattery.qml was restored."
fi
# restore original backup
if [ -f /opt/victronenergy/gui/qml/PageBatteryParameters.qml.backup ]; then
    cp -f /opt/victronenergy/gui/qml/PageBatteryParameters.qml.backup /opt/victronenergy/gui/qml/PageBatteryParameters.qml
    echo "PageBatteryParameters.qml was restored."
fi
# restore original backup
if [ -f /opt/victronenergy/gui/qml/PageBatterySettings.qml.backup ]; then
    cp -f /opt/victronenergy/gui/qml/PageBatterySettings.qml.backup /opt/victronenergy/gui/qml/PageBatterySettings.qml
    echo "PageBatterySettings.qml was restored."
fi
# restore original backup
if [ -f /opt/victronenergy/gui/qml/PageLynxIonIo.qml.backup ]; then
    cp -f /opt/victronenergy/gui/qml/PageLynxIonIo.qml.backup /opt/victronenergy/gui/qml/PageLynxIonIo.qml
    echo "PageLynxIonIo.qml was restored."
fi

service_path="/service/start-gui"
if [ -d $service_path ] && [ -f "$service_path/supervise/status" ]; then
    svc -d -u "$service_path"
fi
