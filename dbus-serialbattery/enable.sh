#!/bin/bash

# remove comment for easier troubleshooting
#set -x


# check if minimum required Venus OS is installed | start
versionRequired="v2.90"

# import functions
source /data/apps/dbus-serialbattery/functions.sh


# get current Venus OS version
versionStringToNumber "$(head -n 1 /opt/victronenergy/version)"
venusVersionNumber="$versionNumber"

# minimum required version to install the driver
versionStringToNumber "$versionRequired"

if (( $venusVersionNumber < $versionNumber )); then
    echo
    echo
    echo "Minimum required Venus OS version \"$versionRequired\" not met. Currently version \"$(head -n 1 /opt/victronenergy/version)\" is installed."
    echo
    echo "Please update via \"Remote Console/GUI -> Settings -> Firmware -> Online Update\""
    echo "OR"
    echo "by executing \"/opt/victronenergy/swupdate-scripts/check-updates.sh -update -force\""
    echo
    echo "Install the driver again after Venus OS was updated."
    echo
    echo
    exit 1
fi
# check if minimum required Venus OS is installed | end



# fix permissions
chmod +x /data/apps/dbus-serialbattery/*.sh
chmod +x /data/apps/dbus-serialbattery/*.py
chmod +x /data/apps/dbus-serialbattery/service/run
chmod +x /data/apps/dbus-serialbattery/service/log/run


# remove old folders that are not needed anymore
if [ -d /opt/victronenergy/dbus-serialbattery ]; then
    echo "Remove old dbus-serialbattery folders on root fs..."
    bash /opt/victronenergy/swupdate-scripts/remount-rw.sh
    rm -rf /opt/victronenergy/service/dbus-serialbattery
    rm -rf /opt/victronenergy/service-templates/dbus-serialbattery
    rm -rf /opt/victronenergy/dbus-serialbattery
fi


# check if overlay-fs is active
checkOverlay dbus-serialbattery "/opt/victronenergy/service-templates"


if [ -d "/opt/victronenergy/service-templates/dbus-serialbattery" ]; then
    rm -rf "/opt/victronenergy/service-templates/dbus-serialbattery"
fi
cp -rf "/data/apps/dbus-serialbattery/service" "/opt/victronenergy/service-templates/dbus-serialbattery"



# install custom GUI
bash /data/apps/dbus-serialbattery/custom-gui-install.sh



# check if serial-starter.d was deleted
serialstarter_path="/data/conf/serial-starter.d"
serialstarter_file="${serialstarter_path}/dbus-serialbattery.conf"

# check if folder is a file (older versions of this driver < v1.0.0)
if [ -f "$serialstarter_path" ]; then
    rm -f "$serialstarter_path"
fi

# check if folder exists
if [ ! -d "$serialstarter_path" ]; then
    mkdir "$serialstarter_path"
fi

# check if file exists
if [ ! -f "$serialstarter_file" ]; then
    {
        echo "service   sbattery    dbus-serialbattery"
        echo "alias     default     gps:vedirect:sbattery"
        echo "alias     rs485       cgwacs:fzsonick:imt:modbus:sbattery"
    } > "$serialstarter_file"
fi



# add install-script to rc.local to be ready for firmware update
filename=/data/rc.local
if [ ! -f "$filename" ]; then
    echo "#!/bin/bash" > "$filename"
    chmod 755 "$filename"
fi

# add enable script to rc.local
# log the output to a file and run it in the background to prevent blocking the boot process
grep -qxF "bash /data/apps/dbus-serialbattery/enable.sh > /data/apps/dbus-serialbattery/startup.log 2>&1 &" $filename || echo "bash /data/apps/dbus-serialbattery/enable.sh > /data/apps/dbus-serialbattery/startup.log 2>&1 &" >> $filename



# add empty config.ini, if it does not exist to make it easier for users to add custom settings
filename="/data/apps/dbus-serialbattery/config.ini"
if [ ! -f "$filename" ]; then
    {
        echo "[DEFAULT]"
        echo
        echo "; If you want to add custom values/settings, then check the values/settings you want to change in \"config.default.ini\""
        echo "; and insert them below to persist future driver updates."
        echo
        echo "; Example (remove the semicolon \";\" to uncomment and activate the value/setting):"
        echo "; MAX_BATTERY_CHARGE_CURRENT = 50.0"
        echo "; MAX_BATTERY_DISCHARGE_CURRENT = 60.0"
        echo
        echo
    } > $filename
fi



# TODO: stop BLE, CAN and serial?
echo "Stop all dbus-serialbattery services..."
for service in /service/dbus-serialbattery.*; do
    [ -e "$service" ] && svc -d "$service"
done
for service in /service/dbus-canbattery.*; do
    [ -e "$service" ] && svc -d "$service"
done

# kill driver, if still running
pkill -f "supervise dbus-serialbattery.*"
pkill -f "multilog .* /var/log/dbus-serialbattery.*"
pkill -f "python .*/dbus-serialbattery.py /dev/tty.*"



