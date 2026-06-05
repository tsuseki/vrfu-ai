@echo off
:: vrfu-ai - autostart variant (no browser auto-open, no pause).
:: Registered as a Windows scheduled task at user logon - see
:: install_autostart.ps1 / uninstall_autostart.ps1.
::
:: Closing the spawned window stops the server cleanly. To stop without
:: rebooting: end "python.exe" running server.py, or run
::   powershell -c "Get-NetTCPConnection -LocalPort 8765 -LocalAddress 127.0.0.1 -State Listen | %% { Stop-Process -Id $_.OwningProcess -Force }"

setlocal

:: Kill any existing process listening on 127.0.0.1:8765 (e.g. an orphan from a prior session).
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8765 -LocalAddress 127.0.0.1 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1

cd /d "%~dp0web"
"%~dp0ai-toolkit\venv\Scripts\python.exe" server.py
