# Queue merge — design notes

Captured 2026-05-01 between sessions. **This is a design doc, not a status
report.** Implementation is the next session's work.

## Goal

Run overnight batches that mix multiple characters (e.g. 100 tsu + 100 cocoa
+ 100 kutsu), each with their own prompting style, without manual
hand-holding. Review and vote across all characters in unified tabs.

## Architecture decided

**Per-entry character field.** Each queue.yaml entry can specify which
character/LoRA to use:

```yaml
- label: emo-wink-park-cherry-nardack
  prompt: ...
  character: tsu_chocola      # ← optional; falls back to queue's owner
```

**Outputs stay per-character.** Each character keeps its own
`output/`, `liked/`, `archive/`, `done.yaml`. The website API merges
them at request time when the user filters "All".

**Character picker moves out of the top bar.** Each tab gets its own:
- **Generation tab**: picks which character's queue you're editing /
  running. No "All" option — you can only edit one queue at a time, and
  even though Run can process mixed-character entries, the queue UI
  itself is per-file.
- **Review tabs (New / Liked / Archive)**: gain an "All" option (default).
  Backend aggregates across characters when `?character=all` is sent.

## Phases

### Phase 1 — generate.py per-entry character (smallest, most foundational)

Touch points:

- `load_pipeline(cfg)` currently loads one character's LoRA at startup.
  Refactor to support **switching LoRAs mid-run** when the next entry's
  character differs from the current.
- `cfg = load_yaml(...)` is currently called once for the run-target.
  Need a per-character config cache so `character_tags` and `outfits`
  lookups go against the right character per entry.
- Output path: `C.output_dir(entry_character)` instead of
  `C.output_dir(run_character)`.

LoRA switch cost is ~3–5 seconds. For a 300-entry mixed queue that's
10–20 minutes of swap overhead worst case if zigzagged. Mitigation
in Phase 2.

CLI shape:

```
python generate.py --character tsu_chocola
    # processes tsu's queue; entries without `character:` field run on tsu
    # entries WITH `character: cocoa_mizu` switch the LoRA to cocoa for that entry
```

No new flag needed for Phase 1. Phase 2 adds `--order` to control
how mixed entries are processed.

### Phase 2 — ordering + warning

```
python generate.py --character tsu_chocola --order character
python generate.py --character tsu_chocola --order original
```

- `--order character` (DEFAULT): sort entries so consecutive same-character
  entries cluster together. Minimizes LoRA switches — you swap once
  per character, not per entry.
- `--order original`: respect the user's queue order verbatim.
  **Warn at startup** with the count of LoRA switches the run will incur
  (`"This run will switch LoRA 47 times. Use --order character to
  reduce to 3."`).

### Phase 3 — `character=all` aggregate API

Endpoints to extend (all currently take `?character=X`):

- `/api/images` — currently reads one character's output/liked/archive.
  When `character=all`, walk every character via `C.list_characters()`
  and merge results. Each image needs to know which character it came
  from (add `character` field to the response).
- `/api/artists` — same pattern, union the per-character artist counts.
- `/api/batches` — slightly weirder — batches are per-character today.
  When `=all`, either show per-character batch sub-grouping in the
  dropdown, or hide the batch picker in "all" mode.
- `/api/stats` — already has `/api/stats/global` from a prior commit.
  Either reuse it or add `character=all` support to the existing endpoint.

The `/api/character-info` endpoint stays per-character (used by the
generation tab, not review).

### Phase 4 — frontend per-tab character pickers

Move `<select id="character">` from the top bar. Add:

- One picker on the **Generation page** (queue/run/training): single
  character, no "All", same options as today minus the redundant top-bar
  one.
- One picker on the **Review page** toolbar (new/liked/archive): includes
  "All" as the first option, default selected.

State changes in app.js:
- `state.character` stays for generation/queue/training.
- New `state.reviewCharacter` (default `"all"`) for review tabs.
- All API calls in review functions use `state.reviewCharacter`,
  passing `character=all` when applicable.
- Image cards get a small character badge (top-left chip?) so the user
  can tell which character an image is from when in "All" mode.

### Phase 5 — run banner mid-run character updates

