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
"%PY%" -m pip install --quiet --upgrade huggingface_hub
"%PY%" -c "from huggingface_hub import hf_hub_download; hf_hub_download('John6666/wai-illustrious-sdxl-v170-sdxl', 'waiIllustriousSDXL_v170.safetensors', local_dir=r'%ROOT%checkpoints', local_dir_use_symlinks=False)"
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo  Downloaded: %TARGET%
echo ============================================================

:end
endlocal
exit /b 0

:fail
echo.
echo ============================================================
echo  Download FAILED.
echo  Manual download: see docs/install.md for direct links.
echo ============================================================
endlocal
exit /b 1
