@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto check_dependencies
where py >nul 2>&1
if errorlevel 1 goto use_python
py -3 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1
if errorlevel 1 goto use_python
py -3 -m venv --without-pip .venv
if errorlevel 1 goto venv_failed
goto check_dependencies
:use_python
python -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1
if errorlevel 1 goto python_missing
python -m venv --without-pip .venv
if errorlevel 1 goto venv_failed
:check_dependencies
".venv\Scripts\python.exe" -c "import sys; assert sys.version_info >= (3,11) and sys.prefix != sys.base_prefix, 'A working Python 3.11+ virtual environment is required'"
if errorlevel 1 goto environment_invalid
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, httpx, jsonschema, referencing, pydantic" >nul 2>&1
if not errorlevel 1 goto run_bridge
".venv\Scripts\python.exe" -m pip --version >nul 2>&1
if not errorlevel 1 goto install_dependencies
echo Python is available. Restoring missing pip in .venv using ensurepip...
".venv\Scripts\python.exe" -m ensurepip --upgrade --default-pip
if errorlevel 1 goto pip_failed
".venv\Scripts\python.exe" -m pip --version >nul 2>&1
if errorlevel 1 goto pip_failed
:install_dependencies
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto dependencies_failed
:run_bridge
if "%~1"=="" goto run_desktop
".venv\Scripts\python.exe" -m bridge_x %*
set "BRIDGE_START_EXIT_CODE=%errorlevel%"
if not "%BRIDGE_START_EXIT_CODE%"=="0" pause
exit /b %BRIDGE_START_EXIT_CODE%
:run_desktop
".venv\Scripts\python.exe" -c "import tkinter" >nul 2>&1
if errorlevel 1 goto tkinter_missing
start "" ".venv\Scripts\pythonw.exe" -m bridge_x --desktop --provider molab
exit /b %errorlevel%
:tkinter_missing
echo TK_UNAVAILABLE: Python needs the Tcl/Tk component for the native window.
echo Run start.bat --headless for terminal mode, or enable Tcl/Tk in Python setup.
goto setup_failed
:python_missing
echo PYTHON_UNAVAILABLE: No usable Python 3.11+ was found through py or python.
echo Check your Python launcher and PATH. See README.md.
goto setup_failed
:venv_failed
echo VENV_CREATE_FAILED: Python was found but could not create .venv.
echo Check folder permissions and Python's venv component. Existing files were retained.
goto setup_failed
:environment_invalid
echo VENV_INVALID: The existing .venv interpreter is unusable or older than Python 3.11.
echo Preserve your configuration and journal. Repair or rename only .venv, then retry.
goto setup_failed
:pip_failed
echo PIP_BOOTSTRAP_FAILED: Python runs, but pip could not be restored in .venv.
echo Check the ensurepip component of your base Python installation. See README.md.
goto setup_failed
:dependencies_failed
echo DEPENDENCY_INSTALL_FAILED: Python and pip are available, but requirements installation failed.
echo Check the installer message above, package-download access and requirements.txt.
:setup_failed
pause
exit /b 1
