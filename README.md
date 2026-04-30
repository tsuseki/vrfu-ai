# vrfu-ai

Local pipeline for generating anime art of custom characters using SDXL + character LoRAs. Everything runs on your own machine — your GPU does the work, no cloud, no API keys, no rate limits. A web UI bundles generation, voting, organizing, upscaling, and on-rig LoRA training into one workflow.

![preview placeholder](docs/preview.png)

## What it does

- **Generate** images from a queue of prompts using SDXL + your character's LoRA
- **Review** and vote on generated images in a local web UI (heart, like, dislike, anatomy issue, comment)
- **Organize** liked images into a separate folder, archive the rest
- **Upscale** liked images via SDXL hires-fix img2img (auto-detects VRAM, falls back to 1.5× on lower-tier GPUs)
- **Train** new character LoRAs from your own reference images via [ai-toolkit](https://github.com/ostris/ai-toolkit)

## Hardware requirements

| Component | Minimum | Recommended |
|---|---|---|
| GPU | NVIDIA, 12 GB VRAM | NVIDIA, 16+ GB VRAM |
| OS | Windows 10/11 | Windows 11 |
| Disk | ~15 GB free | ~30 GB free (more for many checkpoints) |
| Python | 3.10 or 3.11 | 3.11 |

The 16 GB tier auto-runs the upscaler at 1.5×; 18+ GB gets full 2×. Training works on 16 GB at default settings (rank 32, batch 1, gradient checkpointing).

## Quickstart

```cmd
git clone --recursive https://github.com/tsuseki/vrfu-ai.git
cd vrfu-ai
setup.bat
download_models.bat
launch_website.bat
```

The `--recursive` flag pulls the bundled [ai-toolkit](https://github.com/ostris/ai-toolkit) training framework. Forgot it? `setup.bat` runs `git submodule update --init` for you.

Then drop a LoRA your friend sent you into `loras/characters/demo_character_v1/demo_character_v1.safetensors`, edit `characters/demo_character/config.yaml` to match the LoRA's identity, click ▶️ Start in the website. See [docs/quickstart.md](docs/quickstart.md) for the full walkthrough.

## Documentation

- [docs/install.md](docs/install.md) — first-time setup, model downloads, troubleshooting installation
- [docs/quickstart.md](docs/quickstart.md) — your first generation in 5 minutes
- [docs/add-character.md](docs/add-character.md) — capturing references and training your own character LoRA
- [docs/prompting.md](docs/prompting.md) — prompt engineering for Illustrious / NoobAI / SDXL anime models
- [docs/artist-palette.md](docs/artist-palette.md) — curated artist tags that work well
- [docs/reference.md](docs/reference.md) — folder layout, config schemas, web API (for power users)
- [docs/troubleshooting.md](docs/troubleshooting.md) — common errors and how to fix them

## License

This project is MIT licensed. See [LICENSE](LICENSE) for details. Bundled `vendor/ai-toolkit/` retains its own license (also MIT, see `vendor/ai-toolkit/LICENSE`). The base SDXL checkpoint and character LoRAs are not part of this repo and have their own licenses — see the install docs for download links and license notes.
