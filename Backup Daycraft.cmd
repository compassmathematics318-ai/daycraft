@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0scripts\backup.py" %*
) else (
  python "%~dp0scripts\backup.py" %*
)
set "RESULT=%ERRORLEVEL%"
echo.
if not "%SCHEDULE_BUILDER_NONINTERACTIVE%"=="1" pause
exit /b %RESULT%
