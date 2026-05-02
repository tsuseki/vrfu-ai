"""
Shared utilities for the vrfu-ai.

Imported by every script under scripts/ and by web/server.py. Centralizes:
  - Project paths (so no script has hardcoded F:\\vrfu-ai\\... paths)
  - Character config loading
  - The append-only activity log
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

import yaml

# ─── Project paths ──────────────────────────────────────────────────────────
# Computed from this file's location: scripts/_common.py is one level deep,
# so its parent.parent is the repo root. This means the project works wherever
# the user clones it — no env vars, no config edits.
ROOT        = Path(__file__).resolve().parent.parent
CHARACTERS  = ROOT / "characters"
SCRIPTS     = ROOT / "scripts"
WEB         = ROOT / "web"
DOCS        = ROOT / "docs"
LORAS       = ROOT / "loras"
CHECKPOINTS = ROOT / "checkpoints"
VENDOR      = ROOT / "vendor"
ACTIVITY    = ROOT / "activity.jsonl"


# ─── Character helpers ──────────────────────────────────────────────────────
def char_dir(name: str) -> Path:
    """Return a character's root folder (creating it lazily for sub-dir access)."""
    return CHARACTERS / name


def list_characters() -> list[str]:
    """All characters with a config.yaml present.

    Folders starting with '_' (e.g. '_template', '_cache') are skipped — they're
    project scaffolding, not real characters.
    """
    if not CHARACTERS.exists():
        return []
    return sorted(p.name for p in CHARACTERS.iterdir()
                  if p.is_dir()
                  and not p.name.startswith("_")
                  and (p / "config.yaml").exists())


def _resolve_project_path(p: str) -> str:
    """Resolve a path string to an absolute path. Relative paths are anchored
    at the project ROOT so configs can use repo-relative paths like
    `checkpoints/waiIllustriousSDXL_v170.safetensors` and stay portable."""
    if not p:
        return p
    pp = Path(p)
    if pp.is_absolute():
        return str(pp)
    return str((ROOT / p).resolve())


def load_character(name: str) -> dict:
    """Read characters/<name>/config.yaml. Validates required fields.

    Path-valued fields (checkpoint, character_lora, extra_loras[].path) are
    resolved against ROOT so configs can use repo-relative paths and the
    project still works wherever the user clones it.
    """
    cfg_path = char_dir(name) / "config.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"No config.yaml for character '{name}' at {cfg_path}")
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    required = ["trigger_word", "character_tags", "checkpoint", "character_lora"]
    missing = [k for k in required if k not in cfg]
    if missing:
        raise ValueError(f"config.yaml for '{name}' is missing: {missing}")

    # Resolve path-valued fields against ROOT
    cfg["checkpoint"]     = _resolve_project_path(cfg["checkpoint"])
    cfg["character_lora"] = _resolve_project_path(cfg["character_lora"])
    if isinstance(cfg.get("extra_loras"), list):
        for lora in cfg["extra_loras"]:
            if isinstance(lora, dict) and lora.get("path"):
                lora["path"] = _resolve_project_path(lora["path"])

    cfg["_name"] = name
    cfg["_dir"]  = char_dir(name)
    return cfg


def resolve_default_character(explicit: str | None = None) -> str:
    """If --character is given, use it. Else use the only character if there's exactly one."""
    if explicit:
        return explicit
    cs = list_characters()
    if len(cs) == 1:
        return cs[0]
    if not cs:
        raise SystemExit("No characters found in characters/. Add one with a config.yaml.")
    raise SystemExit(f"Multiple characters available — pass --character. Found: {', '.join(cs)}")


# ─── Activity log ───────────────────────────────────────────────────────────
_activity_lock = threading.Lock()


