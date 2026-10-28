@echo off
rem SPDX-License-Identifier: GPL-3.0-only
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "motor_simulator.py" --visible --quick-test
) else if exist "..\.venv\Scripts\python.exe" (
  "..\.venv\Scripts\python.exe" "motor_simulator.py" --visible --quick-test
) else (
  python "motor_simulator.py" --visible --quick-test
)
set "SIM_EXIT=%ERRORLEVEL%"
echo.
if not "%SIM_EXIT%"=="0" echo Simulation exited with error code %SIM_EXIT%. See docs/INSTALLATION.md.
pause
exit /b %SIM_EXIT%
