@echo off
if "%~1"=="" goto default_window
call "%~dp0start.bat" --desktop %*
exit /b %errorlevel%
:default_window
call "%~dp0start.bat"
exit /b %errorlevel%
