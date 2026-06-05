"""One-shot migration: read every YAML/JSON state file in the repo and
populate vrfu.db. Idempotent — rerunning is safe; existing rows are
upserted, not duplicated. Old files are left in place untouched so a
manual rollback is always possible until you delete them.

Usage:
    ai-toolkit/venv/Scripts/python.exe scripts/migrate_to_db.py
    ai-toolkit/venv/Scripts/python.exe scripts/migrate_to_db.py --rename-old

The --rename-old flag appends `.migrated` to each file we successfully
imported so the running system stops reading them. Skip this on the
first run; do it once you've verified the DB is good.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # so we can `from scripts import ...`

from scripts import _common as C
from scripts import store


def _load_yaml(p: Path) -> object:
    if not p.exists() or p.stat().st_size == 0:
        return None
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ! YAML parse error on {p.name}: {e}", file=sys.stderr)
        return None


def migrate_done(character: str) -> int:
    p = C.done_file(character)
    raw = _load_yaml(p) or []
    if not isinstance(raw, list):
        return 0
    n = 0
    with store.transaction():
        for entry in raw:
            if not isinstance(entry, dict) or "id" not in entry:
                continue
            try:
                entry = dict(entry)
                entry["character"] = character
                # Some entries had `label` missing — derive from output path
                if "label" not in entry and entry.get("output"):
                    op = str(entry["output"])
                    import re
                    m = re.match(r"^output[\\/](\d+)_(.+)\.png$", op)
                    if m:
                        entry["label"] = m.group(2)
                if "label" not in entry:
                    continue
                # Map old field names to new schema
                if "output" in entry and "output_path" not in entry:
                    entry["output_path"] = entry.pop("output")
                store.done_upsert(entry)
                n += 1
            except Exception as e:
                print(f"  ! done row error id={entry.get('id')}: {e}",
                      file=sys.stderr)
    return n


def migrate_queue_unified() -> int:
    """The unified queue.yaml at repo root."""
    p = C.UNIFIED_QUEUE
    raw = _load_yaml(p) or []
    if not isinstance(raw, list):
        return 0
    # queue_append skips duplicates by (character, label) so reruns are safe.
    n = store.queue_append(raw)
    return n


def migrate_feedback() -> int:
    """web/data/feedback.json — character → stem → {votes, comment, ...}"""
    p = C.ROOT / "web" / "data" / "feedback.json"
    if not p.exists():
        return 0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ! feedback.json parse error: {e}", file=sys.stderr)
        return 0
    n = 0
    with store.transaction():
        conn = store._connect()
        for character, stems in data.items():
            if not isinstance(stems, dict):
                continue
            for stem, fb in stems.items():
                if not isinstance(fb, dict):
                    continue
                votes = fb.get("votes") or {}
                comment = fb.get("comment") or ""
                first_voted = fb.get("first_voted")
                last_updated = fb.get("last_updated") or first_voted
                conn.execute(
                    "INSERT OR REPLACE INTO feedback "
                    "(character, stem, votes_json, comment, first_voted, last_updated) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (character, stem, json.dumps(votes, ensure_ascii=False),
                     comment, first_voted, last_updated),
                )
                n += 1
    return n


def migrate_activity() -> int:
    p = C.ROOT / "activity.jsonl"
    if not p.exists():
        return 0
    n = 0
    with store.transaction():
        conn = store._connect()
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                ts = e.pop("ts", None) or datetime.now().isoformat(timespec="seconds")
                event = e.pop("event", "")
                character = e.pop("character", None)
                conn.execute(
                    "INSERT INTO activity (ts, event, character, fields_json) "
                    "VALUES (?, ?, ?, ?)",
                    (ts, event, character, json.dumps(e, ensure_ascii=False)),
                )
                n += 1
    return n


def migrate_upscale_log(character: str) -> int:
    p = C.upscaled_log_file(character)
    raw = _load_yaml(p) or []
    if not isinstance(raw, list):
        return 0
    n = 0
    with store.transaction():
        conn = store._connect()
        for rec in raw:
            if not isinstance(rec, dict):
                continue
            stem = rec.get("stem")
            if not stem:
                continue
            extra = {k: v for k, v in rec.items()
                     if k not in ("stem", "scale", "model", "duration_s", "ts")}
            conn.execute(
                "INSERT INTO upscale_log (character, stem, scale, model, "
                "duration_s, ts, extra_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (character, stem, rec.get("scale"), rec.get("model"),
                 rec.get("duration_s"),
                 rec.get("ts") or datetime.now().isoformat(timespec="seconds"),
                 json.dumps(extra, ensure_ascii=False) if extra else None),
            )
            n += 1
    return n


def migrate_last_id(character: str) -> int | None:
    p = C.char_dir(character) / "last_id.txt"
    if not p.exists():
        return None
    try:
        n = int(p.read_text(encoding="utf-8").strip())
    except Exception:
        return None
    store.character_state_bump_last_id(character, n)
    return n


def migrate_config(character: str) -> bool:
    p = C.char_dir(character) / "config.yaml"
    raw = _load_yaml(p)
    if not isinstance(raw, dict):
        return False
    store.character_config_set(character, raw)
    return True


def _rename_old(p: Path) -> None:
    """Rename p to p.migrated.<ts> so the old path stops being read."""
    if not p.exists():
        return
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = p.with_suffix(p.suffix + f".migrated.{ts}")
    try:
        p.rename(target)
        print(f"  renamed {p.name} -> {target.name}")
    except OSError as e:
        print(f"  ! could not rename {p}: {e}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rename-old", action="store_true",
                    help="Rename successfully-imported files to .migrated.<ts>")
    args = ap.parse_args()

    print(f"DB: {store.DB_PATH}")
    store.init()
    print("schema initialised")

    # Cross-character files first
    print("\n== feedback.json")
    n = migrate_feedback()
    print(f"  imported {n} feedback rows")

    print("\n== activity.jsonl")
    n = migrate_activity()
    print(f"  imported {n} activity events")

    print("\n== unified queue.yaml")
    n = migrate_queue_unified()
    print(f"  imported {n} queue entries (duplicates by (char,label) skipped)")

    # Per-character files
    characters = []
    if C.CHARACTERS.exists():
        for d in sorted(C.CHARACTERS.iterdir()):
            if d.is_dir() and not d.name.startswith("_") and d.name != "all":
                characters.append(d.name)
    print(f"\ncharacters found: {characters}")

    for character in characters:
        print(f"\n-- {character}")
        n = migrate_done(character)
        print(f"  done: {n}")
        n = migrate_upscale_log(character)
        print(f"  upscale_log: {n}")
        n = migrate_last_id(character)
        print(f"  last_id: {n}")
        ok = migrate_config(character)
        print(f"  config: {'ok' if ok else 'missing/empty'}")

    # Take a snapshot right after the initial import — this is a known
    # good state we can always roll back to.
    snap = store.snapshot(label="post-migration")
    print(f"\nsnapshot: {snap}")

    if args.rename_old:
        print("\n== renaming old files (--rename-old)")
        _rename_old(C.ROOT / "web" / "data" / "feedback.json")
        _rename_old(C.ROOT / "activity.jsonl")
        _rename_old(C.UNIFIED_QUEUE)
        for character in characters:
            _rename_old(C.done_file(character))
            _rename_old(C.upscaled_log_file(character))
            _rename_old(C.char_dir(character) / "last_id.txt")
            _rename_old(C.char_dir(character) / "config.yaml")


if __name__ == "__main__":
    main()
