"""
Export a character (LoRA + configs) as a single .zip a friend can drop into
their own clone of this repo.

Usage:
    python scripts/export_character.py --character mari
    python scripts/export_character.py --character mari --out F:/some/where/mari.zip
    python scripts/export_character.py --character mari --include-training

What goes in the bundle:

    mari_bundle.zip
    ├── README.md                                       (auto-generated install guide)
    ├── characters/mari/config.yaml                     (project-side character config)
    ├── characters/mari/training_config.yaml            (ai-toolkit training config)
    ├── loras/mari/mari.safetensors                     (the trained LoRA)
    ├── loras/mari/checkpoints/mari_*.safetensors       (optional intermediate steps)
    └── characters/mari/training/                       (only with --include-training)

What's NOT included:
    - optimizer.pt (training state, not useful for inference, ~half a GB)
    - liked/, archive/, output/, logs/ (per-user generation history)
    - the base SDXL checkpoint (too big; receiver downloads separately)

Receiver workflow:
    1. Clone vrfu-ai, run setup.bat, run download_models.bat
    2. Characters tab -> Import bundle... -> pick the .zip. The server unpacks
       it AND seeds the config into vrfu.db, so the character is live at once.
       (Manual unzip into the repo root also works, but then you must run
       scripts/migrate_to_db.py to seed the DB.)
    3. Open the character, set character_tags + outfits if not already filled
       in (the Characters page saves to the DB), then click Start to verify.

The bundle's config.yaml is generated from the sender's live DB config, and
all paths are written repo-relative, so it works regardless of where the
sender or receiver cloned the repo.
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C   # noqa: E402
import store          # noqa: E402


BUNDLE_README = """\
# {pretty} character bundle

This bundle is a {pretty} LoRA + configs for the **vrfu-ai** pipeline:
<https://github.com/tsuseki/vrfu-ai>

## If you don't have vrfu-ai yet

Clone the repo first (the `--recursive` flag pulls the ai-toolkit submodule):

```cmd
git clone --recursive https://github.com/tsuseki/vrfu-ai.git
cd vrfu-ai
setup.bat
download_models.bat
```

See <https://github.com/tsuseki/vrfu-ai/blob/main/docs/install.md> for the
full install walkthrough.

## Install the bundle (recommended: use the website)

1. **Open the website** — run `launch_website.bat` in your vrfu-ai folder.
2. **Go to the Characters tab.**
3. **Click 📥 Import bundle…** at the bottom of the character sidebar.
4. **Pick this `.zip`.** The server unpacks it into the right places
   (`characters/{name}/` + `loras/{name}/`) and validates the contents.
5. **Click {pretty}** in the sidebar. Verify `character_tags`,
   `outfits.default`, and any per-character notes look right. Edit
   through the form if needed and Save.
6. **Click ▶️ Start** on the Generation tab to verify generation works.

## Manual install (fallback)

If the import button isn't available (e.g. you're setting up before
launching the website for the first time), unzip the contents into the
**root of your `vrfu-ai` clone** (the folder with `launch_website.bat`).
Folders will merge with what's already there:

```
vrfu-ai/
├── characters/{name}/                         (this bundle)
│   ├── config.yaml
│   ├── training_config.yaml
│   └── training/                              (only if sender used --include-training)
└── loras/{name}/
    ├── {name}.safetensors                     (the LoRA)
    └── checkpoints/                           (intermediate training steps)
```

Then load the config into the state DB (the manual unzip drops files on
disk, but the app reads config from `vrfu.db`):

```cmd
ai-toolkit\venv\Scripts\python.exe scripts\migrate_to_db.py
```

Now open the website, go to the Characters tab, click {pretty}, verify
the config, and click ▶️ Start to test generation. (The 📥 Import button
above does this seeding for you — the manual path is the only one that
needs `migrate_to_db.py`.)

## Notes from the sender

- Trigger word: `{trigger}`
- LoRA file: `loras/{name}/{name}.safetensors` ({lora_size_mib} MiB)
- Trained against: {checkpoint}

## If something doesn't work

- **"No config.yaml for character"** — the unzip didn't land in the right
  place. Files must be at `characters/{name}/config.yaml`, not nested
  deeper or at the wrong root.
- **LoRA loads but character looks generic** — `character_tags` is too
  short. Edit it through the Characters tab to add identity anchors
  (hair, eyes, ears, distinguishing features).
- **Generation looks plasticky / 3D** — the LoRA may need an artist tag
  on every prompt. See the **Notes from the sender** section above for
  character-specific quirks.

