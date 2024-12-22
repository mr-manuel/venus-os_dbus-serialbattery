#!/bin/bash

# remove comment for easier troubleshooting
#set -x

# this file has also to work for older driver versions
# else it won't work to install an older version


# check if at least 30 MB free space is available on the system partition
freeSpace=$(df -m /data | awk 'NR==2 {print $4}')
if [ $freeSpace -lt 30 ]; then
    echo
    echo
    echo "ERROR: Not enough free space on the /data partition. At least 30 MB are required."
    echo
    echo "       Free up some space and try again."
    echo
    echo
    exit 1
fi



function backup_config {
    # backup config.ini
    # driver >= v2.0.0
    if [ -f "/data/apps/dbus-serialbattery/config.ini" ]; then
        mv /data/apps/dbus-serialbattery/config.ini /data/apps/dbus-serialbattery_config.ini.backup
        echo "Config.ini backed up to /data/apps/dbus-serialbattery_config.ini.backup"
    # driver < v2.0.0
    elif [ -f "/data/etc/dbus-serialbattery/config.ini" ]; then
        mv /data/etc/dbus-serialbattery/config.ini /data/etc/dbus-serialbattery_config.ini.backup
        echo "Config.ini backed up to /data/etc/dbus-serialbattery_config.ini.backup"
    fi
}

function restore_config {
    # restore config.ini
    # installation of driver >= v2.0.0
    if [ -f "/data/apps/dbus-serialbattery_config.ini.backup" ]; then
        # restore to driver >= v2.0.0 (normal update)
        if [ -d "/data/apps/dbus-serialbattery" ]; then
            mv /data/apps/dbus-serialbattery_config.ini.backup /data/apps/dbus-serialbattery/config.ini
            echo "Config.ini restored to /data/apps/dbus-serialbattery/config.ini"
        # restore to driver < v2.0.0 (downlgrade)
        elif [ -d "/data/etc/dbus-serialbattery" ]; then
            mv /data/apps/dbus-serialbattery_config.ini.backup /data/etc/dbus-serialbattery/config.ini
            echo "Config.ini restored to /data/etc/dbus-serialbattery/config.ini"
        fi
    # installation of driver < v2.0.0
    elif [ -f "/data/etc/dbus-serialbattery_config.ini.backup" ]; then
        # restore to driver >= v2.0.0 (upgrade)
        if [ -d "/data/apps/dbus-serialbattery" ]; then
            mv /data/etc/dbus-serialbattery_config.ini.backup /data/apps/dbus-serialbattery/config.ini
            echo "Config.ini restored to /data/apps/dbus-serialbattery/config.ini"
        # restore to driver < v2.0.0 (normal update)
        elif [ -d "/data/etc/dbus-serialbattery" ]; then
            mv /data/etc/dbus-serialbattery_config.ini.backup /data/etc/dbus-serialbattery/config.ini
            echo "Config.ini restored to /data/etc/dbus-serialbattery/config.ini"
        fi
    fi
}



echo
echo "*** Welcome to the dbus-serialbattery installer from mr-manuel! ***"
echo



