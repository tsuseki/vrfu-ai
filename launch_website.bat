@echo off
:: vrfu-ai — start the local web UI on http://localhost:8765
::
:: Closing this cmd window will stop the server cleanly.
:: If a previous server is still running on this port, this script kills it first
:: so we never end up with duplicate servers.

setlocal

:: Kill any existing process listening on 8765
for /f "tokens=5" %%a in ('netstat -ano ^| findstr "127.0.0.1:8765 .*LISTENING"') do (
  taskkill /F /PID %%a >nul 2>&1
)

cd /d "%~dp0web"
start "" "http://localhost:8765"
"%~dp0ai-toolkit\venv\Scripts\python.exe" server.py
pause
