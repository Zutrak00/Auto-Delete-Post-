@echo off
rem Windows: double-click this file to set up (first run only) and open the dashboard.
cd /d "%~dp0"

set PYTHON=
where py >nul 2>nul && set PYTHON=py -3
if not defined PYTHON (
  where python >nul 2>nul && set PYTHON=python
)
if not defined PYTHON (
  echo Python 3.10 or newer is required. Get it from https://www.python.org/downloads/
  echo During install, tick "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist .venv\Scripts\python.exe (
  echo First run: setting up, this takes a minute...
  %PYTHON% -m venv .venv || goto :error
)

rem Reinstall dependencies only when requirements.txt changes.
fc /b requirements.txt .venv\installed-requirements.txt >nul 2>nul
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
  .venv\Scripts\python.exe -m pip install --quiet -r requirements.txt || goto :error
  copy /y requirements.txt .venv\installed-requirements.txt >nul
)

.venv\Scripts\python.exe -m autodelete web --open %*
pause
exit /b 0

:error
echo Setup failed. Scroll up for the error message.
pause
exit /b 1