# check command line arguments
if [ -z "$1" ]; then

    # fetch version numbers for different versions
    echo -n "Fetch available version numbers..."

    # mr-manuel stable
    latest_release_mrmanuel_stable=$(curl -s https://api.github.com/repos/mr-manuel/venus-os_dbus-serialbattery/releases/latest | grep "tag_name" | cut -d : -f 2,3 | tr -d "\ " | tr -d \" | tr -d \,)

    # mr-manuel beta
    latest_release_mrmanuel_beta=$(curl -s https://api.github.com/repos/mr-manuel/venus-os_dbus-serialbattery/releases | grep "tag_name.*beta" | cut -d : -f 2,3 | tr -d "\ " | tr -d \" | tr -d \, | head -n 1)

    # mr-manuel master branch
    latest_release_mrmanuel_nightly=$(curl -s https://raw.githubusercontent.com/mr-manuel/venus-os_dbus-serialbattery/master/dbus-serialbattery/utils.py | grep DRIVER_VERSION | awk -F'"' '{print "v" $2}')

    # done
    echo " done."



    # show current installed version
    # driver >= v2.0.0
    if [ -f "/data/apps/dbus-serialbattery/utils.py" ]; then
        current_version=$(grep DRIVER_VERSION /data/apps/dbus-serialbattery/utils.py | awk -F'"' '{print $2}')
        echo
        echo "** Currently installed version: v$current_version **"
    # driver < v2.0.0
    elif [ -f "/data/etc/dbus-serialbattery/utils.py" ]; then
        current_version=$(grep DRIVER_VERSION /data/etc/dbus-serialbattery/utils.py | awk -F'"' '{print $2}')
        echo
        echo "** Currently installed version: v$current_version **"
    fi



    echo
    PS3=$'\nSelect which version you want to install from m-rmanuel\'s repo and enter the corresponding number: '

    # create list of versions
    version_list=(
        "stable release \"$latest_release_mrmanuel_stable\" (stable, most up to date)"
        "beta build \"$latest_release_mrmanuel_beta\" (no errors after 72 h runtime, long time testing needed)"
        "nightly build \"$latest_release_mrmanuel_nightly\" (newest features and fixes, bugs possible)"
        "specific branch (specific feature testing)"
        "specific version"
        "local tar file"
        "quit"
    )

    select version in "${version_list[@]}"
    do
        case $version in
            "stable release \"$latest_release_mrmanuel_stable\" (stable, most up to date)")
                break
                ;;
            "beta build \"$latest_release_mrmanuel_beta\" (no errors after 72 h runtime, long time testing needed)")
                break
                ;;
            "nightly build \"$latest_release_mrmanuel_nightly\" (newest features and fixes, bugs possible)")
                break
                ;;
            "specific branch (specific feature testing)")
                break
                ;;
            "specific version")
                break
                ;;
            "local tar file")
                break
                ;;
            "quit")
                exit 0
                ;;
            *)
                echo "> Invalid option: $REPLY. Please enter a number!"
                ;;
        esac
    done

    echo "> Selected: $version"
    echo ""

    if [ "$version" = "stable release \"$latest_release_mrmanuel_stable\" (stable, most up to date)" ]; then
        version="stable"
    elif [ "$version" = "beta build \"$latest_release_mrmanuel_beta\" (no errors after 72 h runtime, long time testing needed)" ]; then
        version="beta"
    elif [ "$version" = "nightly build \"$latest_release_mrmanuel_nightly\" (newest features and fixes, bugs possible)" ]; then
        version="nightly"
    elif [ "$version" = "specific branch (specific feature testing)" ]; then
        version="specific_branch"
    elif [ "$version" = "specific version" ]; then
        version="specific_version"
    elif [ "$version" = "local tar file" ]; then
        version="local"
    fi

elif [ "$1" = "--stable" ]; then
    version="stable"

elif [ "$1" = "--beta" ]; then
    version="beta"

elif [ "$1" = "--nightly" ]; then
    version="nightly"

elif [ "$1" = "--local" ]; then
    version="local"

else
    echo
    echo "No valid command line argument given. Possible arguments are:"
    echo "  --latest   Install the latest stable release from mr-manuel's repo"
    echo "  --beta     Install the latest beta release from mr-manuel's repo"
    echo "  --nightly  Install the latest nightly build from mr-manuel's repo"
    echo "  --local    Install a local tar file from \"/tmp/venus-data.tar.gz\""
    echo
    exit 1
fi



## stable release (mr-manuel, most up to date)
if [ "$version" = "stable" ]; then
    # download stable release
    curl -s https://api.github.com/repos/mr-manuel/venus-os_dbus-serialbattery/releases/latest | grep "browser_download_url.*gz" | cut -d : -f 2,3 | tr -d \" | wget -O /tmp/venus-data.tar.gz -qi -
fi

## beta release (mr-manuel, most up to date)
if [ "$version" = "beta" ]; then
    # download beta release
    curl -s https://api.github.com/repos/mr-manuel/venus-os_dbus-serialbattery/releases/tags/$latest_release_mrmanuel_beta | grep "browser_download_url.*gz" | cut -d : -f 2,3 | tr -d \" | wget -O /tmp/venus-data.tar.gz -qi -
fi

