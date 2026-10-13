@echo off
rem ===================================================================
rem  Move shared-desktop shortcuts back to the shared desktop
rem
rem  Right-click this file and choose "Run as administrator".
rem  It only MOVES 10 shortcuts from your personal desktop to
rem  C:\Users\Public\Desktop - nothing is deleted.
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

"%PY%" "%~dp0fix_public_desktop.py"
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
