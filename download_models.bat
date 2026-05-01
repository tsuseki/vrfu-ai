@echo off
REM ─── Optional model downloader ────────────────────────────────────────────
REM Pulls the default base SDXL checkpoint via huggingface-cli.
REM
REM Skip this script if you'd rather download the model manually — see
REM docs/install.md for direct links to Civitai / HuggingFace pages.
REM
REM Requires the venv built by setup.bat.

setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%ai-toolkit\venv\Scripts\python.exe"
set "TARGET=%ROOT%checkpoints\waiIllustriousSDXL_v170.safetensors"

if not exist "%PY%" (
    echo ERROR: venv not found. Run setup.bat first.
    goto :fail
)

if exist "%TARGET%" (
    echo Already downloaded: %TARGET%
    goto :end
)

if not exist "%ROOT%checkpoints" mkdir "%ROOT%checkpoints"

echo Downloading waiIllustriousSDXL v1.7.0 (~7 GB, takes 10-30 min)...
echo.

REM Pin huggingface_hub to <1.0 because transformers 4.57.x (used at generation
REM time) refuses to load against huggingface_hub>=1.0. Without this pin, every
REM run of this script re-upgrades the package and breaks generation.
"%PY%" -m pip install --quiet "huggingface_hub>=0.34.0,<1.0"
if errorlevel 1 goto :fail

"%PY%" -c "from huggingface_hub import hf_hub_download; hf_hub_download('John6666/wai-illustrious-sdxl-v170-sdxl', 'waiIllustriousSDXL_v170.safetensors', local_dir=r'%ROOT%checkpoints')"
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo  Downloaded: %TARGET%
echo ============================================================

:end
echo.
echo Press any key to close this window.
pause >nul
endlocal
exit /b 0

:fail
echo.
echo ============================================================
echo  Download FAILED. See the error above.
echo  Manual download: see docs/install.md for direct links.
echo ============================================================
echo.
echo Press any key to close this window.
pause >nul
endlocal
exit /b 1
