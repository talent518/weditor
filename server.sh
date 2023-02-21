#!/bin/bash

python -m uiautomator2 init >> init.log 2>&1

daemon -rU --name weditor --chdir=$PWD --stdout $PWD/stdout.log --stderr $PWD/stderr.log -- python -m weditor -q
