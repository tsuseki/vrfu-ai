# Installation

Windows-only setup. Roughly 30 minutes of clock time, mostly waiting for downloads.

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
