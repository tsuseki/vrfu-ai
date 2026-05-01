# Troubleshooting

Common runtime issues and how to fix them. For installation problems, see [install.md](install.md). For prompting issues (LoRA not firing, off-shoulder leaks, etc.), see [prompting.md](prompting.md).

---

## Generation produces "two girls" or split scenes

The model is over-attending to identity/feature tags rather than the `1girl` anchor. Fix:

1. Make sure every queue prompt **starts** with `1girl, solo` (the website's Add Prompt modal does this; manually-edited queue.yaml might miss it)
2. Add `2girls, multiple girls, multiple views` to the negative prompt — the website's modal includes this by default
3. Check `character_tags` in `config.yaml` — if it lists features that read like multiple characters (`black hair, white hair, blue hair`), consolidate (`black hair with white and blue streaks`)

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
3. **Set a permanent override** in `characters/<name>/config.yaml` if you always want a specific scale:
   ```yaml
   upscale_scale: 1.5
   ```
   The website picker still wins per-run; this is just the default.
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
