#!/bin/bash

python -m uiautomator2 init 2>&1 >> init.log

daemon -rU --name weditor --chdir=$PWD --stdout $PWD/stdout.log --stderr $PWD/stderr.log -- python -m weditor -q
