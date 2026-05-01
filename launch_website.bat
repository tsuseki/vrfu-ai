@echo off
:: vrfu-ai — start the local web UI on http://localhost:8765
::
:: Closing this cmd window will stop the server cleanly.
:: If a previous server is still running on this port, this script kills it first
:: so we never end up with duplicate servers.

setlocal

:: Kill any existing process listening on 127.0.0.1:8765 (a previous server we left behind).
:: Using PowerShell because cmd's findstr treats spaces in patterns as logical OR — the
:: previous regex-style version accidentally matched ALL listening processes and would
:: kill anything with a TCP listener (Discord, Steam, etc.). Get-NetTCPConnection is exact.
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8765 -LocalAddress 127.0.0.1 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1

cd /d "%~dp0web"
start "" "http://localhost:8765"
"%~dp0ai-toolkit\venv\Scripts\python.exe" server.py
pause
