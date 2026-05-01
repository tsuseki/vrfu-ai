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
echo [2/3] Installing ai-toolkit dependencies (this can take ~10 min)...
"%PY%" -m pip install --upgrade pip wheel setuptools
"%PY%" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
"%PY%" -m pip install -r "%AT_DIR%\requirements.txt"
if errorlevel 1 goto :fail

REM Step 4: install our pipeline's extras (compel for prompt weighting)
echo.
echo [3/3] Installing main pipeline extras...
"%PY%" -m pip install -r "%ROOT%requirements.txt"
if errorlevel 1 goto :fail

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
