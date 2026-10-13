@echo off
rem ===================================================================
rem  Desktop Nest - dependency installer
rem  ASCII only so it renders in any console codepage.
rem ===================================================================
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"

set "PY="
for %%C in (python.exe) do if not "%%~$PATH:C"=="" set "PY=%%~$PATH:C"
if not defined PY call :trypath "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY call :trypath "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY call :trypath "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY call :trypath "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PY call :trypath "C:\Python313\python.exe"
if not defined PY call :trypath "C:\Python312\python.exe"
if not defined PY call :trypath "%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not defined PY goto :nopython

echo.
echo   Using Python: %PY%
echo.

rem -- already installed? -------------------------------------------
"%PY%" -c "import sys; sys.path.insert(0, r'%~dp0libs'); import PyQt6.QtWidgets" >nul 2>&1
if not errorlevel 1 (
    echo   [OK] PyQt6 is already available. Nothing to do.
    echo.
    pause
    exit /b 0
)

rem -- try pip first, it is the normal way --------------------------
echo   Trying pip install PyQt6 ...
"%PY%" -m pip install --disable-pip-version-check --no-input PyQt6
"%PY%" -c "import PyQt6.QtWidgets" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo   [OK] PyQt6 installed into the system Python.
    echo.
    pause
    exit /b 0
)

rem -- fall back to downloading the wheels straight into libs\ -----
echo.
echo   pip did not work here. Downloading the wheels directly instead...
echo   (about 70 MB, one time only)
echo.
"%PY%" "%~dp0setup_libs.py"
if errorlevel 1 goto :failed

echo.
echo   [OK] Done. You can start the app now.
echo.
pause
exit /b 0

:trypath
if not defined PY if exist %1 set "PY=%~1"
goto :eof

:nopython
echo.
echo   [X] Python not found.
echo.
echo       Install Python 3.10 - 3.13 from python.org
echo       and tick "Add python.exe to PATH" during setup.
echo.
pause
exit /b 1

:failed
echo.
echo   [X] Could not install PyQt6 automatically.
echo.
echo       Open a terminal in this folder and run:
echo           python -m pip install PyQt6
echo.
pause
exit /b 1
