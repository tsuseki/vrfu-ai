# Reference

Power-user docs: folder layout, config schemas, web API. Read this if you're customizing the project, debugging, or sharing it further.

## Folder layout

```
vrfu-ai/
├── README.md                       Project overview + quickstart
├── setup.bat                       First-time install
├── download_models.bat             Optional automated checkpoint download
├── requirements.txt                Main pipeline extras (compel, yaml, Pillow)
├── launch_website.bat              Start the local web UI
│
├── scripts/                        The Python pipeline
│   ├── _common.py                  Shared paths, character resolution, activity log
│   ├── generate.py                 SDXL generation runner (reads queue.yaml)
│   ├── upscale.py                  Hires-fix img2img upscaler
│   ├── train.py                    LoRA training wrapper for ai-toolkit
│   ├── build_reference.py          Generate docs/REFERENCE_<name>.md from votes
│   ├── check_tags.py               Validate prompt tags against Danbooru post counts
│   └── review_prompts.py           Lint queue prompts for structural issues
│
├── web/                            Local browser UI
│   ├── server.py                   Stdlib-only HTTP server bound to 127.0.0.1:8765
│   ├── index.html                  Single-page app
│   ├── app.js                      Frontend logic
│   └── style.css                   Theming
│
├── characters/
│   ├── _template/                  Scaffold copied when you click ➕ New
│   └── <name>/
│       ├── config.yaml             Generation config (trigger, tags, outfits, paths)
│       ├── queue.yaml              Pending prompts (gitignored — your data)
│       ├── training_config.yaml    ai-toolkit training config
│       ├── training/               Training images + .txt captions (gitignored)
│       ├── output/                 Generated images (gitignored)
│       ├── liked/                  Post-Organize favorites (gitignored)
│       ├── liked_upscaled/         2K versions (gitignored)
│       ├── archive/                Post-Organize rejects (gitignored)
│       └── logs/                   Generation/training/upscale logs (gitignored)
│
├── checkpoints/                    Base SDXL .safetensors (you download these)
├── loras/
│   ├── <character>/                Per-character folder
│   │   ├── <character>.safetensors The active LoRA
│   │   ├── optimizer.pt            ai-toolkit's resume state (gitignored)
│   │   ├── samples/                Training-time samples (gitignored)
│   │   └── archived_<date>/        Prior versions auto-saved before retraining
│   └── styles/                     Optional style LoRAs you stack on top
├── upscalers/                      Future ESRGAN-style upscalers (currently unused)
│
├── docs/                           This folder
│
├── ai-toolkit/                     Submodule — training framework (https://github.com/ostris/ai-toolkit, pinned at 0dcbabf)
│                                    Friend gets it via `git clone --recursive` or setup.bat.
└── activity.jsonl                  Append-only event log (gitignored)
```

## `characters/<name>/config.yaml` schema

Read by `_common.load_character()`. Path-valued fields are repo-relative; the loader resolves them against the repo root.

```yaml
character_name:        Cocoa Mizu                                  # Display name
trigger_word:          "cocoa mizu"                                # LoRA trigger
character_tags:        "1girl, solo, fox girl, ..."                # Auto-prepended to every prompt
checkpoint:            "checkpoints/waiIllustriousSDXL_v170.safetensors"
character_lora:        "loras/cocoa_mizu/cocoa_mizu.safetensors"
character_lora_weight: 0.8           # 0.7-0.95
extra_loras: []                      # List of {path, name, weight} stacked on top
sampler: euler_a                     # or dpmpp_2m_karras
upscale_scale: 2.0                   # Optional override; default = auto by VRAM

outfits:                             # Named outfits referenced as {outfit} / {outfit:name}
  default: "white camisole, black shorts, off shoulder"
  bikini:  "white bikini"
```

Required: `trigger_word`, `character_tags`, `checkpoint`, `character_lora`.

## `characters/<name>/queue.yaml` schema

A YAML list of prompt entries. `generate.py` reads from the top, removes each entry as it completes (moving to `done.yaml`).

```yaml
- label:    sfw-cafe-portrait        # Filename-safe, becomes part of the PNG name
  prompt:   "1girl, solo, sensitive, {outfit}, sitting at cafe, looking at viewer, soft lighting, very aesthetic, absurdres"
  width:    832                       # Optional (default 1024)
  height:   1216                      # Optional
  seed:     1234567                   # Optional (default: random)
  steps:    28                        # Optional
  guidance: 5.5                       # Optional
  negative: "extra negatives"         # Optional, appended to BASE_NEGATIVE
```

