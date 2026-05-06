# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`vrfu-ai` is a local SDXL anime-art pipeline. The user runs a web UI on `127.0.0.1:8765`; the UI manages a queue of prompts and spawns Python subprocesses for generation, upscaling, and LoRA training. Everything is on-disk and local — no cloud, no API keys.

## Running and developing

```cmd
launch_website.bat       :: Kills any prior server on :8765 and starts web/server.py
setup.bat                :: First-time install — builds ai-toolkit venv, installs requirements.txt
```

`launch_website.bat` invokes the **ai-toolkit submodule's venv python** (`ai-toolkit\venv\Scripts\python.exe`), not system Python. Any script that imports `torch`/`diffusers` must run from that venv. The web server is a stdlib `ThreadingHTTPServer` — no framework, no build step, no bundler.

Pipeline scripts under `scripts/` are launched by the web server as subprocesses (see `spawn_tool` in `web/server.py`). To run one manually:

```cmd
ai-toolkit\venv\Scripts\python.exe scripts\generate.py --character tsu_chocola
ai-toolkit\venv\Scripts\python.exe scripts\upscale.py  --character all --scale 2.0
ai-toolkit\venv\Scripts\python.exe scripts\train.py    --character tsu_chocola
```

The frontend is **vanilla JS** in `web/app.js` (no framework, no build). Edit and hard-refresh the browser. No tests, no linter configured.

## Architecture (the parts that span files)

**`scripts/_common.py`** is the single source of truth for paths. Every script and `web/server.py` imports it as `C` and uses `C.ROOT`, `C.CHARACTERS`, `C.UNIFIED_QUEUE`, `C.char_dir(name)`, etc. Paths are derived from `_common.py`'s own location, so the project relocates without config edits.

**Web server is the orchestrator.** `web/server.py` is the only long-running process. It serves the UI from `web/`, exposes a JSON API for everything (`/api/queue`, `/api/queue/add|update|delete|reorder|import|clear|shuffle`, `/api/vote`, `/api/run/start|stop`, `/api/upscale`, `/api/training/start`, `/api/organize`), and uses `spawn_tool()` to launch generation/upscale/training as child processes. The frontend polls `/api/run/status` for live progress.

**The queue is unified, not per-character.** `queue.yaml` at the repo root holds entries for every character. Each entry has a `character` field. Per-character `characters/<name>/queue.yaml` files exist as legacy stubs — ignore them; the canonical queue is the root one. `generate.py` reads the unified queue, processes entries matching its `--character` (or all of them in `--character all` mode), and moves completed entries to `characters/<name>/archive/done.yaml`.

**Character configs are prepended at generation time.** `characters/<name>/config.yaml` contains `character_tags` (anchor tags like `1girl, solo, fox girl, ...`), `character_lora` path + weight, `negative_tags`, and an `outfits:` dict for `{outfit:name}` placeholder substitution. `generate.py` (via `prompt_build.py`) prepends `character_tags` and runs outfit-substitution before sending to the model. Queue entries do **not** need to repeat character anchors — only the scenario-specific prompt.

**Activity log.** `activity.jsonl` at the repo root is append-only. `C.log_event()` writes one JSON line per significant event (`queue_added`, `queue_cleared`, `voted`, `organize_clicked`, `server_started`, `generated`). The Activity tab in the UI tails this file. It's the audit trail and the recovery substrate when state goes sideways.

## Conventions to internalize before editing

**Never have an agent (Edit/Write) modify `queue.yaml` directly.** A prior Sonnet sub-agent on an unrelated task wiped ~400 unfinished entries; the user lost work. `web/server.py` now has `_backup_queue()` which snapshots `queue.yaml.last.bak` (1-step undo) and `queue.yaml.backups/queue.YYYYMMDD-HHMMSS.yaml` (rolling 20, triggered on shrinkage of ≥10 entries). **The backup only runs through `save_queue()`**, which means going through the API. Bulk queue work should `POST /api/queue/import` (appends a YAML list) or `POST /api/queue/update` per entry — never raw file writes.

**The "close-up rule" lives in `docs/queue.md`.** When framing is `close-up`, `face focus`, `bust shot`, `upper body`, `head shot`, or `portrait`, strip every lower-body tag (shorts, skirt, barefoot, toenails, feet, legs, etc.) — otherwise the model wedges miniature shoes or feet into the corner of the frame. `docs/queue.md` is the canonical Claude-facing reference for queue work — API endpoints, Python recipe template, entry schema, valid resolutions (1024² / 1216×832 / 832×1216), the 1girl/2girls convention, and the kemonomimi ear-position convention (drooping for sad/sleepy, flattened for scared/angry/shy). Read it before building queue entries.

**Read `docs/prompting.md`** for tag-order and Illustrious/NoobAI/Pony specifics. `docs/reference.md` is the power-user folder/API reference.

**Branch hygiene.** The repo has a `local-only` branch with push protection (per-branch `pushRemote=no_push` + `.git/hooks/pre-push` blocking `refs/heads/local-only` and `refs/heads/private/*`). It's where personal scripts live (`scratch/`). The user works on `local-only` daily so the deployed server has the latest local edits; they switch to `main` only to push public-facing code (`web/`, `docs/`, `characters/<name>/config.yaml`). Don't commit `scratch/` to `main`.

**Server restart needed for `web/server.py` edits**, not for `app.js`/`index.html`/`style.css` (those are static and only need a hard browser refresh).

**Windows-isms.** Backslash paths show up in `output: output\NNNN_label.png` strings inside `done.yaml`. UTF-8 stdout reconfiguration in `generate.py` is intentional for cp932/cp1252 console boxes. The pre-push hook is a POSIX shell script — works because git ships its own sh on Windows.

## Memory

Persistent project memory lives at `~/.claude/projects/F--AI-Art/memory/`. The index is `MEMORY.md`. Notable entries cover: queue prompt-writing conventions, artist-tag fidelity tradeoff, references to `docs/prompting.md` and `docs/queue.md`, the queue-wipe safety memo, and tsu_chocola's visual identity (one diamond per cheek, artist tag required on every prompt because the v2 LoRA was trained on grey-bg VRChat shots). Consult before iterating on prompts.
