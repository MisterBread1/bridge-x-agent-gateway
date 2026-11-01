@echo off
call "%~dp0start.bat" --ui %*
exit /b %errorlevel%