## specific version
if [ "$version" = "specific_version" ]; then
    # read the url
    read -r -p "Enter the url of the \"venus-data.tar.gz\" you want to install: " tar_url
    wget -O /tmp/venus-data.tar.gz "$tar_url"
    if [ $? -ne 0 ]; then
        echo "ERROR: Error during downloading the TAR file. Please check, if the URL is correct."
        exit 1
    fi
fi

## local tar file
if [ "$version" = "local" ]; then
    echo "Make sure the file is available at \"/tmp/venus-data.tar.gz\"."
    echo
fi


# create /data/apps if it do not exist
if [ ! -d "/data/apps" ]; then
    mkdir -p /data/apps
fi


# backup config.ini
backup_config


## extract the tar file
if [ "$version" = "stable" ] || [ "$version" = "beta" ] || [ "$version" = "specific_version" ] || [ "$version" = "local" ]; then

    # check if the tar file exists
    if [ ! -f "/tmp/venus-data.tar.gz" ]; then
        echo "ERROR: There is no file in \"/tmp/venus-data.tar.gz\""
        # restore config.ini
        restore_config
        exit 1
    fi

    # extract archive
    # driver >= v2.0.0
    if tar -tf /tmp/venus-data.tar.gz | grep -q '^dbus-serialbattery/'; then
        tar -zxf /tmp/venus-data.tar.gz -C /tmp --wildcards 'dbus-serialbattery/*'
    # driver < v2.0.0
    elif tar -tf /tmp/venus-data.tar.gz | grep -q '^etc/'; then
        tar -zxf /tmp/venus-data.tar.gz -C /tmp --wildcards 'etc/*'
    else
        echo "ERROR: TAR file does not contain expected data. Check the file and try again."
        # restore config.ini
        restore_config
        exit 1
    fi

    # check if the extraction was successful
    if [ $? -ne 0 ]; then
        echo "ERROR: Error during extracting the TAR file. Check the file and try again."
        # restore config.ini
        restore_config
        exit 1
    fi

    # remove old driver
    # driver >= v2.0.0
    if [ -d "/data/apps/dbus-serialbattery" ]; then
        rm -rf /data/apps/dbus-serialbattery
    fi
    # driver < v2.0.0
    if [ -d "/data/etc/dbus-serialbattery" ]; then
        rm -rf /data/etc/dbus-serialbattery
    fi

    # move driver to the correct location
    # driver >= v2.0.0
    if [ -d "/tmp/dbus-serialbattery" ]; then
        mv /tmp/dbus-serialbattery /data/apps/dbus-serialbattery
    # driver < v2.0.0
    elif [ -d "/tmp/etc/dbus-serialbattery" ]; then
        mv /tmp/etc/dbus-serialbattery /data/etc/dbus-serialbattery
        rmdir /tmp/etc
    else
        echo "ERROR: Something went wrong during moving the files from the temporary TAR location to the final location. Please try again."
        exit 1
    fi

    # cleanup
    rm /tmp/venus-data.tar.gz
    if [ -d "/tmp/etc" ]; then
        rm -rf /tmp/etc
    fi

fi



