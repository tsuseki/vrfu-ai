# Troubleshooting

Common runtime issues and how to fix them. For installation problems, see [install.md](install.md). For prompting issues (LoRA not firing, off-shoulder leaks, etc.), see [prompting.md](prompting.md).

---

## Generation produces "two girls" or split scenes

The model is over-attending to identity/feature tags rather than the `1girl` anchor. Fix:

1. Make sure every queue prompt **starts** with `1girl, solo` (the website's Add Prompt modal does this; entries you build by hand via the API might miss it)
2. Add `2girls, multiple girls, multiple views` to the negative prompt — the website's modal includes this by default
3. Check the character's `character_tags` (Characters page / `GET /api/character-info`) — if it lists features that read like multiple characters (`black hair, white hair, blue hair`), consolidate (`black hair with white and blue streaks`)

---

## LoRA fires but outfit/scene tags are ignored

The classic symptom: every output looks like a generic upper-body portrait of the character regardless of what scene/outfit you prompt.

Cause: **prompt truncated at 77 tokens** during text-encoding. Compel `truncate_long_prompts=False` was added in `scripts/generate.py` to handle this — make sure the file has it. Without it, only your character_tags + first part of the prompt reach the model.

Verify:
```cmd
findstr "truncate_long_prompts" scripts\generate.py
```
Should show `truncate_long_prompts=False`.

---

## Training "succeeds" in 90 seconds without actually training

ai-toolkit silently skips training if it finds an existing `optimizer.pt` at or past the target step count. It just regenerates samples and exits.

`scripts/train.py` now auto-detects this:
- **Pre-flight**: if `loras/<name>/` already has `optimizer.pt` + the `.safetensors`, it auto-archives the old folder before training so the new run starts clean
- **Post-flight**: warns if the run finishes much faster than expected (< 0.5 s/step floor)

If you see the loud `WARNING: training completed in 88 seconds` box, that's this scenario — manually verify the LoRA was actually retrained by checking the `optimizer.pt` mtime.

---

## Auto-start gen toggle ignored after training

The toggle stores intent in an in-memory dict on the server. If you restarted the website server between toggling and clicking Train, the flag was lost.

Fixed: the toggle's state is now captured **at click time** and sent with the start request, so server restarts can't lose it. Verify the latest `web/server.py` has this in the `/api/training/start` handler:
```python
if body.get("chain_to_gen"):
    _chain_after_training[character] = True
```

---

## Out of VRAM during upscale (or generation)

The upscaler auto-picks 2× scale on ≥18 GB GPUs, 1.5× on lower-tier. The website also exposes a **scale picker** next to both "Upscale liked" buttons — type any value 1.0–3.0 and it sticks (saved to localStorage).

If you still OOM (typically as a slow run rather than a crash):

1. **Drop the scale.** Try 1.4 or 1.25 in the picker. SDXL hires-fix at 2× peaks ~14 GB; 1.5× peaks ~10 GB; 1.25× peaks ~8 GB.
2. **Close GPU-hungry apps.** Discord/Vesktop, browser hardware acceleration, VRChat, games. Check Task Manager → Performance → GPU. Dedicated GPU memory should drop below 2 GB before you start a run.
3. **Set a permanent override** if you always want a specific scale: add `upscale_scale: 1.5` to `characters/<name>/config.yaml`, then run `scripts\migrate_to_db.py` to load it into the DB (the Characters page doesn't expose this field). The website picker still wins per-run; this is just the default.
4. Skip upscaling for very large source images (anything wider than 1216 already takes 2.4 GB just for the latent at 2×).

---

## Generation slow as molasses (75 s/it instead of ~1.5 s/it)

VRAM is overflowing into Windows "shared GPU memory" — system RAM that the GPU driver borrows when dedicated VRAM is full. Every operation now round-trips across PCIe and is ~50× slower.

How to confirm: open Task Manager → Performance → GPU. If "Shared GPU memory" is non-zero during a run, you're in this state.

Fix: same as the OOM section above — close apps so dedicated VRAM has headroom, or reduce upscale scale. The pipeline only uses VAE memory tricks (free) by default; we don't auto-offload because that fights with Compel.

---

## "WinError 1314: A required privilege is not held" during first generation

HuggingFace caches model metadata using filesystem symlinks. Windows requires a privilege (or **Developer Mode**) to create them. Without it, the first cache write fails.

One-time fix:
1. Press Win → type "Developer settings" → Open
2. Toggle "Developer Mode" → On
3. Click Yes on the UAC prompt
4. Wait ~10 s for the toggle to settle
5. Restart the website

Developer Mode is a per-user toggle — no admin needed afterwards, no reboot, doesn't open up anything dangerous. It just lets the user create symlinks.

---

## "Skipping and continuing..." spam — every image errors

The full error mentioned `Expected all tensors to be on the same device, cuda:0 and cpu`. This was a race between `enable_model_cpu_offload` (which moves text encoders to CPU between calls) and CompelForSDXL (which feeds them CPU-side token tensors that never get moved to GPU).

Fixed in commit 0fdef21 — pipeline no longer uses `enable_model_cpu_offload`. If you see this on your machine, run `git pull` to pick up the fix.

---

## launch_website.bat as administrator → blackscreen, then nothing

Running the launcher as administrator changes the working directory to `C:\Windows\System32`, which breaks the relative paths it uses to find Python and `server.py`. The cmd window can also close before `pause` runs.

You don't need admin for anything in this project — the venv, GPU, output folders, and 127.0.0.1:8765 are all unprivileged. **Always double-click `launch_website.bat` normally**, never right-click → Run as administrator. If Windows ever shows a UAC prompt for it, click No.

---

## huggingface-hub 1.x ImportError on transformers

If startup crashes with `ImportError: huggingface-hub>=0.34.0,<1.0 is required`, your venv has the recently-released huggingface-hub 1.x but `transformers` 4.57.x refuses it.

Fix in-place without rerunning setup:
```cmd
cd C:\vrfu-ai
ai-toolkit\venv\Scripts\python.exe -m pip install "huggingface-hub>=0.34.0,<1.0"
```

The repo's `requirements.txt` and `download_models.bat` already pin this; you only hit it if pip's resolver bumped the package via some other path (e.g. `pip install transformers -U`).

---

## download_models.bat fails with 401 Unauthorized

The HuggingFace mirror used by the script is intermittently gated. Fall back to manual download:

- **civitai.red mirror (no login)**: <https://civitai.red/models/827184/wai-illustrious-sdxl> — easiest path
- Civitai original: <https://civitai.com/models/827184/wai-illustrious-sdxl> (requires Civitai account)

Save the `.safetensors` file to `checkpoints/waiIllustriousSDXL_v170.safetensors` and skip the script.

---

## Generated image looks 3D / VRChat-ish

Your character LoRA was trained on 3D source data (VRChat captures or similar). The LoRA learned the 3D look as part of the identity.

Fix at generation time:
1. Add `2d, anime coloring, flat color, cel shading` to your prompt's positive tags
2. Add `3d, 3dcg, vrchat, mmd, blender, render, photorealistic` to the negative
3. The project's `BASE_NEGATIVE` already includes (3) by default

Long-term fix: re-caption training data with `3d` tag explicitly, retrain. Then the LoRA learns to treat 3D as a separable medium, and prompting `2d` at gen time can override it.

---

## Training crashes immediately with `UnicodeEncodeError` (cp932)

ai-toolkit emits tqdm progress bars containing `█` (U+2588). On Japanese Windows installs (or any console where `sys.stdout.encoding` is cp932), this character kills the wrapper before any training step runs.

Fixed in `scripts/train.py`:
1. `sys.stdout`/`sys.stderr` reconfigured to UTF-8 with `errors="replace"` at startup
2. Per-line `print()` wrapped in `try/except UnicodeEncodeError` fallback

If it still recurs:
1. Set `PYTHONIOENCODING=utf-8` in the environment before running setup
2. Run `chcp 65001` in the parent cmd window first

---

## Tag suggestions ("Popular" chips) are empty

The Popular chips show top tags from your **liked** images — images you voted on with ❤️/👍 and then ran 📦 Organize on. Until you have at least a few liked images, the chips show "no liked images yet".

To bootstrap:
1. Generate some images (▶️ Start)
2. Vote ❤️ or 👍 on the ones you like
3. Click 📦 Organize (moves liked → liked/, rest → archive/)
4. Open the Add Prompt modal — Popular chips now populated

The chips also refresh every time you click Organize.

---

## SDXL inference still slow on 16 GB Blackwell after the cuDNN-SDP patch

Symptom: with the cuDNN-SDP fix applied, `nvidia-smi dmon` confirms real compute (~150 W during denoising), the log prints "Blackwell (sm_120) detected — cuDNN SDP enabled.", and yet step times sit at 11–32 s/it instead of the expected 1–2 s/it.

Cause: VRAM peaks around 15.85 GB / 16 GB during inference (UNet ~5 GB + activations ~7–8 GB + text encoders ~1.8 GB + VAE ~0.3 GB). On Windows, NVIDIA's driver silently swaps GPU memory to system RAM over PCIe when you cross the threshold — a 40–100× slowdown that shows as a sustained slow step time. The cuDNN-SDP patch fixes compute; this fix addresses VRAM headroom.

Fixed in `scripts/generate.py` and `scripts/upscale.py` — on detected Blackwell with <20 GB VRAM, the text encoders cycle CPU↔GPU per image: brought to GPU briefly for Compel encoding (~0.1 s), pushed back to CPU before UNet runs. Frees ~1.8 GB during the heavy denoising/VAE phases, keeping peak VRAM under the sysmem-fallback ceiling.

If you have a 16 GB Blackwell card and still see slow inference after `git pull`:

1. Confirm the offload is active — log should print `16 GB Blackwell: text-encoder CPU offload enabled (_execution_device pinned to cuda).`
2. If you see `Cannot generate a cpu tensor from a generator of type cuda` at generation start, the `_execution_device` override didn't take — diffusers version mismatch. Try `pip install --upgrade diffusers`.
3. If sysmem fallback persists, watch VRAM during inference (`nvidia-smi -l 1`). If it still climbs above 15.5 GB, drop to 832×1216 (or 1216×832) instead of 1024² — slightly less peak.

---

## SDXL inference takes 4–8 minutes per image on RTX 50-series (Blackwell)

Symptom: 28-step generation at 1024×1024 takes 4–8 min instead of the ~30–60s expected on a Blackwell card. Step 1 reads ~4–8s/it, step 2 onwards spikes to 18–28s/it. Inconsistent between runs.

Cause: PyTorch's default scaled-dot-product attention (SDP) backend on sm_120 in the 2.11 stable line is broken — flash-SDP produces sustained slow dispatches on Blackwell. The fix is routing through cuDNN-backed SDP (`enable_cudnn_sdp(True)`), which uses cuDNN 9.x's Blackwell-native flash kernel.

Fixed in `scripts/generate.py` and `scripts/upscale.py` — both detect sm_120+ at startup and force the cuDNN SDP path, plus enable TF32 matmul and re-apply `AttnProcessor2_0` after every peft LoRA load (peft swaps it for its own slow processor).

If you're seeing this on a customised generate.py:

```python
# Before `import torch`:
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "max_split_size_mb:1024")

# After pipe.to("cuda") and after every load_lora_weights():
torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True
if torch.cuda.get_device_capability(0) >= (12, 0):
    torch.backends.cuda.enable_cudnn_sdp(True)
    torch.backends.cuda.enable_flash_sdp(False)
    torch.backends.cuda.enable_math_sdp(False)
    torch.backends.cuda.enable_mem_efficient_sdp(True)
    torch.backends.cudnn.benchmark = False
from diffusers.models.attention_processor import AttnProcessor2_0
pipe.unet.set_attn_processor(AttnProcessor2_0())
```

If step times are still inconsistent (some 1.7s, some 18s) after the patch, check NVIDIA Control Panel → Manage 3D settings → "Power management mode" → set to "Prefer maximum performance". Blackwell's adaptive clock can drop to a low P-state between async work, causing the next call to come up cold.

---

## `ModuleNotFoundError: No module named 'torchaudio'` during training

Symptom: `train.py` (or any ai-toolkit job) fails to load with `ModuleNotFoundError: No module named 'torchaudio'`.

Cause: ai-toolkit's `config_modules.py` imports `torchaudio` at the top level. Older versions of `setup.bat` only installed `torch` + `torchvision`, missing `torchaudio`. If you re-installed torch via cu128 manually without `torchaudio`, you'll hit this.

Fix:

```cmd
ai-toolkit\venv\Scripts\python.exe -m pip install torchaudio --index-url https://download.pytorch.org/whl/cu128
```

Current `setup.bat` includes `torchaudio` in both pip-install steps, so a fresh `setup.bat` run won't hit this.

---

## `HFValidationError: Repo id must use alphanumeric chars, '-', '_' or '.'` during training

Symptom: `train.py` errors with a long Windows path being mistaken for a HuggingFace repo ID:

```
HFValidationError: Repo id must use alphanumeric chars, '-', '_' or '.'.
The name cannot start or end with '-' or '.':
'C:\Users\you\vrfu-ai\.claude\worktrees\...\checkpoints\waiIllustriousSDXL_v170.safetensors'
```

Cause: you ran the script from inside a Claude Code worktree (`.claude/worktrees/<name>/`). The naive `Path(__file__).parent.parent` resolves to the worktree, but the worktree only contains git-tracked files — `checkpoints/`, `loras/`, and your personal `characters/<name>/` are gitignored heavy assets that only exist in the main repo. diffusers tried to load the checkpoint from the worktree path, didn't find it, and fell back to interpreting the absolute Windows path as a HuggingFace repo ID, which fails validation.

This is fixed in `scripts/_common.py` — `ROOT` now detects the `.claude/worktrees/<name>/` pattern and resolves to the real project root automatically. If you're seeing this on an older checkout, pull the latest.

Workaround if you can't pull yet: invoke the script with the main-repo path explicitly, not the worktree path:

```cmd
:: GOOD
C:\Users\you\vrfu-ai\ai-toolkit\venv\Scripts\python.exe C:\Users\you\vrfu-ai\scripts\train.py --character mari

:: BAD (worktree path)
C:\Users\you\vrfu-ai\.claude\worktrees\foo\ai-toolkit\venv\Scripts\python.exe C:\Users\you\vrfu-ai\.claude\worktrees\foo\scripts\train.py --character mari
```

The web UI's `spawn_tool()` already runs scripts from the main repo, so this only bites when running training/generation manually from inside a worktree.

---

## "NVIDIA GeForce RTX 50xx with CUDA capability sm_120 is not compatible…"

Symptom: `import torch` reports `True` for `cuda.is_available()` but you see a
warning like *"NVIDIA GeForce RTX 5070 Ti with CUDA capability sm_120 is not
compatible with the current PyTorch installation. The current PyTorch
install supports CUDA capabilities sm_50 sm_60 … sm_90"*. Generation
either crashes or silently falls back to CPU (~50× slower).

Cause: the GPU is **Blackwell** (RTX 50-series). Old PyTorch wheels built
against CUDA 12.1 don't ship Blackwell kernels. Current `setup.bat`
installs against CUDA 12.8 by default, but if you set the project up
before that change you'll be on a cu121 build.

Fix:

```cmd
ai-toolkit\venv\Scripts\python.exe -m pip install --upgrade torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
ai-toolkit\venv\Scripts\python.exe -m pip install --upgrade torchao peft
```

Verify:

```cmd
ai-toolkit\venv\Scripts\python.exe -c "import torch; x=torch.tensor([1.0]).cuda(); print(x*2)"
```

Should print `tensor([2.], device='cuda:0')` with **no** sm_NNN warning.

If you have a newer GPU than Blackwell, cu128 stable may not be enough —
try the PyTorch nightly index instead:
`https://download.pytorch.org/whl/nightly/cu128`.

---

## Website shows blank / "(no output yet)" but training is running

You restarted the website server while training was in progress. The training subprocess survives (it was spawned with `CREATE_NEW_PROCESS_GROUP`) but the new server process has no record of it, so the UI shows "Idle".

Wait for training to complete. The .safetensors will land at `loras/<name>/<name>.safetensors` regardless. Auto-start gen won't fire for that run since the chain flag is in the old (now-dead) server's memory — start it manually.


---

## Prompts don't seem to do anything

If outputs are completely unrelated to your prompt (random scenes, wrong character, generic anime girl), check:

1. **Did `setup.bat` complete successfully?** Re-run it; it's idempotent.
2. **Is the right LoRA loaded?** Look at the run log (`characters/<name>/logs/run_*.txt`). The first ~10 lines list the loaded LoRA path and weight. Verify that's the file you expect.
3. **Is `character_tags` correct?** A wrong/empty `character_tags` means the LoRA's identity is mis-prompted on every gen.
4. **Is the trigger word right?** It must match the trigger your friend used during training. Ask them.