### BLUETOOTH PART | START ###

# get bluetooth mode integrated/usb
bluetooth_use_usb=$(awk -F "=" '/^BLUETOOTH_USE_USB/ {print $2}' /data/apps/dbus-serialbattery/config.ini)

# works only for Raspberry Pi, since GX devices don't have a /u-boot/config.txt
# replace dtoverlay in /u-boot/config.txt this needs a reboot!
if [ -f "/u-boot/config.txt" ]; then
    if [[ $bluetooth_use_usb == *"True"* ]]; then
        if grep -q -r "miniuart-bt" /u-boot/config.txt; then
            sed -i 's/miniuart-bt/disable-bt/g' /u-boot/config.txt
            echo "ATTENTION! You have changed the bluetooth mode to USB! THIS NEEDS A MANUAL REBOOT!"
        fi
    elif [[ $bluetooth_use_usb == *"False"* ]]; then
        if grep -q -r "disable-bt" /u-boot/config.txt; then
            sed -i 's/disable-bt/miniuart-bt/g' /u-boot/config.txt
            echo "ATTENTION! You have changed the bluetooth mode to built in module! THIS NEEDS A MANUAL REBOOT!"
        fi
    fi
fi

# get BMS list from config file
bluetooth_bms=$(awk -F "=" '/^BLUETOOTH_BMS/ {print $2}' /data/apps/dbus-serialbattery/config.ini)
#echo $bluetooth_bms

