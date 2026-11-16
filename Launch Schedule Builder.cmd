@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo Schedule Builder could not start. See the message above and the logs folder.
  if not "%SCHEDULE_BUILDER_NONINTERACTIVE%"=="1" pause
)
exit /b %RESULT%
