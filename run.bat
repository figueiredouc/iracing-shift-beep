@echo off
pushd "%~dp0"
py -3 "%~dp0shift_beep.py" %*
popd
pause
