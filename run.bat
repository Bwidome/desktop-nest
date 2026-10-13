@echo off
rem ===================================================================
rem  Desktop Nest - launcher (ASCII-only name, for command-line use)
rem
rem  Same as the Chinese-named launcher; provided because a Chinese
rem  filename is awkward to type at a command prompt.
rem ===================================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "PY="
for %%C in (pythonw.exe) do if not "%%~$PATH:C"=="" set "PY=%%~$PATH:C"
for %%C in (python.exe)  do if not "%%~$PATH:C"=="" set "PY=%%~$PATH:C"
if not defined PY call :trypath "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY call :trypath "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY call :trypath "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY call :trypath "%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not defined PY goto :nopython

start "" "%PY%" "%~dp0main.py" %*
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