## nightly builds
if [ "$version" = "nightly" ] || [ "$version" = "specific_branch" ]; then

    # ask which branch to install
    if [ "$version" = "specific_branch" ]; then

        # fetch branches from Github
        branches=$(curl -s https://api.github.com/repos/mr-manuel/venus-os_dbus-serialbattery/branches | grep "name" | cut -d : -f 2,3 | tr -d \" | tr -d \,)

        # create a select menu
        echo
        PS3=$'\nSelect the branch you want to install and enter the corresponding number: '

        select branch in $branches
        do
            if [[ -z "$branch" ]]; then
                echo "> Invalid selection. Please try again."
            else
                break
            fi
        done

        echo "> Selected branch: $branch"

    else

        branch="master"

    fi

    # download driver
    wget -O /tmp/$branch.zip https://github.com/mr-manuel/venus-os_dbus-serialbattery/archive/refs/heads/$branch.zip

    # check if the download was successful
    if [ $? -ne 0 ]; then
        echo "ERROR: Error during downloading the ZIP file. Please try again."
        # restore config.ini
        restore_config
        exit 1
    fi

    # extract archive
    # driver >= v2.0.0
    if unzip -l /tmp/$branch.zip | awk '{print $4}' | grep -q "^venus-os_dbus-serialbattery-${branch}/dbus-serialbattery/"; then
        unzip -q /tmp/$branch.zip "venus-os_dbus-serialbattery-${branch}/dbus-serialbattery/*" -d /tmp
    # driver < v2.0.0
    elif unzip -l /tmp/$branch.zip | awk '{print $4}' | grep -q "^venus-os_dbus-serialbattery-${branch}/etc/dbus-serialbattery/"; then
        unzip -q /tmp/$branch.zip "venus-os_dbus-serialbattery-${branch}/etc/dbus-serialbattery/*" -d /tmp
    else
        echo "ERROR: ZIP file does not contain expected data. Check the file and try again."
        # restore config.ini
        restore_config
        exit 1
    fi

    # check if the extraction was successful
    if [ $? -ne 0 ]; then
        echo "ERROR: Error during extracting the ZIP file. Check the file and try again."
        # restore config.ini
        restore_config
        exit 1
    fi

    # remove old driver
    # driver >= v2.0.0
    if [ -d "/data/apps/dbus-serialbattery" ]; then
        rm -rf /data/apps/dbus-serialbattery
    fi
    # driver < v2.0.0
    if [ -d "/data/etc/dbus-serialbattery" ]; then
        rm -rf /data/etc/dbus-serialbattery
    fi

    # move driver to the correct location
    # driver >= v2.0.0
    if [ -d "/tmp/venus-os_dbus-serialbattery-$branch/dbus-serialbattery" ]; then
        mv /tmp/venus-os_dbus-serialbattery-$branch/dbus-serialbattery /data/apps
    # driver < v2.0.0
    elif [ -d "/tmp/venus-os_dbus-serialbattery-$branch/etc/dbus-serialbattery" ]; then
        mv /tmp/venus-os_dbus-serialbattery-$branch/etc/dbus-serialbattery /data/etc
    else
        echo "ERROR: Something went wrong during moving the files from the temporary ZIP location to the final location. Please try again."
        exit 1
    fi

    # cleanup
    rm /tmp/$branch.zip
    rm -rf /tmp/venus-os_dbus-serialbattery-$branch

fi


# fix permissions, owner and group
if [ -d "/data/apps/dbus-serialbattery" ]; then
    chmod +x /data/apps/dbus-serialbattery/*.sh
    chmod +x /data/apps/dbus-serialbattery/*.py
    chmod +x /data/apps/dbus-serialbattery/service/run
    chmod +x /data/apps/dbus-serialbattery/service/log/run

    chown -R root:root /data/apps/dbus-serialbattery
elif [ -d "/data/etc/dbus-serialbattery" ]; then
    chmod +x /data/etc/dbus-serialbattery/*.sh
    chmod +x /data/etc/dbus-serialbattery/*.py
    chmod +x /data/etc/dbus-serialbattery/service/run
    chmod +x /data/etc/dbus-serialbattery/service/log/run

    chown -R root:root /data/etc/dbus-serialbattery
fi



# restore config.ini
restore_config


# check if installed version is >= v2.0.0
if [ -d "/data/apps/dbus-serialbattery" ]; then
    # install overlay-fs if not already installed
    if [ ! -d "/data/apps/overlay-fs" ]; then
        if [ -d "/data/apps/dbus-serialbattery/ext/venus-os_overlay-fs" ]; then
            echo
            echo "Install overlay-fs app..."
            bash /data/apps/dbus-serialbattery/ext/venus-os_overlay-fs/install.sh --copy
        else
            echo "ERROR: overlay-fs app not found. Please install it manually."
        fi
    else
        echo
    fi
fi



# run install script >= v2.0.0
if [ -f "/data/apps/dbus-serialbattery/enable.sh" ]; then
    bash /data/apps/dbus-serialbattery/enable.sh
# run install script >= v1.0.0 and < v2.0.0
elif [ -f "/data/etc/dbus-serialbattery/reinstall-local.sh" ]; then
    bash /data/etc/dbus-serialbattery/reinstall-local.sh
# run install script < v1.0.0
elif [ -f "/data/etc/dbus-serialbattery/reinstalllocal.sh" ]; then
    bash /data/etc/dbus-serialbattery/reinstalllocal.sh
fi
