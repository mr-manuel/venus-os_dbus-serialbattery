#!/bin/bash
#
# MIT License
#
# Copyright (c) 2024 github.com/mr-manuel
#
# Version: 0.0.1 (20241128)


echo
echo "Enabling overlay-fs app..."


# Create overlay-fs and mount it, if not already mounted
function mountOverlayFs ()
{
    path="/data/apps/overlay-fs/data"
    lowerDir="$1"

    # Check if the path exists and is a directory
    if [ ! -d "$lowerDir" ]; then
        echo "$(date +%Y-%m-%d\ %H:%M:%S) ERROR: ${lowerDir} is not a directory"
        return 1
    fi

    # Check if the path is a symlink
    if [ -L "$lowerDir" ]; then
        echo "$(date +%Y-%m-%d\ %H:%M:%S) ERROR: ${lowerDir} is a symlink and cannot be used"
        return 1
    fi

    # Check if the path is not /
    if [ "$lowerDir" == "/" ]; then
        echo "$(date +%Y-%m-%d\ %H:%M:%S) ERROR: ${lowerDir} is the root directory and cannot be used"
        return 1
    fi

    # Extract the top directory name of the path
    overlayName="$(basename "$1")"


    if [ ! -d "${path}/${overlayName}/upper" ]; then
        mkdir -p "${path}/${overlayName}/upper"
    fi
    if [ ! -d "${path}/${overlayName}/work" ]; then
        mkdir -p "${path}/${overlayName}/work"
    fi
    if [ ! -d "${path}/${overlayName}/merged" ]; then
        mkdir -p "${path}/${overlayName}/merged"
    fi


    # Check if overlay is already mounted
    if ! mountpoint -q "${path}/${overlayName}/merged"; then
        echo "$(date +%Y-%m-%d\ %H:%M:%S) INFO: Mounting overlay for ${lowerDir}"
        # Mount the overlay
        # add "-o index=off" to avoid error when system had power loss:
        # mount: /data/apps/overlay-fs/gui-v2/merged: mount(2) system call failed: Stale file handle.
        # there is no difference for only a few changed files
        mount -t overlay OL_${overlayName} -o index=off -o lowerdir=${lowerDir},upperdir=${path}/${overlayName}/upper,workdir=${path}/${overlayName}/work ${path}/${overlayName}/merged

        # Check if the mount was successful
        if [ $? -ne 0 ]; then
            echo "$(date +%Y-%m-%d\ %H:%M:%S) ERROR: Could not mount overlay for ${lowerDir}"
            return 1
        fi
    fi


    # Check if overlay is already mounted
    if ! mountpoint -q "${lowerDir}"; then
        echo "$(date +%Y-%m-%d\ %H:%M:%S) INFO: Mounting bind overlay for ${lowerDir}"
        # Mounting bind to the lower directory path
        mount --bind "${path}/${overlayName}/merged" "${lowerDir}"

        # Check if the mounting bind was successful
        if [ $? -ne 0 ]; then
            echo "$(date +%Y-%m-%d\ %H:%M:%S) ERROR: Could not mount bind overlay for ${lowerDir}"
            return 1
        fi
    fi
}



# Fix permissions
chmod 755 /data/apps/overlay-fs/*.sh



# Launch the overlay-fs at startup
filename="/data/rcS.local"
# Create the file if it doesn't exist
if [ ! -f "$filename" ]; then
    echo "$(date +%Y-%m-%d\ %H:%M:%S) INFO: rcS.local file doesn't exist. Creating it..."
    echo "#!/bin/bash" > "$filename"
    chmod 755 "$filename"
fi
# Add the line to the first non-comment line of the file if it doesn't exist
if ! grep -qxF "bash /data/apps/overlay-fs/enable.sh > /data/apps/overlay-fs/startup.log 2>&1" "$filename"; then
    echo "$(date +%Y-%m-%d\ %H:%M:%S) INFO: Adding overlay-fs startup command to rcS.local"
    lineNumber=$(awk '/^[^#]/ {print NR; exit}' "$filename")
    if [ -z "$lineNumber" ]; then
        # If no non-comment line is found, add to the end of the file
        echo "bash /data/apps/overlay-fs/enable.sh > /data/apps/overlay-fs/startup.log 2>&1" >> "$filename"
    else
        sed -i "${lineNumber}i bash /data/apps/overlay-fs/enable.sh > /data/apps/overlay-fs/startup.log 2>&1" "$filename"
    fi
fi


# Read the config file and loop through each line
while IFS= read -r line; do
    # Ensure the line starts with /
    if [[ "$line" =~ ^\/ ]]; then
        mountOverlayFs $line
    fi
done < "/data/apps/overlay-fs/overlay-fs.conf"

echo "done."
echo
