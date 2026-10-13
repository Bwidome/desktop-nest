@echo off
rem ===================================================================
rem  Restore Desktop - recovery helper
rem  ASCII only in this file so it renders in any console codepage.
rem
rem  Moves everything out of the hidden nest folder back to the desktop
rem  (shared-desktop shortcuts go back to the shared desktop).
rem  Nothing is deleted; files are only moved.
rem ===================================================================
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"

set "PY="
for %%C in (pythonw.exe) do if not "%%~$PATH:C"=="" set "PY=%%~$PATH:C"
for %%C in (python.exe)  do if not "%%~$PATH:C"=="" set "PY=%%~$PATH:C"
if not defined PY call :trypath "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY call :trypath "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY call :trypath "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY call :trypath "%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not defined PY goto :nopython

"%PY%" "%~dp0restore_desktop.py"
echo.
pause
exit /b 0

:trypath
if not defined PY if exist %1 set "PY=%~1"
goto :eof

:nopython
echo.
echo   [X] Python not found. Install Python 3.9+ first.
echo.
pause
exit /b 1
