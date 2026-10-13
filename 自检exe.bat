@echo off
rem ===================================================================
rem  Startup self-test for the packaged (exe) build.
rem
rem  Double-click this file. It runs the exe with --selftest and writes
rem  the output to selftest-result.txt next to this script.
rem
rem  IMPORTANT: this file is deliberately ASCII-only. cmd.exe reads .bat
rem  files using the OEM codepage, so non-ASCII text here gets mangled
rem  into bogus "commands" before chcp can take effect.
rem ===================================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "EXE="
for /f "delims=" %%F in ('dir /b /s "%~dp0dist-new\*.exe" 2^>nul') do if not defined EXE set "EXE=%%F"
if not defined EXE for /f "delims=" %%F in ('dir /b /s "%~dp0dist\*.exe" 2^>nul') do if not defined EXE set "EXE=%%F"

if not defined EXE (
  echo.
  echo   [X] No .exe found under dist-new\ or dist\
  echo.
  pause
  exit /b 1
)

echo.
echo   Testing:
echo     %EXE%
echo   ------------------------------------------------------------
echo.

"%EXE%" --selftest > "%~dp0selftest-result.txt" 2>&1
set RC=%ERRORLEVEL%
type "%~dp0selftest-result.txt"

echo.
echo   ------------------------------------------------------------
echo   Exit code: %RC%
if "%RC%"=="0" (
  echo   RESULT: PASSED - the exe starts fine on this machine.
) else (
  echo   RESULT: FAILED - please send selftest-result.txt back.
)
echo.
pause
exit /b %RC%
