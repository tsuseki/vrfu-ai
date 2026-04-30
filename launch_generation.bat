@echo off
:: vrfu-ai — run the generation queue from the command line.
:: Usage: drag-drop or call:  launch_generation.bat <character_name>
::        Defaults to picking the only character if there's exactly one.
setlocal
set "CHAR=%~1"
cd /d "%~dp0scripts"
if "%CHAR%"=="" (
  "%~dp0ai-toolkit\venv\Scripts\python.exe" generate.py
) else (
  "%~dp0ai-toolkit\venv\Scripts\python.exe" generate.py --character %CHAR%
)
pause
