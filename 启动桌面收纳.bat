@echo off
rem ===================================================================
rem  Desktop Nest - launcher
rem  ASCII only in this file so it renders in any console codepage.
rem
rem  Picks a Python that can actually import the Qt bindings, then starts
rem  the tray app detached so no console window stays open.
rem ===================================================================
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"

set "PY="

rem -- 1. Python already on PATH -----------------------------------
for %%C in (pythonw.exe) do if not "%%~$PATH:C"=="" call :consider "%%~$PATH:C"
for %%C in (python.exe)  do if not "%%~$PATH:C"=="" call :consider "%%~$PATH:C"

rem -- 2. Common install locations ---------------------------------
call :consider "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
call :consider "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
call :consider "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
call :consider "%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe"
call :consider "%LOCALAPPDATA%\Programs\Python\Python39\pythonw.exe"
call :consider "C:\Python313\pythonw.exe"
call :consider "C:\Python312\pythonw.exe"
call :consider "C:\Python311\pythonw.exe"

rem -- 3. The runtime bundled with DeepSeek Harness ----------------
call :consider "%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe"

if not defined PY goto :nopython

if /i "%~1"=="shortcut" goto :makeshortcut
if /i "%~1"=="/shortcut" goto :makeshortcut
start "" "%PY%" "%~dp0main.py" %*
exit /b 0

:makeshortcut
"%PY%" "%~dp0create_shortcut.py"
pause
exit /b 0
exit /b 0

rem ===================================================================
:consider
rem %1 = candidate interpreter; accept only if it can import Qt.
if defined PY goto :eof
if not exist %1 goto :eof
%1 -c "import sys; sys.path.insert(0, r'%~dp0libs'); import PyQt6.QtWidgets" >nul 2>&1
if errorlevel 1 goto :eof
set "PY=%~1"
goto :eof

:nopython
echo.
echo   [X] No usable Python + Qt found.
echo.
echo   Do this:
echo     1. Install Python 3.10 - 3.13 from python.org
echo        and tick "Add python.exe to PATH".
echo     2. Then double-click  install.bat  once.
echo.
pause
exit /b 1
