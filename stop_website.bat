@echo off
:: Stops any vrfu-ai web server still listening on port 8765.
:: Use this if a server is stuck running in the background after you closed the cmd.

setlocal
set "FOUND=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr "127.0.0.1:8765 .*LISTENING"') do (
  taskkill /F /PID %%a >nul 2>&1 && (
    echo Killed server PID %%a
    set "FOUND=1"
  )
)
if %FOUND%==0 echo No server was running on port 8765.
pause
