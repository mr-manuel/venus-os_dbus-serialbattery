#!/bin/bash
#
# MIT License
#
# Copyright (c) 2024 github.com/mr-manuel
#
# Version: 0.0.1 (20241128)

# This script removes a directory from the overlay-fs.
# It identifies which directorys were mounted by an application, unmounts the overlay,
# and removes it from the config file if it was the only application using it.
#
# Usage: remove-app.sh <app-name>


# Declare an associative array to store unique app names
declare -A uniqueAppNames

# Read the config file and loop through each line
while IFS= read -r line; do
    # Ensure the line starts with /
    if [[ "$line" =~ ^\/ ]]; then
        # Split the config entry on the first space
        IFS=' ' read -r configDir appNames other <<< "$line"

        # Split the app names on the comma
        IFS=',' read -ra appNamesArray <<< "$appNames"

        # Add each app name to the associative array
        for appName in "${appNamesArray[@]}"; do
            uniqueAppNames["$appName"]=1
        done
    fi
done < /data/apps/overlay-fs/overlay-fs.conf

# Create a list of unique app names
uniqueAppNamesList=("${!uniqueAppNames[@]}")

# Sort the list of unique app names alphabetically
mapfile -t sortedUniqueAppNames < <(printf "%s\n" "${uniqueAppNamesList[@]}" | sort)
unset IFS


# Get command line arguments
if [ $# -ne 1 ]; then
    echo "Usage: $0 <app-name>"
    echo
    echo "Installed app names:"
    for appName in "${sortedUniqueAppNames[@]}"; do
        echo "- $appName"
    done
    exit 1
fi


# Check if the app name is valid
appNameFound="false"
for appName in "${sortedUniqueAppNames[@]}"; do
    if [[ "$appName" == "$1" ]]; then
        appNameFound="true"
        break
    fi
done

if [[ "$appNameFound" == "false" ]]; then
    echo "The app name \"$1\" is not installed."
    echo
    echo "Installed app names:"
    for appName in "${sortedUniqueAppNames[@]}"; do
        echo "- $appName"
    done
    exit 1
fi


# Remove the app name from the config file and unmount the overlay if it was the only app using it
while IFS= read -r line; do
    # Ensure the line starts with /
    if [[ "$line" =~ ^\/ ]]; then
        # Split the config entry on the first space
        IFS=' ' read -r configDir appNames other <<< "$line"

        # Split the app names on the comma
        IFS=',' read -ra appNamesArray <<< "$appNames"

        # Check if the app name is in the entry
        for i in "${!appNamesArray[@]}"; do
            if [ "${appNamesArray[$i]}" == "$1" ]; then
                # Remove the app name from the entry
                unset "appNamesArray[$i]"

                # If the entry is empty, remove it from the config file and unmount the overlay
                if [ ${#appNamesArray[@]} -eq 0 ]; then
                    sed -i "\;^$configDir;d" "/data/apps/overlay-fs/overlay-fs.conf"
                    echo "The directory \"$configDir\" was removed from the config file."

                    # Unmount the overlay
                    overlayName="$(basename "$configDir")"
                    path="/data/apps/overlay-fs/data"
                    if mountpoint -q "$configDir"; then
                        echo "Unmounting bind overlay for ${configDir}"
                        umount "$configDir"
                        if [ $? -ne 0 ]; then
                            echo "ERROR: Could not unmount bind overlay for ${configDir}"
                        fi
                    fi
                    if mountpoint -q "${path}/$overlayName/merged"; then
                        echo "Unmounting overlay for ${configDir}"
                        umount "${path}/$overlayName/merged"
                        if [ $? -ne 0 ]; then
                            echo "ERROR: Could not unmount overlay for ${configDir}"
                        fi
                    fi
                else
                    # Update the entry in the config file
                    newAppNames=$(IFS=,; echo "${appNamesArray[*]}")
                    sed -i "\;^$configDir ;s; .*; $newAppNames;" "/data/apps/overlay-fs/overlay-fs.conf"
                    echo "The app \"$1\" was removed from the directory \"$configDir\" in the config file."
                fi
            fi
        done
    fi
done < /data/apps/overlay-fs/overlay-fs.conf
