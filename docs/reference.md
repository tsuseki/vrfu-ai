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
│   ├── store.py                    SQLite state store — the source of truth (see below)
│   ├── migrate_to_db.py            One-shot: import legacy YAML/JSON files into vrfu.db
│   ├── generate.py                 SDXL generation runner (reads the queue from vrfu.db)
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
│       ├── config.yaml             Scaffold/interchange seed — runtime config lives in vrfu.db
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
├── vrfu.db                         SQLite state store — THE source of truth (gitignored)
└── db.snapshots/                   Rolling hot backups of vrfu.db (gitignored)
```

## State lives in `vrfu.db` (SQLite)

All mutable runtime state is in one SQLite database, `vrfu.db`, at the repo
root — accessed only through `scripts/store.py` (WAL mode, atomic
transactions, multi-process safe). This replaced a pile of YAML/JSON files
that lost data under concurrent writers (a race wiped 1,352 `done.yaml`
entries in May 2026; see the header of `store.py`).

| Table | Replaces | Holds |
|---|---|---|
| `queue` | `queue.yaml` | Pending prompts for every character |
| `done` | `characters/<name>/done.yaml` | Metadata for every generated image |
| `feedback` | `web/data/feedback.json` | Votes + comments per image stem |
| `upscale_log` | `characters/<name>/upscaled.yaml` | Upscale history |
| `activity` | `activity.jsonl` | Append-only event audit log |
| `character_state` | `characters/<name>/last_id.txt` | Per-character `last_id` counter |
| `character_config` | `characters/<name>/config.yaml` | Live character config (tags, lora, outfits) |

The legacy files are kept on disk as **migration sources / rollback copies**
but are no longer read at runtime. `scripts/migrate_to_db.py` imports them
(idempotent; `--rename-old` appends `.migrated` once verified). `config.yaml`
additionally survives as the **interchange/scaffold format** — `_template/`
seeds new characters and export bundles ship it — but the UI's Characters
page writes config to the DB, not back to the file.

## Character config schema

The live config is a row in the `character_config` table (this exact shape,
stored as JSON), loaded by `_common.load_character()` → `store.character_config_get()`.
The same shape is what `_template/config.yaml` and export bundles carry on
disk. Path-valued fields are repo-relative; the loader resolves them against
the repo root.

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

## Queue entry schema

Each row in the `queue` table is one prompt entry of this shape (the same
shape `POST /api/queue/import` accepts as a YAML list). `generate.py` reads
them via `store.queue_list()` and, as each completes, moves it into the
`done` table in one atomic transaction.

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
| `/api/queue?character=X` | The character's queue as JSON (from the `queue` table) |
| `/api/images?character=X&view=output|liked|archive&page=N&per_page=M` | Paginated image list |
| `/api/stats?character=X` | Vote stats, top artists, top categories |
| `/api/activity?character=X&limit=200` | Recent events from the `activity` table |
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
| `/api/queue/export` | (GET) | Download the current queue as YAML |
| `/api/vote` | `{character, stem, vote_type, value}` | Cast a vote |
| `/api/organize` | `{character}` | Move output/ → liked/ or archive/ based on votes |

## Logs and state

All of this is in `vrfu.db` now (see the table map above); query it through
`scripts/store.py`, never by opening the file.

- **`activity` table** — append-only event log: `{ts, event, character, fields_json}`. Events include `generated`, `voted`, `organize_clicked`, `upscaled`, `training_started`, `training_ended`, `character_imported`, etc. Read via `store.activity_list()` / `/api/activity`. Useful for debugging.
- **`feedback` table** — votes + comment per `(character, stem)`. Atomic per-row upsert on every vote (`store.feedback_set_vote()`).
- **`done` table** — full prompt + metadata for every successfully generated image. Used by the website to look up artists and prompt details (`store.done_list()`).
- **`upscale_log` table** — append-only history of every upscale.

`vrfu.db` is gitignored — it's per-machine, per-user. To inspect it ad hoc:
`sqlite3 vrfu.db "SELECT event, character, ts FROM activity ORDER BY ts DESC LIMIT 20;"` (read-only; for writes use `store.py`).

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
