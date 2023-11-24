#!/bin/bash

adb root >> init.log 2>&1
adb tcpip 5555 >> init.log 2>&1
adb shell "setprop bmi.service.adb.root 1" >> init.log 2>&1
python -m uiautomator2 purge >> init.log 2>&1
python -m uiautomator2 init >> init.log 2>&1
adb forward --list >> init.log 2>&1

arg="-q"

d=$(grep capture /proc/asound/pcm | sort -r | head -n 1 | awk -F- '{print $1+0;}')
if [ -n "$d" ]; then
    arg="$arg -d $d"
fi

daemon --stop --name weditor

PIDFILE="$HOME/.weditor/weditor.pid"
if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if [ -n "$PID" -a -d "/proc/$PID" ]; then
        kill $PID
        while [ -d "/proc/$PID" ]; do sleep 1;done
    fi
    rm -vf "$PIDFILE"
fi
daemon -irU -M 1000000 -L 10 --name weditor --chdir=$PWD -- sh -c "python -m weditor $arg < /dev/null >> stdout.log 2>> stderr.log"
