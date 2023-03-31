#!/bin/bash

python -m uiautomator2 init >> init.log 2>&1

arg="-q"

d=$(grep capture /proc/asound/pcm | sort -r | head -n 1 | awk -F- '{print $1+0;}')
if [ -n "$d" ]; then
    arg="$arg -d $d"
fi

daemon -rU --name weditor --chdir=$PWD --stdout $PWD/stdout.log --stderr $PWD/stderr.log -- python -m weditor $arg
