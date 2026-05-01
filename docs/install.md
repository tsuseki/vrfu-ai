# Installation

Windows-only setup. Roughly 30 minutes of clock time, mostly waiting for downloads.

If you've installed Python and Git before and know how to open a `cmd` window, skip to **section 1**. Otherwise read **section 0** first.

---

## 0. Absolute-beginner setup

This section walks through installing Python, installing Git, what "PATH" means, and how to open a `cmd` window. If any of those are unfamiliar, do this section step by step. You only do it once on this machine.

### 0a. Install Python

1. Open <https://www.python.org/downloads/> in your browser.
2. Click the big yellow "Download Python 3.x.x" button. (The exact version doesn't matter as long as it's 3.10, 3.11, or 3.12. **Don't** install 3.13 yet — some packages aren't ready for it.)
3. Open the downloaded `.exe` file from your Downloads folder.
4. **Critical step**: at the *very first* installer screen, **tick the box that says "Add python.exe to PATH"** at the bottom. If you skip this, nothing later will work and you'll have to uninstall and redo it.
5. Click "Install Now" and wait for it to finish. Click "Close".

#### Verifying Python installed correctly

Open a `cmd` window (see **0d** below if you're not sure how) and type:

```cmd
python --version
```

You should see something like `Python 3.11.7`. If you see `'python' is not recognized as an internal or external command`, the "Add to PATH" tick didn't take — uninstall Python from Windows Settings → Apps, then redo step 4 above being sure to tick the box.

### 0b. Install Git

1. Open <https://git-scm.com/downloads/> in your browser.
2. Click "Windows" → "64-bit Git for Windows Setup".
3. Run the downloaded installer. **Just click Next on every screen** — the defaults are fine. Don't try to customize anything.

#### Verifying Git installed correctly

Open a *fresh* `cmd` window (existing ones won't see Git yet) and type:

```cmd
git --version
```

You should see something like `git version 2.45.0.windows.1`. If you see `'git' is not recognized`, restart Windows so the PATH update takes effect, then try again.

### 0c. What is PATH and why does it matter?

When you type a command like `python` or `git` in cmd, Windows looks for that program in a list of folders called the **PATH**. If the program's folder isn't on the PATH, Windows says "not recognized" even though the program is installed.

Both installers above can add themselves to PATH automatically (Python via the tick box, Git's installer does it by default). If you skipped that, you'd have to type the full path every time, like `C:\Users\you\AppData\Local\Programs\Python\Python311\python.exe`. Don't do that — re-run the installer with the box ticked.

You don't need to edit PATH manually for this project. If something says "not on PATH", the fix is always "re-run the installer with PATH option enabled".

### 0d. Opening a cmd (Command Prompt) window

`cmd` (also called Command Prompt or terminal) is a black window where you type text commands. There are several ways to open one:

- **Win + R** → type `cmd` → Enter (this is the fastest)
- Press the Win key → type `cmd` → click "Command Prompt"
- Right-click the Start button (Win + X) → choose "Terminal" or "Command Prompt"

#### Changing folders inside cmd

When cmd opens, it usually starts in `C:\Users\<your-name>`. To move to a different folder, type:

```cmd
cd C:\vrfu-ai
```

Replace `C:\vrfu-ai` with the actual folder path. After running this, every command you type runs *as if* you were in that folder.

The `cd /d` variant changes drives too: `cd /d D:\projects\vrfu-ai`.

#### Tips

- You can paste into cmd by right-clicking, or with Ctrl+V on Windows 10+.
- Up arrow recalls your previous command.
- The `cd` (no arguments) prints the folder you're currently in.
- **Don't run cmd as administrator** for this project. You don't need to, and it changes the working directory in surprising ways. Just use a normal cmd window.

### 0e. Verifying you're ready

Open a fresh `cmd` window and run, one at a time:

```cmd
python --version
git --version
nvidia-smi
```

If all three print version info (and `nvidia-smi` shows your GPU), you're ready for section 1.

If any of them errors:
- `python` not recognized → redo **0a**
- `git` not recognized → redo **0b**, restart Windows
- `nvidia-smi` not recognized → install/update your NVIDIA drivers from <https://www.nvidia.com/Download/index.aspx>

---

## 1. Prerequisites

- **Python 3.10 or 3.11** — install from [python.org](https://www.python.org/downloads/) and tick "Add to PATH"
- **Git** — install from [git-scm.com](https://git-scm.com/downloads/) (only needed if you're cloning from GitHub; not required if you got the project as a ZIP)
- **NVIDIA GPU** with recent drivers (CUDA 12.x compatible)

To verify Python is on PATH:
```cmd
python --version
```
Should print `Python 3.10.x` or `3.11.x`. If `'python' is not recognized`, reinstall Python and check the "Add to PATH" box.

## 2. Clone the repo (with `--recursive`)

```cmd
git clone --recursive https://github.com/tsuseki/vrfu-ai.git C:\vrfu-ai
cd C:\vrfu-ai
```

The `--recursive` flag pulls the bundled **ai-toolkit** training framework as a git submodule. If you forgot it, `setup.bat` will run `git submodule update --init` for you on first run — no manual fixup needed.

The repo works wherever you put it (no env vars, no config edits) — paths are computed relative to where the project lives.

## 3. Run setup.bat

Double-click `setup.bat` (or run it from a `cmd` window inside the repo).

This does:
1. Verifies Python is on PATH
2. Creates a venv at `ai-toolkit/venv/`
3. Installs PyTorch with CUDA 12.1 support
4. Installs ai-toolkit's dependencies (`ai-toolkit/requirements.txt`)
5. Installs main pipeline extras (`requirements.txt` — Compel, PyYAML, Pillow)

Total: ~5 GB of downloads, ~10–15 minutes on a typical connection.

If something fails, see the **Troubleshooting** section at the bottom.

## 4. Download the base SDXL checkpoint

The project uses **waiIllustriousSDXL v1.7.0** (~7 GB) as the base model. You have two options.

### Option A — automated (`download_models.bat`)

```cmd
download_models.bat
```

Pulls from a HuggingFace mirror. Takes 10–30 minutes depending on connection. **May fail with 401 Unauthorized** — the upstream mirror is intermittently gated. If so, fall back to Option B.

### Option B — manual

Download from one of these sources and put the resulting `.safetensors` file at `checkpoints/waiIllustriousSDXL_v170.safetensors`:

- **civitai.red mirror (no login)**: <https://civitai.red/models/827184/wai-illustrious-sdxl> — easiest path
- Civitai original: <https://civitai.com/models/827184/wai-illustrious-sdxl> (requires Civitai account)
- HuggingFace: <https://huggingface.co/John6666/wai-illustrious-sdxl-v170-sdxl> (often gated; needs HF login + accept-terms)

After downloading, the file structure should look like:
```
checkpoints/
└── waiIllustriousSDXL_v170.safetensors    (~7 GB)
```

## 5. Add character LoRAs

The base SDXL model knows what an "anime girl with red hair" looks like generically. To generate consistent characters, you need a **character LoRA** — a fine-tuned adapter trained on reference images of one specific character.

### Using a LoRA your friend sent you

Drop the `.safetensors` file at:
```
loras/<character_name>/<character_name>.safetensors
```

E.g. `loras/tsu_chocola/tsu_chocola.safetensors`.

The repo ships with a placeholder slot for `demo_character`. To use a friend's LoRA there:
1. Rename the file to `demo_character.safetensors`
2. Drop it at `loras/demo_character/demo_character.safetensors`
3. Edit `characters/demo_character/config.yaml`:
   - `trigger_word`: the trigger word your friend used (ask them)
   - `character_tags`: the canonical visual identity (e.g. `1girl, solo, fox girl, black hair, red eyes`)
4. Click ▶️ Start in the Generation page

For a LoRA you'll set up under its own slot (rather than overwriting demo), see [add-character.md](add-character.md).

### Training your own LoRA

See [add-character.md](add-character.md) for the full workflow: gathering 30–50 reference images → captioning → training (~55 min on a 3090).

## 6. Optional: upscaler model

The hires-fix upscaler uses the same SDXL base + your character LoRA — **no extra models needed**. The `upscalers/` folder exists for future use (e.g. ESRGAN), it's empty by default.

## 7. Launch the website

```cmd
launch_website.bat
```

Opens <http://localhost:8765> in your default browser. Server is localhost-only — nothing exposed to your network.

## Troubleshooting

### `python` is not recognized

Python isn't on PATH. Reinstall from python.org with "Add to PATH" ticked, or manually add `C:\Python311` (or wherever it installed) to your PATH environment variable.

### `setup.bat` fails on PyTorch install

Most common: CUDA version mismatch. The script installs `torch` from `https://download.pytorch.org/whl/cu121` (CUDA 12.1). If you have CUDA 11.x drivers, edit setup.bat and replace `cu121` with `cu118`.

To check your CUDA version:
```cmd
nvidia-smi
```
Look at "CUDA Version" in the top-right.

### `setup.bat` fails on a specific package

Some ai-toolkit deps occasionally fail to wheel-install on Windows. If you see something like `error: Microsoft Visual C++ 14.0 or greater is required`, install the **Build Tools for Visual Studio**: <https://visualstudio.microsoft.com/visual-cpp-build-tools/> (just the C++ build tools, not the full IDE).

### `download_models.bat` 401/403

The HuggingFace mirror used by the script is public, but rare auth glitches happen. Falling back to manual download (Option B above) always works.

### Out of VRAM during generation

The default settings target 12+ GB. If you OOM on a 12 GB card:
- Edit `scripts/generate.py` and lower `DEFAULT_GUIDANCE` to 5.0 (slightly less work per step)
- Avoid stacking multiple LoRAs (`extra_loras` in `config.yaml` should stay `[]`)
- Close other GPU-using apps (browsers with WebGL pages, games, etc.)

### Out of VRAM during upscaling

The upscaler auto-detects your VRAM and picks 2× scale for ≥18 GB or 1.5× for less. If you still OOM:
- Edit `characters/<name>/config.yaml` and add `upscale_scale: 1.25` (the auto-detection only knows two tiers)
- Or skip upscaling for very large source images

### Out of VRAM during training

ai-toolkit defaults are tuned for 12 GB+ with gradient checkpointing on. If you OOM:
- Lower `linear: 32` to `linear: 16` in `characters/<name>/training_config.yaml`
- Lower `resolution: [ 512, 768, 1024 ]` to `resolution: [ 512, 768 ]`
- Don't train at the same time as a generation run (the wrapper blocks this anyway)

### Anything else

See [troubleshooting.md](troubleshooting.md) for runtime issues. Installation issues that aren't covered here: open an issue on GitHub.