See <https://github.com/tsuseki/vrfu-ai/blob/main/docs/troubleshooting.md>
for more.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Bundle a character + LoRA for sharing.")
    parser.add_argument("--character", required=True, help="Character name (folder under characters/).")
    parser.add_argument("--out", help="Output .zip path. Defaults to <character>_bundle.zip in repo root.")
    parser.add_argument("--include-training", action="store_true",
                        help="Include training/ images + captions. Off by default — they're large and may be NSFW.")
    parser.add_argument("--include-checkpoints", action="store_true", default=True,
                        help="Include loras/<name>/checkpoints/ (intermediate training steps). On by default.")
    parser.add_argument("--no-checkpoints", dest="include_checkpoints", action="store_false")
    args = parser.parse_args()

    name = args.character
    char_dir = C.char_dir(name)

    # The DB is the source of truth for config — the on-disk config.yaml can be
    # a stale scaffold seed (the UI saves edits to the DB, not the file). Pull
    # the live config and ship THAT in the bundle so the receiver gets the
    # sender's current tags / outfits / weights.
    db_cfg = store.character_config_get(name)
    if db_cfg is None:
        sys.exit(f"ERROR: no config for '{name}' in the state DB. Run "
                 f"scripts/migrate_to_db.py to seed it, or create the character "
                 f"through the website first.")
    config_yaml_text = yaml.safe_dump(db_cfg, sort_keys=False, allow_unicode=True)

    # Resolved view (absolute paths) for the README metadata + LoRA lookup.
    cfg = C.load_character(name)
    pretty = cfg.get("character_name") or name
    trigger = cfg.get("trigger_word") or name
    checkpoint = cfg.get("checkpoint") or "checkpoints/<base SDXL>.safetensors"

    lora_path = C.ROOT / cfg["character_lora"]
    if not lora_path.exists():
        sys.exit(f"ERROR: LoRA not found at {lora_path}")
    lora_size_mib = lora_path.stat().st_size // (1024 * 1024)

    # Default output path
    out_path = Path(args.out) if args.out else (C.ROOT / f"{name}_bundle.zip")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Collect files to include — (source absolute path, archive-relative path)
    files: list[tuple[Path, str]] = []

    # Project-side configs. config.yaml is generated from the DB (above) and
    # written straight into the zip in the writer block below, so the bundle
    # always carries the sender's current config rather than a stale file.
    tcfg = char_dir / "training_config.yaml"
    if tcfg.exists():
        files.append((tcfg,                          f"characters/{name}/training_config.yaml"))

    # Main LoRA + intermediate checkpoints
    files.append((lora_path,                         f"loras/{name}/{lora_path.name}"))
    if args.include_checkpoints:
        ckpt_dir = lora_path.parent / "checkpoints"
        if ckpt_dir.is_dir():
            for ck in sorted(ckpt_dir.glob("*.safetensors")):
                files.append((ck,                    f"loras/{name}/checkpoints/{ck.name}"))

    # Optional training set
    if args.include_training:
        train_dir = char_dir / "training"
        if train_dir.is_dir():
            for f in sorted(train_dir.iterdir()):
                if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".txt"):
                    files.append((f,                 f"characters/{name}/training/{f.name}"))

    # Auto-generated README inside the bundle
    bundle_readme = BUNDLE_README.format(
        pretty=pretty, name=name, trigger=trigger, checkpoint=checkpoint,
        lora_size_mib=lora_size_mib,
    )

    total_bytes = sum(p.stat().st_size for p, _ in files)
    print(f"Bundling {pretty} ({name})")
    print(f"  files: {len(files) + 1}  (config.yaml generated from the DB)")
    print(f"  size:  {total_bytes / (1024**3):.2f} GiB" if total_bytes > 1024**3
          else f"  size:  {total_bytes / (1024**2):.1f} MiB")
    print(f"  out:   {out_path}")

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_STORED) as z:
        # ZIP_STORED (no compression) — safetensors + PNG don't compress meaningfully
        # and STORED is dramatically faster for ~500MB-2GB bundles.
        for src, arc in files:
            z.write(src, arc)
        z.writestr(f"characters/{name}/config.yaml", config_yaml_text)
        z.writestr("README.md", bundle_readme)

    print(f"\nWrote {out_path} ({out_path.stat().st_size / (1024**2):.1f} MiB)")
    print(f"Send the .zip via Discord / email / cloud storage. The receiver "
          f"unzips it into their vrfu-ai/ root.")


if __name__ == "__main__":
    main()
