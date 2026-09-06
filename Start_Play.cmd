@echo off
setlocal
title Orbit Play Session
cd /d "%~dp0"
python --version >nul 2>&1
if errorlevel 1 goto py_launcher
python "%~dp0Play.py"
goto finished
:py_launcher
py -3 --version >nul 2>&1
if errorlevel 1 goto missing
py -3 "%~dp0Play.py"
goto finished
:missing
echo Python was not found. Send a screenshot of this window.
:finished
echo.
echo Session ended. Stop tracking in OpenTrack. Errors remain visible above.
pause
