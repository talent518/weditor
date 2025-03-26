#!/bin/bash --login

LOCKFILE="$HOME/.weditor/weditor.lock"
if [ -f $LOCKFILE ]; then
  pid=$(cat $LOCKFILE)
  c=$(egrep -c ^server\\.sh /proc/$pid/comm)
  if [ $c -eq 1 ]; then
    echo "weditor server shell is locked."
    exit 1
  fi
fi

echo -n $$ > $LOCKFILE

echo "Ignore sound device found: touch .ignore.pcm"
echo "Ignore adb and uiautomator2 init: touch .ignore.init"
echo "weditor argument file: .weditor.arg"

truncate -s0 *.log

if [ ! -f ".ignore.init" ]; then
    adb tcpip 5555 >> init.log 2>&1
    sleep 10
    adb root >> init.log 2>&1
    sleep 2
    adb shell setprop bmi.service.adb.root 1 >> init.log 2>&1
    adb shell "setprop bmi.service.adb.root 1" >> init.log 2>&1
    python -m uiautomator2 purge >> init.log 2>&1
    python -m uiautomator2 init >> init.log 2>&1
    adb forward --list >> init.log 2>&1
fi

arg="-q"

if [ ! -f ".ignore.pcm" ]; then
    d=$(grep capture /proc/asound/pcm | sort -r | head -n 1 | awk -F- '{print $1+0;}')
    if [ -n "$d" ]; then
        arg="$arg -d $d"
    fi
fi

if [ -f ".weditor.arg" ]; then
    arg="$arg $(cat .weditor.arg)"
fi

daemon --stop --name weditor

PIDFILE="$HOME/.weditor/weditor.pid"
if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if [ -n "$PID" -a -d "/proc/$PID" ]; then
        kill $PID
        while [ -d "/proc/$PID" ]; do sleep 1;done
    fi
    rm -f "$PIDFILE"
fi

daemon -irU -M 1000000 -L 10 --name weditor --chdir=$PWD --stdout stdout.log --stderr stderr.log -- python -m weditor $arg $@

rm -f $LOCKFILE
