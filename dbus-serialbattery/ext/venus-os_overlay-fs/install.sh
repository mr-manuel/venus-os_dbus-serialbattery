#!/bin/bash
#
# MIT License
#
# Copyright (c) 2024 github.com/mr-manuel
#
# INFO
# use this script to install the latest version of the app and copy it to the correct location
#
# COMMAND LINE ARGUMENTS
# -c, --copy: copy the app to the correct location if delivered as dependency without downloading


appPath="/data/apps"
appName="overlay-fs"

# change to temp directory
cd "/tmp"

echo


# check command line arguments
if [ "$1" == "-c" ] || [ "$1" == "--copy" ]; then

    echo "Copying and installing overlay-fs app..."

    # get the path of this script
    sourcePath="$(dirname "$(realpath "$0")")/overlay-fs/"

    # check if the app directory is available
    if [ ! -d "$sourcePath" ]; then
        echo "The app directory is not available. Try to execute the download script to install, else copy the files again."
        echo
        exit 1
    fi


else

    # download app
    echo "Downloading overlay-fs app..."


    # download nightly build
    url="https://github.com/mr-manuel/venus-os_${appName}/archive/refs/heads/master.zip"

    echo "Downloading from: $url"
    wget -O "/tmp/venus-os_${appName}.zip" "$url"

    # check if download was successful
    if [ ! -f "/tmp/venus-os_${appName}.zip" ]; then
        echo
        echo "ERROR: Download failed. Exiting..."
        echo
        exit 1
    fi


    # If updating: cleanup old directory
    if [ -d "/tmp/venus-os_${appName}-master" ]; then
        rm -rf "/tmp/venus-os_${appName}-master"
    fi


    # unzip directory
    echo "Unzipping app..."
    unzip venus-os_${appName}.zip

    # Find and rename the extracted directory to be always the same
    extractedDirectory="$(find /tmp/ -maxdepth 1 -type d -name "*${appName}-*")"

    # Desired directory name
    desiredDirectory="/tmp/venus-os_${appName}-master"

    # Check if the extracted directory exists and does not already have the desired name
    if [ -n "$extractedDirectory" ]; then
        if [ "$extractedDirectory" != "$desiredDirectory" ]; then
            mv "$extractedDirectory" "$desiredDirectory"
        else
            echo "Directory already has the desired name: $desiredDirectory"
        fi
    else
        echo "Error: Could not find extracted directory. Exiting..."
        # exit 1
    fi

    sourcePath="/tmp/venus-os_${appName}-master/${appName}/"

fi


# If updating: backup existing config file
if [ -f "${appPath}/${appName}/overlay-fs.conf" ]; then
    echo "Backing up existing config file..."
    mv "${appPath}/${appName}/overlay-fs.conf" "${appPath}/${appName}_overlay-fs.conf"
fi


# If updating: cleanup existing app
if [ -d ${appPath}/${appName} ]; then
    echo "Cleaning up existing app..."
    rm -rf "${appPath:?}/${appName}"
fi


# copy files
echo "Copying new app files..."
if [ ! -d "${appPath}" ]; then
    mkdir -p "${appPath}"
fi
cp -R "${sourcePath}" "${appPath}/${appName}/"

# remove temp files

echo "Cleaning up temp files..."
if [ -f "/tmp/venus-os_${appName}.zip" ]; then
    rm -rf "/tmp/venus-os_${appName}.zip"
fi
if [ -d "/tmp/venus-os_${appName}-master" ]; then
    rm -rf "/tmp/venus-os_${appName}-master"
fi


# If updating: restore existing config file
if [ -f "${appPath}/${appName}_overlay-fs.conf" ]; then
    echo "Restoring existing config file..."
    if [ -f "${appPath}/${appName}/overlay-fs.conf" ]; then
        rm "${appPath}/${appName}/overlay-fs.conf"
    fi
    mv "${appPath}/${appName}_overlay-fs.conf" "${appPath}/${appName}/overlay-fs.conf"
fi


# set permissions for files
echo "Setting permissions for files..."
chmod 755 ${appPath}/${appName}/*.sh


# copy empty config file
if [ ! -f "${appPath}/${appName}/overlay-fs.conf" ]; then
    # Copy empty config file
    cp "${appPath}/${appName}/overlay-fs.conf.sample" "${appPath}/${appName}/overlay-fs.conf"

    if [ "$1" != "-c" ] && [ "$1" != "--copy" ]; then
        echo
        echo "First installation detected. Copying empty config file..."
        echo
        echo "** Do not forget to add entries! **"
        echo "You can add entries by executing the following command:"
        echo "${appPath}/${appName}/add-app-and-directory.sh <app-name> <directory-path>"
        echo "Example:"
        echo "    bash ${appPath}/${appName}/add-app-and-directory.sh /var/www/venus custom-web-app"
        echo
        echo "** Execute the enable.sh script after you have added at least one entry! **"
        echo "You can execute the enable.sh script with the following command:"
        echo "bash ${appPath}/${appName}/enable.sh"
        echo
    fi
else
    if [ "$1" != "-c" ] && [ "$1" != "--copy" ]; then
        echo
        echo "Reboot to apply new version..."
    fi
fi


echo "Installation of overlay-fs app completed."
echo