The run-state banner currently shows "running for tsu_chocola". With a
mixed-queue run, this should update as the LoRA switches. The
`run_state` dict already has a `character` field — generate.py just
needs to update it when it switches (write a status line that the
website parses, or have the website re-poll via existing PROGRESS
markers). Trivial extension of existing polling.

## Open questions

1. **One queue file or many?** Decision: keep per-character `queue.yaml`
   files. Editing UI is per-character. Cross-character runs walk all
   queues in turn (sorted-by-character order). User can also write
   `character:` overrides in any queue if they want to mix.

2. **Activity log per-character or unified?** Already
   `activity.jsonl` is global with a `character` field. Just needs UI
   filter, which already exists.

3. **Training is still per-character.** Mixed-character runs apply only
   to generation. Training uses one LoRA target by definition.

4. **What about `cocoa_mizu_v1` / archived characters?** The character
   picker should hide folders without a current LoRA. Already handled
   by `list_characters()` requiring `config.yaml` — empty-LoRA
   characters are explicitly excluded by convention.

## Implementation order suggested

Phase 1 first (foundation). Test by hand with a small mixed queue.
Phase 2 (ordering) once Phase 1 is stable.
Phase 3 (`character=all` API) before Phase 4 (UI) so the UI has data to
show.
Phase 4 (per-tab pickers) ships as one big diff.
Phase 5 (banner updates) is a small polish on top.

Total estimate: ~400–600 LOC across server.py, generate.py, app.js,
index.html. Self-contained — no new dependencies.

## Adjacent feature: Character overview / config editor

**Separate from the queue-merge work but worth building in the same arc.**

A new tab or modal that shows each character's config and lets the user
edit it from the website instead of opening config.yaml in an editor.

What to display per character:
- `character_name`, `trigger_word`, `character_tags`
- `character_lora` path, `character_lora_weight`
- `checkpoint`, `sampler`
- All `outfits:` entries (default + named variants), with edit/add/delete
- Optionally: read-only listing of `extra_loras`

What to edit:
- `character_tags` (textarea — but warn: changes here have to match
  training captions, see PROMPTING.md §9.6)
- `character_lora_weight` (slider 0.0–1.5)
- Outfit definitions (per-variant textarea, plus a "+" button for new)

Backend:
- New `GET /api/character/config?character=X` returns the parsed config.
- New `POST /api/character/config` writes back. Use the same atomic-save
  pattern as `save_queue` (write tmp, replace) so a crash mid-edit can't
  brick the config.
- Validation: refuse to save if `character_lora` path doesn't exist;
  warn if `character_tags` has tokens not present in any training
  caption (greppable from `characters/<X>/training/*.txt`).

Frontend:
- New "⚙ Character" or "👤 Profile" tab next to Generation/Review/Activity.
- Per-character page with an editable form. Save button.
- Read-only "training preview" section showing 3–5 training thumbnails
  + a representative caption — helps the user see what the LoRA learned
  before they edit identity tags.

### Global positive/negative editor

Same tab can host:
- Read/edit `BASE_NEGATIVE` from `generate.py`. Tricky because it's
  Python source, not config. Two options:
  1. Move `BASE_NEGATIVE` and other globals into a project-level
     `config.yaml` at the repo root. `generate.py` reads it at startup.
     Web UI edits the file. **Cleaner long-term.**
  2. Patch the Python source via AST or regex. **Hack, don't do this.**
- Project-level positive prefix (the canonical opener documented in
  PROMPTING.md §9.2). Currently this is implicit — every queue entry
  has to remember to include it. Could be a project-level setting that
  generate.py prepends to every prompt automatically (with an
  `auto_prefix: false` per-entry escape hatch).

Implementation order: do per-character config editor first (~200 LOC),
then the project-level globals editor (~100 LOC + the migration of
BASE_NEGATIVE to config.yaml).

## What's NOT in scope

- A "global queue" at project root (proposed Phase 3-optional in earlier
  discussion). Per-character files are good enough.
- A separate orchestrator service. The single subprocess walking a
  multi-character queue is sufficient.
- Per-character style profiles + a `seed_queue.py` script (was proposed,
  rejected). User writes prompts directly via the website.