The `{outfit}` and `{outfit:name}` placeholders are expanded by `generate.py` using the character's `outfits` dict. If the named outfit doesn't exist, generation aborts with a clear error.

## `characters/<name>/training_config.yaml`

This is ai-toolkit's config format. The template handles 99% of the fields correctly — you only need to override `trigger_word` (matches `config.yaml`), `name` (the LoRA's filename without `.safetensors`), and dataset path (already templated to point at the character's `training/` folder).

For the rare cases you want to customize: rank, learning rate, optimizer, sample prompts. See ai-toolkit's docs for the full schema.

## Web API

All endpoints are localhost-only and don't require auth.

### Read endpoints (GET)

| Endpoint | Returns |
|---|---|
| `/api/characters` | `{characters: ["cocoa_mizu", ...]}` |
| `/api/character-info?character=X` | Full config dump + outfits + popular_tags |
| `/api/character/thumbnail?character=X` | Image bytes (representative pic for the character) |
| `/api/queue?character=X` | The character's queue.yaml as JSON |
| `/api/images?character=X&view=output|liked|archive&page=N&per_page=M` | Paginated image list |
| `/api/stats?character=X` | Vote stats, top artists, top categories |
| `/api/activity?character=X&limit=200` | Recent events from activity.jsonl |
| `/api/run/status` | Current generation runner state |
| `/api/tool/status?tool=upscale|training` | Current upscaler / trainer state |
| `/api/docs` | List of available .md files in docs/ |
| `/api/docs/<slug>` | Raw markdown content |

### Write endpoints (POST)

| Endpoint | Body | Effect |
|---|---|---|
| `/api/character/create` | `{name}` | Scaffold new character from `_template/` |
| `/api/run/start` | `{character}` | Start generation |
| `/api/run/stop` | `{}` | Stop generation |
| `/api/upscale` | `{character}` | Start upscaling liked/ |
| `/api/training/start` | `{character, chain_to_gen?}` | Start LoRA training |
| `/api/training/stop` | `{}` | Stop training |
| `/api/training/chain-to-gen` | `{character, enabled}` | Toggle auto-start gen after training |
| `/api/queue/add` | `{character, label, prompt, width, height, ...}` | Add a prompt |
| `/api/queue/update` | `{character, label, ...}` | Edit a prompt by label |
| `/api/queue/delete` | `{character, label}` | Remove a prompt |
| `/api/queue/clear` | `{character}` | Empty the queue |
| `/api/queue/shuffle` | `{character}` | Randomize the queue order |
| `/api/queue/import` | `{character, yaml}` | Bulk import from a YAML string |
| `/api/queue/export` | (GET) | Download queue.yaml |
| `/api/vote` | `{character, stem, vote_type, value}` | Cast a vote |
| `/api/organize` | `{character}` | Move output/ → liked/ or archive/ based on votes |

## Logs and state

- **`activity.jsonl`** — append-only event log. One JSON object per line: `{ts, event, character, ...}`. Events include `generated`, `voted`, `organize_clicked`, `upscaled`, `training_started`, `training_ended`, `character_created`, etc. Useful for debugging.
- **`web/data/feedback.json`** — votes per character per image stem. Loaded once on every server start, written on every vote.
- **`characters/<name>/done.yaml`** — full prompt + metadata for every successfully generated image. Used by the website to look up artists and prompt details.
- **`characters/<name>/upscaled.yaml`** — same shape but for upscaled outputs.

All these are gitignored — they're per-machine, per-user.

## How `generate.py` builds the final prompt

```
[BASE_POSITIVE], [trigger_word], [character_tags], [user prompt with {outfit} expanded]
```

So a queue entry like:
```yaml
prompt: "1girl, solo, sensitive, {outfit}, sitting in cafe, very aesthetic, absurdres"
```

Becomes (for cocoa_mizu):
```
masterpiece, best quality, amazing quality, very aesthetic, newest, absurdres, anime coloring, cel shading,
cocoa mizu, 1girl, solo, fox girl, ..., 1girl, solo, sensitive, white sports bra, white asymmetric jacket, ..., sitting in cafe, very aesthetic, absurdres
```

Yes, `1girl, solo` and `very aesthetic, absurdres` repeat — that's intentional. Compel handles >77-token prompts by chunking, and the redundancy is harmless. See [prompting.md](prompting.md) for why this ordering matters.
