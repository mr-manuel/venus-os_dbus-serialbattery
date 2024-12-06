#!/bin/bash
#
# MIT License
#
# Copyright (c) 2024 github.com/mr-manuel
#
# Version: 0.0.1 (20241128)

# This script adds a directory to the overlay-fs.
# It checks if the directory or any of its parent directories are already in the config file.
# If so, it will not add the directory but will add the app name to the existing entry.
#
# Usage: add-app-and-directory.sh [--no-mount] <app-name> <directory-path>

show_help() {
    echo "Usage: $0 [--no-mount] <app-name> <directory-path>"
    echo
    echo "Options:"
    echo "  --no-mount    Skip the mount of the directory for now"
}

no_mount=0

# Parse options
while [[ "$1" == --* ]]; do
    case "$1" in
        --no-mount)
            no_mount=1
            shift
            ;;
        --help)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Check if required arguments are provided
if [ $# -ne 2 ]; then
    show_help
    exit 1
fi

appNameArg="$1"
directoryPathArg="$2"

# Remove trailing slash from directory
if [ "${directoryPathArg: -1}" == "/" ]; then
    directoryPathArg="${directoryPathArg%/}"
fi


checkOverlayRecursive() {
    local dir="$1"
    while [ "$dir" != "/" ]; do
        if mount | grep -q "on $dir type overlay"; then
            echo "$dir"
            return 0
        fi
        dir=$(dirname "$dir")
    done
    return 1
}

checkConfigRecursive() {
    local dir="$1"
    while [ "$dir" != "/" ]; do
        if grep -q "^$dir " /data/apps/overlay-fs/overlay-fs.conf; then
            # Output the whole line and not only the directory
            grep "^$dir " /data/apps/overlay-fs/overlay-fs.conf
            return 0
        fi
        dir=$(dirname "$dir")
    done
    return 1
}


# Check if the directory exists
if [ ! -d "$directoryPathArg" ]; then
    echo "ERROR: The directory \"${directoryPathArg}\" does not exist."
    exit 1
fi

# Check if the path is a symlink
if [ -L "$directoryPathArg" ]; then
    echo "ERROR: The directory \"${directoryPathArg}\" is a symlink and cannot be used."
    exit 1
fi


# Check if the directory is already mounted as an overlay and if the directory exists in the config file
# overlayDir=$(checkOverlayRecursive "$directoryPathArg")
# if [ $? -eq 0 ]; then
#     echo "The directory \"$directoryPathArg\" cannot be enabled, since \"$overlayDir\" is already mounted as an overlay-fs."
#     exit 1
# fi


# Check if the directory exists in the config file
configEntry="$(checkConfigRecursive "$directoryPathArg")"
if [ $? -eq 0 ]; then
    # Split the config entry on the first space
    IFS=' ' read -r configDir appNames other <<< "$configEntry"

    # Split the app names on the comma
    IFS=',' read -ra appNamesArray <<< "$appNames"

    # Check if the app name is already in the entry
    for app in "${appNamesArray[@]}"; do
        if [ "$app" == "$appNameArg" ]; then
            echo "The app \"$appNameArg\" was already added to the directory \"$configDir\" in the config file."
            exit
        fi
    done

    # Add the app name to the existing entry
    sed -i "s|^$configDir .*|&,$appNameArg|" /data/apps/overlay-fs/overlay-fs.conf
    echo "The app \"$appNameArg\" was added to the directory \"$configDir\" in the config file."
else
    # Add the directory to the config file
    echo "$directoryPathArg $appNameArg" >> /data/apps/overlay-fs/overlay-fs.conf
    echo "The directory \"$directoryPathArg\" was added to the config file."

    # Run enable.sh to mount the overlay-fs
    /data/apps/overlay-fs/enable.sh
fi