# clear whitespaces
bluetooth_bms_clean=$(echo "$bluetooth_bms" | tr -s ' ' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
#echo $bluetooth_bms_clean

# split into array
IFS="," read -r -a bms_array <<< "$bluetooth_bms_clean"

# array length
bluetooth_length=${#bms_array[@]}
# echo $bluetooth_length

# stop all dbus-blebattery services, if at least one exists
if ls /service/dbus-blebattery.* 1> /dev/null 2>&1; then
    echo "Stop all dbus-blebattery services..."
    for service in /service/dbus-blebattery.*; do
        [ -e "$service" ] && svc -d "$service"
    done

    # always remove existing blebattery services to cleanup
    rm -rf /service/dbus-blebattery.*

    # kill all blebattery processes that remain
    pkill -f "supervise dbus-blebattery.*"
    pkill -f "multilog .* /var/log/dbus-blebattery.*"
    pkill -f "python .*/dbus-serialbattery.py .*_Ble"

    # kill opened bluetoothctl processes
    pkill -f "^bluetoothctl "
fi


if [ "$bluetooth_length" -gt 0 ]; then

    echo
    echo "Found $bluetooth_length Bluetooth BMS in the config file!"
    echo

    # Required packages, shipped with the driver:
    # - opkg install python3-misc
    # - opkg install python3-pip
    # - pip3 install bleak

    /etc/init.d/bluetooth stop
    sleep 2
    /etc/init.d/bluetooth start
    echo

    # function to install ble battery
    install_blebattery_service() {
        if [ -z "$1" ]; then
            echo "ERROR: BMS unique number is empty. Aborting installation."
            echo
            exit 1
        fi
        if [ -z "$2" ]; then
            echo "ERROR: BMS type for battery $1 is empty. Aborting installation."
            echo
            exit 1
        fi
        if [ -z "$3" ]; then
            echo "ERROR: BMS MAC address for battery $1 with BMS type $2 is empty. Aborting installation."
            echo
            exit 1
        fi

        echo "Installing \"$2\" with MAC address \"$3\" as dbus-blebattery.$1"

        mkdir -p "/service/dbus-blebattery.$1/log"
        {
            echo "#!/bin/sh"
            echo "exec multilog t s25000 n4 /var/log/dbus-blebattery.$1"
        } > "/service/dbus-blebattery.$1/log/run"
        chmod 755 "/service/dbus-blebattery.$1/log/run"

        {
            echo "#!/bin/sh"
            echo
            echo "# Forward signals to the child process"
            echo "trap 'kill -TERM \$PID' TERM INT"
            echo
            # close all open connections, else the driver can't connect
            echo "bluetoothctl disconnect $3 > /dev/null 2>&1"
            echo
            echo "# Start the main process"
            echo "exec 2>&1"
            echo "python /data/apps/dbus-serialbattery/dbus-serialbattery.py $2 $3 &"
            echo
            echo "# Capture the PID of the child process"
            echo "PID=\$!"
            echo
            echo "# Wait for the child process to exit"
            echo "wait \$PID"
            echo
            echo "# Capture the exit status"
            echo "EXIT_STATUS=\$?"
            echo
            echo "# Exit with the same status"
            echo "exit \$EXIT_STATUS"
        } > "/service/dbus-blebattery.$1/run"
        chmod 755 "/service/dbus-blebattery.$1/run"
    }

    # Example
    # install_blebattery_service 0 Jkbms_Ble C8:47:8C:00:00:00
    # install_blebattery_service 1 Jkbms_Ble C8:47:8C:00:00:11

    for (( i=0; i<bluetooth_length; i++ ));
    do
        # split BMS type and MAC address
        IFS=' ' read -r -a bms <<< "${bms_array[$i]}"
        install_blebattery_service $i "${bms[0]}" "${bms[1]}"
    done

    echo

else

    echo
    echo "No Bluetooth battery configuration found in \"/data/apps/dbus-serialbattery/config.ini\"."
    echo "You can ignore this, if you are using only a serial connection."
    echo

fi
### BLUETOOTH PART | END ###



### CAN PART | START ###

# get CAN port(s) from config file
can_port=$(awk -F "=" '/^CAN_PORT/ {print $2}' /data/apps/dbus-serialbattery/config.ini)
#echo $can_port

# clear whitespaces
can_port_clean="$(echo $can_port | sed 's/\s*,\s*/,/g')"
#echo $can_port_clean

# split into array
IFS="," read -r -a can_array <<< "$can_port_clean"
#declare -p can_array
# readarray -td, can_array <<< "$can_port_clean,"; unset 'can_array[-1]'; declare -p can_array;

can_lenght=${#can_array[@]}
# echo $can_lenght

# stop all dbus-canbattery services, if at least one exists
if ls /service/dbus-canbattery.* 1> /dev/null 2>&1; then
    echo "Killing old CAN battery services..."
    svc -t /service/dbus-canbattery.*

    # always remove existing canbattery services to cleanup
    rm -rf /service/dbus-canbattery.*

    # kill all canbattery processes that remain
    pkill -f "supervise dbus-canbattery.*"
    pkill -f "multilog .* /var/log/dbus-canbattery.*"
    pkill -f "python .*/dbus-serialbattery.py can.*"
fi


if [ "$can_lenght" -gt 0 ]; then

    echo
    echo "Found $can_lenght CAN port(s) in the config file!"
    echo

    # Required packages, shipped with the driver:
    # - opkg install python3-misc
    # - opkg install python3-pip
    # - pip3 install python-can

    # function to install can battery
    install_canbattery_service() {
        if [ -z "$1" ]; then
            echo "ERROR: CAN port is empty. Aborting installation."
            echo
            exit 1
        fi

        echo "Installing CAN port \"$1\" as dbus-canbattery.$1"

        mkdir -p "/service/dbus-canbattery.$1/log"
        {
            echo "#!/bin/sh"
            echo "exec multilog t s25000 n4 /var/log/dbus-canbattery.$1"
        } > "/service/dbus-canbattery.$1/log/run"
        chmod 755 "/service/dbus-canbattery.$1/log/run"

        {
            echo "#!/bin/sh"
            echo
            echo "# Forward signals to the child process"
            echo "trap 'kill -TERM \$PID' TERM INT"
            echo
            echo "# Start the main process"
            echo "exec 2>&1"
            echo "python /data/apps/dbus-serialbattery/dbus-serialbattery.py $1 &"
            echo
            echo "# Capture the PID of the child process"
            echo "PID=\$!"
            echo
            echo "# Wait for the child process to exit"
            echo "wait \$PID"
            echo
            echo "# Capture the exit status"
            echo "EXIT_STATUS=\$?"
            echo
            echo "# Exit with the same status"
            echo "exit \$EXIT_STATUS"
        } > "/service/dbus-canbattery.$1/run"
        chmod 755 "/service/dbus-canbattery.$1/run"
    }

    # Example
    # install_canbattery_service can0
    # install_canbattery_service can9

    for (( i=0; i<can_lenght; i++ ));
    do
        install_canbattery_service "${can_array[$i]}"
    done

else

    echo
    echo "No CAN port configuration found in \"/data/apps/dbus-serialbattery/config.ini\"."
    echo "You can ignore this, if you are using only a serial connection."
    echo

fi
### CAN PART | END ###



### needed for upgrading from older versions | start ###
# remove old drivers before changing from dbus-blebattery-$1 to dbus-blebattery.$1
rm -rf /service/dbus-blebattery-*
# remove old install script from rc.local
sed -i "/^sh \/data\/etc\/dbus-serialbattery\/reinstalllocal.sh/d" /data/rc.local
sed -i "/^sh \/data\/etc\/dbus-serialbattery\/reinstall-local.sh/d" /data/rc.local
sed -i "/^bash \/data\/etc\/dbus-serialbattery\/reinstall-local.sh/d" /data/rc.local
# remove old entry from rc.local
sed -i "/^sh \/data\/etc\/dbus-serialbattery\/installble.sh/d" /data/rc.local
### needed for upgrading from older versions | end ###



# install notes
echo
echo
echo "#################"
echo "# Install notes #"
echo "#################"
echo
echo "SERIAL battery connection: The installation is complete. You don't have to do anything more."
echo
echo "BLUETOOTH battery connection: There are a few more steps to complete installation."
echo
echo "    1. Add your Bluetooth BMS to the config file \"/data/apps/dbus-serialbattery/config.ini\"."
echo "       Check the default config file \"/data/apps/dbus-serialbattery/config.default.ini\" for more informations."
echo "       If your Bluetooth BMS are nearby you can show the MAC address with \"bluetoothctl devices\"."
echo
echo "    2. Make sure to disable Bluetooth in \"Settings -> Bluetooth\" in the remote console/GUI to prevent reconnects every minute."
echo
echo "    3. Re-run \"/data/apps/dbus-serialbattery/reinstall-local.sh\", if the Bluetooth BMS were not added to the \"config.ini\" before."
echo
echo "    ATTENTION!"
echo "    If you changed the default connection PIN of your BMS, then you have to pair the BMS first using OS tools like the \"bluetoothctl\"."
echo "    See https://wiki.debian.org/BluetoothUser#Using_bluetoothctl for more details."
echo
echo "CAN battery connection: There are a few more steps to complete installation."
echo
echo "    1. Add your CAN port to the config file \"/data/apps/dbus-serialbattery/config.ini\"."
echo "       Check the default config file \"/data/apps/dbus-serialbattery/config.default.ini\" for more informations."
echo
echo "    2. Make sure to select a profile with 250 kbit/s in \"Settings -> Services -> VE.Can port -> CAN-bus profile\" in the remote console/GUI."
echo
echo "    3. Re-run \"/data/apps/dbus-serialbattery/reinstall-local.sh\", if the CAN port was not added to the \"config.ini\" before."
echo
echo "CUSTOM SETTINGS: If you want to add custom settings, then check the settings you want to change in \"/data/apps/dbus-serialbattery/config.default.ini\""
echo "                 and add them to \"/data/apps/dbus-serialbattery/config.ini\" to persist future driver updates."
echo
echo
line=$(cat /data/apps/dbus-serialbattery/utils.py | grep DRIVER_VERSION | awk -F'"' '{print "v" $2}')
echo "*** dbus-serialbattery $line was installed. ***"
echo
echo
echo "####################################"
echo "# Help to keep this project alive! #"
echo "####################################"
echo
echo "Your support keeps this project alive!"
echo "If you find this project valuable, please consider making a donation."
echo "Your contribution helps me continue improving and maintaining it."
echo "Every donation, no matter the size, makes a difference."
echo "Copy the link below and paste it into your browser to donate:"
echo
echo "https://www.paypal.com/donate/?hosted_button_id=3NEVZBDM5KABW"
echo
echo "Cheers, mr-manuel"
echo
echo