def log_event(event: str, **fields) -> None:
    """Append a single JSON line to activity.jsonl.

    Example:
        log_event("generated", character="tsu_chocola", label="kantoku-witch",
                  seed=12345, duration_s=71.2)

    Writes:  {"ts": "2026-04-27T18:42:01", "event": "generated", "character": ...}
    """
    record = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event}
    record.update(fields)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _activity_lock:
        ACTIVITY.parent.mkdir(parents=True, exist_ok=True)
        with ACTIVITY.open("a", encoding="utf-8") as f:
            f.write(line)


def read_activity(character: str | None = None, limit: int = 100,
                  event: str | None = None) -> list[dict]:
    """Tail activity.jsonl. Optional filtering by character and/or event type."""
    if not ACTIVITY.exists():
        return []
    out: list[dict] = []
    with ACTIVITY.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if character and rec.get("character") != character:
                continue
            if event and rec.get("event") != event:
                continue
            out.append(rec)
    return out[-limit:]


# ─── Subdirectory accessors (used by scripts + server) ──────────────────────
def output_dir(character: str) -> Path:        return char_dir(character) / "output"
def liked_dir(character: str) -> Path:         return char_dir(character) / "liked"
def liked_archive_dir(character: str) -> Path: return char_dir(character) / "liked" / "liked_archive"
def upscaled_dir(character: str) -> Path:      return char_dir(character) / "liked_upscaled"
def archive_dir(character: str) -> Path:       return char_dir(character) / "archive"
def logs_dir(character: str) -> Path:          return char_dir(character) / "logs"
def queue_file(character: str) -> Path:        return char_dir(character) / "queue.yaml"
def done_file(character: str) -> Path:         return char_dir(character) / "archive" / "done.yaml"


# ─── Unified queue ──────────────────────────────────────────────────────────
# Single project-level queue.yaml that holds entries for all characters. Each
# entry's `character:` field routes it to the right LoRA + output folder.
# Replaces the previous per-character queue.yaml model. Per-character done.yaml
# files (the archive of completed runs) stay per-character — only the *pending*
# queue is unified.
UNIFIED_QUEUE = ROOT / "queue.yaml"


def migrate_per_character_queues_if_needed() -> None:
    """If UNIFIED_QUEUE doesn't exist but per-character queue.yaml files do,
    merge them into the unified file. Each entry gets `character: <name>`
    set if missing. Per-character files are renamed to `.legacy_per_char`
    so users can recover them but they no longer take effect.

    Idempotent — safe to call repeatedly. Only runs if the unified file
    is missing.
    """
    if UNIFIED_QUEUE.exists():
        return
    merged: list[dict] = []
    sources: list[Path] = []
    for cname in list_characters():
        qf = queue_file(cname)
        if not qf.exists():
            continue
        try:
            raw = yaml.safe_load(qf.read_text(encoding="utf-8")) or []
        except Exception:
            continue
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            if not entry.get("character"):
                entry["character"] = cname
            merged.append(entry)
        sources.append(qf)
    # Write the unified file (header + entries) even if empty — pins our
    # ownership of the path so subsequent runs don't re-migrate.
    header = (
        "# UNIFIED PROMPT QUEUE\n"
        "# Each entry routes to a character via its `character:` field.\n"
        "# Add prompts via the website (Generation tab → ➕ Add prompt).\n"
        "# Completed entries move to characters/<character>/archive/done.yaml.\n"
        "# See docs/DATA_FORMATS.md for full field reference.\n"
        "\n"
    )
    UNIFIED_QUEUE.write_text(header, encoding="utf-8")
    if merged:
        with UNIFIED_QUEUE.open("a", encoding="utf-8") as f:
            yaml.dump(merged, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    # Rename old per-character queue files so they don't get re-loaded.
    for qf in sources:
        legacy = qf.with_suffix(qf.suffix + ".legacy_per_char")
        try:
            qf.rename(legacy)
        except Exception:
            pass
def upscaled_log_file(character: str) -> Path: return char_dir(character) / "archive" / "upscaled.yaml"
