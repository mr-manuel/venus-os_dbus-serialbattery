velib_python
============

[![Build Status](https://travis-ci.com/victronenergy/velib_python.svg?branch=master)](https://travis-ci.org/victronenergy/velib_python)

This is the general python library within Victron. It contains code that is related to D-Bus and the Color
Control GX. See http://www.victronenergy.com/panel-systems-remote-monitoring/colorcontrol/ for more
infomation about that panel.

Files  busitem.py, dbusitem.py and tracing.py are deprecated.

The main files are vedbus.py, dbusmonitor.py and settingsdevice.py.

- Use VeDbusService to put your process on dbus and let other services interact with you.
- Use VeDbusItemImport to read a single value from other processes the dbus, and monitor its signals.
- Use DbusMonitor to monitor multiple values from other processes
- Use SettingsDevice to store your settings in flash, via the com.victronenergy.settings dbus service. See
https://github.com/victronenergy/localsettings for more info.

Code style
==========

Comply with PEP8, except:
- use tabs instead of spaces, since we use tabs for all projects within Victron.
- max line length = 110

Run this command to set git diff to tabsize is 4 spaces. Replace --local with --global to do it globally for the current
user account.

    git config --local core.pager 'less -x4'

Run this command to check your code agains PEP8

    pep8 --max-line-length=110 --ignore=W191 *.py
    
D-Bus
=====

D-Bus is an/the inter process communication bus used on Linux for many things. Victron uses it on the CCGX to have all the different processes exchange data. Protocol drivers publish data read from products (for example battery voltage) on the D-Bus, and other processes (the GUI for example) takes it from the D-Bus to show it on the display.

Libraries that implement D-Bus connectivity are available in many programming languages (C, Python, etc). There are also many commandline tools available to talk to a running process via D-bus. See for example the dbuscli (executeable name dbus): http://code.google.com/p/dbus-tools/wiki/DBusCli, and also dbus-monitor and dbus-send.

There are two sides in using the D-Bus, putting information on it (exporting as service with objects) and reading/writing to a process exporting a service. Note that instead of reading with GetValue, you can also subscribe to receive a signal when datachanges. Doing this saves unncessary context-switches in most cases.

To get an idea of how to publish data on the dbus, run the example:

    matthijs@matthijs-VirtualBox:~/dev/velib_python/examples$ python vedbusservice_example.py 
    vedbusservice_example.py starting up
    /Position value is 5
    /Position value is now 10
    try changing our RPM by executing the following command from a terminal

    dbus-send --print-reply --dest=com.victronenergy.example /RPM com.victronenergy.BusItem.SetValue int32:1200
    Reply will be <> 0 for values > 1000: not accepted. And reply will be 0 for values < 1000: accepted.
    
Leave that terminal open, start a second terminal, and interrogate above service from the commandline:

    matthijs@matthijs-VirtualBox:~/dev/velib_python/examples$ dbus
    org.freedesktop.DBus
    org.freedesktop.PowerManagement
    com.victronenergy.example
    org.xfce.Terminal5
    org.xfce.Xfconf
    [and many more services in which we are not interested]
    
To get more details, add the servicename:

    matthijs@matthijs-VirtualBox:~/dev/velib_python/examples$ dbus com.victronenergy.example
    /
    /Float
    /Int
    /NegativeInt
    /Position
    /RPM
    /String

And get the value for the position:

    matthijs@matthijs-VirtualBox:~/dev/velib_python/examples$ dbus com.victronenergy.example /RPM GetValue
    100

And setting the value is also possible, the % makes dbus evaluate what comes behind it, resulting in an int instead of the default (a string).:

    matthijs@matthijs-VirtualBox:~/dev/velib_python/examples$ dbus com.victronenergy.example /RPM SetValue %1
    0

In this example, the 0 indicates succes. When trying an unsupported value, 2000, this is what happens:

    matthijs@matthijs-VirtualBox:~/dev/velib_python/examples$ dbus com.victronenergy.example /RPM SetValue %2000
    2

Exporting services, and the object paths (/Float, /Position, /Group1/Value1, etcetera) is standard D-Bus functionality. At Victron we designed and implemented a D-Bus interface, called com.victronenergy.BusItem. Example showing all interfaces supported by an object:

    matthijs@matthijs-VirtualBox:~/dev/velib_python/examples$ dbus com.victronenergy.example /RPM
    Interface org.freedesktop.DBus.Introspectable:
     String Introspect()
    
    Interface com.victronenergy.BusItem:
     Int32 SetValue(Variant newvalue)
     String GetDescription(String language, Int32 length)
     String GetText()
     Variant GetValue()
