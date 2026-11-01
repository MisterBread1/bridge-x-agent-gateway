@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto local_python
where py >nul 2>&1
if errorlevel 1 goto system_python
py -3 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1
if errorlevel 1 goto system_python
py -3 -m tools.copy_key
goto finish
:system_python
python -m tools.copy_key
goto finish
:local_python
".venv\Scripts\python.exe" -m tools.copy_key
:finish
set "BRIDGE_COPY_EXIT_CODE=%errorlevel%"
pause
exit /b %BRIDGE_COPY_EXIT_CODE%
