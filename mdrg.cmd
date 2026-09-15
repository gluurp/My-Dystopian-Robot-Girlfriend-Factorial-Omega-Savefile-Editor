@echo off
REM ===================================================================
REM  mdrg-cli launcher for Windows
REM
REM  Usage:  mdrg.cmd scan
REM          mdrg.cmd inventory
REM          mdrg.cmd where
REM          mdrg.cmd edit "M7.mdrgslot"
REM
REM  Finds a Python 3 interpreter, sets UTF-8 console output, and runs
REM  mdrg-cli.py with the same arguments you passed here.
REM ===================================================================

setlocal

set "HERE=%~dp0"
set "CLI=%HERE%mdrg-cli.py"

REM --- make the console emit UTF-8 so the box-drawing glyphs survive ---
chcp 65001 >nul 2>&1
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM --- locate a Python 3 interpreter -----------------------------------
set "PY="

where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
    where python3 >nul 2>&1 && set "PY=python3"
)

if not defined PY (
    echo.
    echo   Could not find Python 3.
    echo.
    echo   Install it from https://www.python.org/downloads/windows/
    echo   and tick "Add python.exe to PATH" during setup.
    echo.
    echo   For the interactive editor you also need:
    echo       pip install windows-curses
    echo.
    exit /b 1
)

if not exist "%CLI%" (
    echo   mdrg-cli.py not found next to this script: %CLI%
    exit /b 1
)

%PY% "%CLI%" %*
exit /b %ERRORLEVEL%
