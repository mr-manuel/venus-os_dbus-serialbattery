#!/bin/bash
#
# MIT License
#
# Copyright (c) 2024 github.com/mr-manuel
#
# Version: 0.0.1 (20241128)


# disable app
bash /data/apps/overlay-fs/disable.sh


read -r -p "Do you want to delete the overlay-fs app and all overlay data in \"/data/apps/overlay-fs\"? If unsure, just press enter. [y/N] " response
echo
response=${response,,} # tolower
if [[ $response =~ ^([yY][eE][sS]|[yY])$ ]]; then
    rm -rf /data/apps/overlay-fs
    echo "The directory \"/data/apps/overlay-fs\" was removed."
fi


echo "The overlay-fs app was uninstalled. Please reboot."
echo
