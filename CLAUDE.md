# CLAUDE.md

Orientation for any LLM agent (Claude Code, Cursor, Aider, etc.) operating
on this repository. **This project is designed to be operated through an
agent** — the docs and conventions are written for you, not just for
human readers. Read this file first.

## What this is

`vrfu-ai` is a local SDXL anime-art pipeline: per-character LoRAs +
SDXL base + a web UI on `127.0.0.1:8765` that orchestrates generation,
voting, organizing, upscaling, and on-rig LoRA training. Everything is
on-disk and local — no cloud, no API keys.

User interaction model:

1. The **user** runs `launch_website.bat`, opens the web UI, and votes
   on generated images (super_like / love / like / style / location /
   pose / outfit / dislike / anatomy_issue, plus free-form comments).
2. **You (the agent)** read those signals + the project docs to write
   new prompts, set up new characters, troubleshoot problems, and ship
   character bundles to friends. The user *can* do everything by hand
   through the UI; you mostly exist to make it faster.

If the user says *"queue 50 prompts of X"*, *"set up Mari as a new
character"*, *"export this character so I can send it to a friend"*, or
*"why is generation slow?"* — the docs in this repo (especially
`docs/queue.md`, `docs/add-character.md`, `docs/exporting.md`,
`docs/troubleshooting.md`) tell you exactly what to do.

## Running and developing

```cmd
launch_website.bat       :: Kills any prior server on :8765 and starts web/server.py
setup.bat                :: First-time install — builds ai-toolkit venv, installs requirements.txt
```

`launch_website.bat` invokes the **ai-toolkit submodule's venv python**
(`ai-toolkit\venv\Scripts\python.exe`), not system Python. Any script
that imports `torch` / `diffusers` must run from that venv. The web
server is a stdlib `ThreadingHTTPServer` — no framework, no build step,
no bundler.

Pipeline scripts under `scripts/` are launched by the web server as
subprocesses (see `spawn_tool` in `web/server.py`). To run one manually:

```cmd
ai-toolkit\venv\Scripts\python.exe scripts\generate.py        --character tsu_chocola
ai-toolkit\venv\Scripts\python.exe scripts\upscale.py          --character all --scale 2.0
ai-toolkit\venv\Scripts\python.exe scripts\train.py            --character tsu_chocola
ai-toolkit\venv\Scripts\python.exe scripts\export_character.py --character mari
```

The frontend is **vanilla JS** in `web/app.js` (no framework, no build).
Edit and hard-refresh the browser. No tests, no linter configured.

## What the user usually wants from you

| Request shape | Right doc to read first | Notable concrete step |
|---|---|---|
| "Queue prompts for X" | [`docs/queue.md`](docs/queue.md) | `POST /api/queue/import` with a YAML list — never `Edit` `queue.yaml` directly |
| "Set up new character" | [`docs/add-character.md`](docs/add-character.md) | Copy `_template/`, fill `character_tags` + `outfits.default` |
| "Export X to send to a friend" | [`docs/exporting.md`](docs/exporting.md) | `python scripts/export_character.py --character X` |
| "I got a bundle from a friend" | [`docs/exporting.md`](docs/exporting.md) (receiver section) | Unzip into repo root, fill any missing `character_tags` |
| "Generation is slow / errors" | [`docs/troubleshooting.md`](docs/troubleshooting.md) | Most common: Blackwell (sm_120) needs cu128 wheels + cuDNN-SDP |
| "Train a LoRA for X" | [`docs/add-character.md`](docs/add-character.md) | `POST /api/training/start` or `🎓 Train LoRA` button |
| "Why does my prompt look generic" | [`docs/prompting.md`](docs/prompting.md) | Usually `character_tags` too short or wrong artist tag |

## Architecture (the parts that span files)

**`scripts/_common.py`** is the single source of truth for paths. Every
script and `web/server.py` imports it as `C` and uses `C.ROOT`,
`C.CHARACTERS`, `C.UNIFIED_QUEUE`, `C.char_dir(name)`, etc. Paths are
derived from `_common.py`'s own location and detect Claude Code worktree
locations (`.claude/worktrees/<name>/`) so they always resolve to the
real project root regardless of where the script was invoked from.

**Web server is the orchestrator.** `web/server.py` is the only
long-running process. It serves the UI from `web/`, exposes a JSON API
for everything (queue CRUD, votes, run control, upscale, training,
organize, character config edit), and uses `spawn_tool()` to launch
generation / upscale / training as child processes. The frontend polls
`/api/run/status` for live progress.

**Single source of truth for character config: `characters/<name>/config.yaml`.**
The Characters page in the website edits this file; `generate.py` reads
it; `scripts/export_character.py` ships it. There is no sidecar, no
overlay, no in-memory shadow copy. When the user says *"I edited X in
the website"*, X is in that file.

**The queue is unified, not per-character.** `queue.yaml` at the repo
root holds entries for every character. Each entry has a `character`
field. Per-character `characters/<name>/queue.yaml` files exist as
legacy stubs — ignore them; the canonical queue is the root one.
`generate.py` reads the unified queue, processes entries matching its
`--character` (or all of them in `--character all` mode), and moves
completed entries to `characters/<name>/archive/done.yaml`.

