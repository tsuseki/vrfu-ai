@echo off
REM ─── vrfu-ai — first-time setup for Windows ────────────────────────
REM Builds the ai-toolkit venv and installs the project's Python deps.
REM Safe to re-run; skips steps that are already done.

setlocal
set "ROOT=%~dp0"
set "AT_DIR=%ROOT%ai-toolkit"
set "VENV=%AT_DIR%\venv"
set "PY=%VENV%\Scripts\python.exe"

echo.
echo ============================================================
echo  vrfu-ai setup
echo  Repo root: %ROOT%
echo ============================================================
echo.

REM Step 1: verify prerequisites
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not on PATH. Install Python 3.10 or 3.11 from
    echo        https://www.python.org/downloads/ and check "Add to PATH".
    goto :fail
)
where git >nul 2>&1
if errorlevel 1 (
    echo ERROR: Git is not on PATH. Install Git from https://git-scm.com/downloads/.
    goto :fail
)

REM Step 1b: initialize ai-toolkit submodule if missing
REM (handles flat clones where the user forgot --recursive)
if not exist "%AT_DIR%\.git" (
    echo [pre] ai-toolkit submodule not initialized; pulling now...
    cd /d "%ROOT%"
    git submodule update --init --recursive
    if errorlevel 1 goto :fail
)

REM Step 2: build venv if missing
if not exist "%PY%" (
    echo [1/3] Creating venv at vendor\ai-toolkit\venv ...
    python -m venv "%VENV%"
    if errorlevel 1 goto :fail
) else (
    echo [1/3] venv already exists at vendor\ai-toolkit\venv  [skip]
)

REM Step 3: install ai-toolkit's deps
echo.
echo [2/4] Installing ai-toolkit dependencies (this can take ~10 min)...
"%PY%" -m pip install --upgrade pip wheel setuptools
REM Install torch from the CUDA 12.8 index. cu128 wheels include kernels for
REM Pascal (sm_50) through Blackwell (sm_120), so this works for every NVIDIA
REM GPU from a 1060 to a 5090. cu121 (the previous default) does NOT cover
REM Blackwell — RTX 5070 Ti / 5080 / 5090 owners get sm_120-incompatible
REM warnings and silent CPU fallback.
"%PY%" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
"%PY%" -m pip install -r "%AT_DIR%\requirements.txt"
if errorlevel 1 goto :fail

REM Step 3b: ai-toolkit's requirements.txt pins torch==2.5.1 + torchao==0.10.0,
REM which will have stomped our cu128 install above. Re-upgrade torch from
REM cu128 after ai-toolkit's pins land, then bump torchao + peft to versions
REM compatible with the newer torch (torchao>=0.16 stops peft's hard-raise on
REM LoRA dispatch — see scripts/generate.py for the historical workaround).
echo.
echo [3/4] Upgrading torch + torchao for Blackwell / newer-GPU compatibility...
"%PY%" -m pip install --upgrade torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
"%PY%" -m pip install --upgrade torchao peft
if errorlevel 1 goto :fail

REM Step 4: install our pipeline's extras (compel for prompt weighting)
echo.
echo [4/4] Installing main pipeline extras...
"%PY%" -m pip install -r "%ROOT%requirements.txt"
if errorlevel 1 goto :fail

REM Smoke test: confirm torch sees the GPU and the device's compute capability
REM is in the kernel set. If this prints "CUDA OK" we're good; if it warns
REM about sm_NNN incompatibility the user has an even newer GPU and the cu128
REM wheel needs a bump. Failure here is non-fatal — install completed, the
REM user can still run on CPU or fix it manually.
echo.
echo Verifying CUDA setup...
"%PY%" -c "import torch, warnings; warnings.filterwarnings('error', category=UserWarning); import sys; ok = torch.cuda.is_available(); name = torch.cuda.get_device_name(0) if ok else 'no GPU'; cap = torch.cuda.get_device_capability(0) if ok else None; print(f'CUDA OK: {name} (sm_{cap[0]}{cap[1]})' if ok else 'WARNING: CUDA not available — torch will run on CPU only')" 2>&1
if errorlevel 1 (
    echo.
    echo WARNING: CUDA verification raised a warning. Your GPU may be too new
    echo          even for the cu128 wheel. Install proceeded; if generation
    echo          falls back to CPU, ask Claude or check docs/troubleshooting.md.
)

echo.
echo ============================================================
echo  Setup complete.
echo.
echo  Next steps:
echo   1. Download the base SDXL checkpoint into checkpoints\
echo      (run download_models.bat for an automated download, or see
echo       docs/install.md for the manual link)
echo   2. Drop any character LoRAs you've been sent into
echo      loras\^<name^>\^<name^>.safetensors
echo   3. Double-click launch_website.bat
echo   4. Open http://localhost:8765 in your browser
echo ============================================================
echo.
echo Press any key to close this window.
pause >nul
endlocal
exit /b 0

:fail
echo.
echo ============================================================
echo  Setup FAILED. See the error above.
echo  Common fixes:
echo   - Make sure Python 3.10 or 3.11 is on PATH
echo   - Make sure you have a CUDA-capable GPU and recent drivers
echo   - Check internet connection (pip needs to download ~5 GB)
echo ============================================================
echo.
echo Press any key to close this window.
pause >nul
endlocal
exit /b 1
