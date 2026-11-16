@echo off
setlocal
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\stop.py" %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo Daycraft did not stop. Review the message above. No unrelated process was terminated.
  if not "%SCHEDULE_BUILDER_NONINTERACTIVE%"=="1" pause
)
exit /b %RESULT%