**Character configs are prepended at generation time.**
`characters/<name>/config.yaml` contains `character_tags` (anchor tags
like `1girl, solo, fox girl, ...`), `character_lora` path + weight,
`negative_tags`, and an `outfits:` dict for `{outfit:name}` placeholder
substitution. `generate.py` (via `prompt_build.py`) prepends
`character_tags` and runs outfit-substitution before sending to the
model. Queue entries do **not** need to repeat character anchors —
only the scenario-specific prompt.

**Activity log.** `activity.jsonl` at the repo root is append-only.
`C.log_event()` writes one JSON line per significant event
(`queue_added`, `queue_cleared`, `voted`, `organize_clicked`,
`server_started`, `generated`). The Activity tab in the UI tails this
file. It's the audit trail and the recovery substrate when state goes
sideways.

## The preference-learning loop (important)

Every Liked image carries the prompt that produced it, the artist tag
used, the framing, the outfit, etc. Every vote (`super_like` / `love` /
`style` / `pose` / etc.) is a labelled signal about what the user values.
**Use this when the user asks for new prompts.**

Workflow when the user says *"queue more like the ones I liked"* or
*"more affection prompts but better"*:

1. `GET /api/images?view=liked&character=<name>` — gets liked images
   with their prompts, votes, comments, artist tags, framing.
2. Look for patterns in what's liked: which artists fire well? which
   framings get super_likes? which outfit / scene combos earn comments?
3. Build new prompts that reuse those patterns. Don't blindly copy —
   vary the scenario, but keep the dimensions that scored highly.
4. Include in the queue rationale (your message back to the user) which
   liked-image patterns informed the new batch.

Counterpart for negatives: `view=archive` returns disliked /
anatomy_issue / un-loved images. Their prompts contain the patterns to
*avoid*. If `artist:X` shows up frequently in archive but rarely in
liked, downweight or skip that artist.

This is the project's central feedback mechanism. The user is voting
*for you* (and for future-you), not just for sorting.

## Conventions to internalize before editing

**Never have an agent (Edit / Write) modify `queue.yaml` directly.** A
prior Sonnet sub-agent on an unrelated task wiped ~400 unfinished
entries; the user lost work. `web/server.py` has `_backup_queue()`
which snapshots `queue.yaml.last.bak` (1-step undo) and timestamped
`queue.yaml.backups/queue.YYYYMMDD-HHMMSS.yaml` (rolling 20, triggered
on shrinkage of ≥10 entries). **The backup only runs through
`save_queue()`**, which means going through the API. Bulk queue work
should `POST /api/queue/import` (appends a YAML list) or
`POST /api/queue/update` per entry — never raw file writes.

**The "close-up rule" lives in `docs/queue.md`.** When framing is
`close-up`, `face focus`, `bust shot`, `upper body`, `head shot`, or
`portrait`, strip every lower-body tag (shorts, skirt, barefoot,
toenails, feet, legs, etc.) — otherwise the model wedges miniature
shoes or feet into the corner of the frame. `docs/queue.md` is the
canonical agent-facing reference for queue work — API endpoints,
Python recipe template, entry schema, valid resolutions
(1024² / 1216×832 / 832×1216), the 1girl/2girls convention, the
kemonomimi ear-position convention (drooping for sad/sleepy,
flattened for scared/angry/shy), and the preference-learning loop.
Read it before building queue entries.

**Read `docs/prompting.md`** for tag-order and Illustrious / NoobAI /
Pony specifics. `docs/reference.md` is the power-user folder/API
reference. `docs/exporting.md` is the canonical reference for shipping
characters between users.

**Branch hygiene.** The repo has a `local-only` branch with push
protection (per-branch `pushRemote=no_push` + `.git/hooks/pre-push`
blocking `refs/heads/local-only` and `refs/heads/private/*`). Personal
scripts live there (`scratch/`). The user works on `local-only` daily so
the deployed server has their latest local edits; they switch to `main`
only to push public-facing code (`web/`, `docs/`, `characters/_demo_character`,
`characters/_template`). Don't commit `scratch/` to `main`. Don't commit
files under `characters/<personal-name>/` to `main` — only `_demo_character`
and `_template` ship publicly.

**Server restart needed for `web/server.py` edits**, not for
`app.js` / `index.html` / `style.css` (those are static and only need a
hard browser refresh).

**Windows-isms.** Backslash paths show up in `output: output\NNNN_label.png`
strings inside `done.yaml`. UTF-8 stdout reconfiguration in `generate.py`
is intentional for cp932 / cp1252 console boxes. The pre-push hook is a
POSIX shell script — works because git ships its own sh on Windows.

## Memory

Persistent project memory lives at `~/.claude/projects/F--AI-Art/memory/`.
The index is `MEMORY.md`. Notable entries cover: queue prompt-writing
conventions, artist-tag fidelity tradeoff, references to
`docs/prompting.md` and `docs/queue.md`, the queue-wipe safety memo, and
tsu_chocola's visual identity (one diamond per cheek, artist tag required
on every prompt because the v2 LoRA was trained on grey-bg VRChat shots).
Consult before iterating on prompts. Update memory when the user
corrects you on something durable (a preference, a per-character quirk,
a historical reason for a workaround).
