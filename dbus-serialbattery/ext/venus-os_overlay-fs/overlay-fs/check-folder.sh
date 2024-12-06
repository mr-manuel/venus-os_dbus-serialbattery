#!/bin/bash
#
# MIT License
#
# Copyright (c) 2024 github.com/mr-manuel
#
# Version: 0.0.1 (20241128)

# This script checks if a directory is mounted on an overlay filesystem (overlay-fs).
# It returns 0 if the directory is mounted on an overlay-fs, and 1 if it is not.
#
# Usage: check-directory.sh <directory-path>


# Get command line arguments
if [ $# -ne 1 ]; then
    echo "Usage: $0 <directory-path>"
    exit 1
fi

# Remove trailing slash from directory
if [ "${1: -1}" == "/" ]; then
    directory="${1%/}"
else
    directory="$1"
fi

# Check if the directory exists
if [ ! -d "$directory" ]; then
    echo "The directory \"$directory\" does not exist."
    exit 1
fi

# Check if the directory is mounted on an overlay-fs
if mount | grep -q "on $directory type overlay"; then
    echo "The directory \"$directory\" is mounted on an overlay-fs."
    exit 0
else
    echo "The directory \"$directory\" is not mounted on an overlay-fs."
    exit 1
fi
