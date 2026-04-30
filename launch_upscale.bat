@echo off
:: vrfu-ai — run the hires-fix upscaler on a character's liked/ folder.
:: Usage: launch_upscale.bat <character_name>
setlocal
set "CHAR=%~1"
cd /d "%~dp0scripts"
if "%CHAR%"=="" (
  "%~dp0ai-toolkit\venv\Scripts\python.exe" upscale.py
) else (
  "%~dp0ai-toolkit\venv\Scripts\python.exe" upscale.py --character %CHAR%
)
pause
