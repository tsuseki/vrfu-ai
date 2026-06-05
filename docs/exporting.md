# Exporting & sharing characters

How to bundle a character (LoRA + configs) so a friend can drop the
result into their own clone of this repo and start generating.

This is the symmetric companion of [`add-character.md`](add-character.md).
That doc walks through *making* a character; this one walks through
*shipping* one.

## TL;DR

```cmd
ai-toolkit\venv\Scripts\python.exe scripts\export_character.py --character mari
```

→ produces `mari_bundle.zip` in the repo root. Send that zip. The receiver
unzips it into the root of their `vrfu-ai/` clone and the files merge into
the right places automatically.

---

## What goes in the bundle

```
mari_bundle.zip
├── README.md                                      ← auto-generated install guide
├── characters/mari/config.yaml                    ← project-side character config
├── characters/mari/training_config.yaml           ← ai-toolkit training config (for retraining)
├── loras/mari/mari.safetensors                    ← the trained LoRA
├── loras/mari/checkpoints/mari_*.safetensors      ← intermediate training steps (optional)
└── characters/mari/training/                      ← only with --include-training
```

**Default contents (without flags):** project config + training config +
final LoRA + intermediate step checkpoints. Typical size: ~1 GiB.

**`--include-training`:** also bundles the `training/` PNG + `.txt`
caption pairs. Off by default because (a) they're often NSFW, (b) they
add several GB, (c) the receiver doesn't usually need them — the LoRA
is already trained.

**`--no-checkpoints`:** skip the `loras/<name>/checkpoints/` step
checkpoints. Cuts size by ~75%; receiver only gets the final 2000-step
build. Use when bundling for someone who just wants to generate, not
A/B against earlier training steps.

## What's NOT in the bundle (deliberately)

- **`optimizer.pt`** — training state, half a gig, only useful if the
  receiver wants to *resume* training (rare).
- **`liked/`, `archive/`, `output/`, `logs/`** — your generation history
  is private and not portable.
- **The base SDXL checkpoint** — too big (~7 GB). Receiver downloads
  separately via `download_models.bat`.
- **Hardcoded paths from the training config** — the script rewrites
  paths to be repo-relative so the bundle works regardless of where
  you (or the receiver) cloned to.

## Receiver-side flow

When someone sends you a `<name>_bundle.zip`:

1. Make sure your `vrfu-ai/` is set up — `setup.bat` ran, base SDXL
   checkpoint downloaded, website launches.
2. **Recommended — use the Import button.** In the website, go to the
   **Characters** tab and click **📥 Import bundle…**, then pick the `.zip`.
   The server unpacks it into `characters/` + `loras/` **and seeds the config
   into the DB**, so the character is live the moment it finishes — no extra
   step.
3. **Manual fallback** (e.g. you haven't launched the website yet): unzip the
   bundle into the **root of your `vrfu-ai/` clone** ("Extract here"), then
   load the config into the DB yourself —
   `ai-toolkit\venv\Scripts\python.exe scripts\migrate_to_db.py` (idempotent;
   imports every `characters/*/config.yaml`). Restart the website if it was
   already running. The manual path needs this because it bypasses the
   server's importer.
4. Open the **Characters** tab and click the new character. Verify
   `character_tags`, `trigger_word`, `outfits.default` are filled in. If the
   sender left `character_tags` minimal, fill them in from the bundle's
   `README.md` and the training images (if included) — the Characters page
   saves straight to the DB.
5. Click **▶️ Start** on the Generation tab to verify everything works.

## Working with an agent

If you (sender) want the agent to do the export end-to-end:

> *"Export the mari character as a bundle to send to a friend."*

The agent runs `scripts/export_character.py --character mari` and points
you at the resulting zip.

If you (receiver) want the agent to import a bundle for you:

> *"I just got `mari_bundle.zip` from a friend at `~/Downloads/`.
> Set it up in this repo."*

The agent unzips, places files, runs `migrate_to_db.py` to load the
config into the DB, opens the website to the Characters tab, and walks
you through filling in any missing `character_tags`.

## Troubleshooting

**"No config.yaml for character"** after unzipping — the archive landed
in the wrong place. The folders inside the zip start with `characters/`
and `loras/` — those need to merge with the same folders in your repo
root. If your tool nested them inside another folder (e.g.
`mari_bundle/characters/...`), move them up one level.

**LoRA loads but character looks generic / not anchored to the trained
look** — `character_tags` is too thin. Either the sender shipped the
defaults from `_template/` (just `1girl, solo`), or your local tags
got reset. Edit through the Characters tab to add hair / eyes /
distinguishing features.

**Generation works but every output is the same composition** — the
sender's `outfits.default` is probably the only outfit specified.
Either add more named outfits, or write outfit tags inline in queue
prompts (the latter is what the close-up rule needs anyway — see
[`queue.md`](queue.md)).

**Receiver runs Windows + RTX 50-series and gen is slow** — separate
issue, see [`troubleshooting.md`](troubleshooting.md) for the Blackwell
SDP + text-encoder offload patches.
