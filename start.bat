@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto check_dependencies
where py >nul 2>&1
if errorlevel 1 goto use_python
py -3 -m venv .venv
if errorlevel 1 goto setup_failed
goto check_dependencies
:use_python
python -m venv .venv
if errorlevel 1 goto setup_failed
:check_dependencies
".venv\Scripts\python.exe" -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11 or newer is required'"
if errorlevel 1 goto setup_failed
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, httpx, jsonschema, referencing, pydantic" >nul 2>&1
if not errorlevel 1 goto run_bridge
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto setup_failed
:run_bridge
".venv\Scripts\python.exe" -m bridge_x %*
set "BRIDGE_START_EXIT_CODE=%errorlevel%"
if not "%BRIDGE_START_EXIT_CODE%"=="0" pause
exit /b %BRIDGE_START_EXIT_CODE%
:setup_failed
echo Setup failed. Install Python 3.11 or newer and follow README.md.
pause
exit /b 1
