"""SQLite-backed state store for vrfu-ai.

WHY THIS EXISTS
===============
We lost 1,352 done.yaml entries in May 2026 to a stale-snapshot race —
two generate.py processes both loaded done.yaml at startup, both
mutated their in-memory copies, both rewrote the whole file. The
second writer's snapshot truncated the first's appends. The same
pattern lived in queue.yaml, feedback.json, upscaled.yaml, and
last_id.txt. YAML/JSON files that are rewritten wholesale can never
be made safe under concurrent writers without an external lock; even
with locks, a parse error returning `[]` (mid-write truncation, BOM,
disk full) silently wipes everything.

SQLite solves this in one move:
  - WAL mode: multi-process safe out of the box.
  - Atomic transactions: no partial writes, no parse-error wipes.
  - Indexed lookups: O(log n) not O(n) full-file scans.
  - One file per project: easy to back up by copying.

WHAT'S IN HERE
==============
- Connection helpers (singleton per-process, WAL mode, FKs on).
- Schema (CREATE TABLE IF NOT EXISTS — idempotent init).
- Data-access functions for every table:
    done, queue, feedback, upscale_log, activity, character_state,
    character_config.
- Snapshot/backup helpers (online .backup API + scheduled snapshots).

USAGE
=====
    from scripts import store
    store.init()                              # idempotent; safe to call repeatedly
    store.done_insert(character="tsu_chocola", id=42, label="x", prompt=...)
    rows = store.done_list(character="tsu_chocola")

EVERY caller goes through this module. NEVER open the .db file from
elsewhere — that risks bypassing WAL/foreign-key pragmas.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

# Ensure `import _common` works whether this module is loaded as
# `scripts.store` (project root on path) or as bare `store` (scripts/ on path).
import sys as _sys
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.insert(0, str(_HERE))
import _common as C  # type: ignore  # noqa: E402


# ─── Paths ──────────────────────────────────────────────────────────────────
DB_PATH = C.ROOT / "vrfu.db"
SNAPSHOTS_DIR = C.ROOT / "db.snapshots"


# ─── Connection management ──────────────────────────────────────────────────
# One sqlite3.Connection per thread (sqlite3 requires it). Connections share
# the same on-disk file; WAL mode means concurrent readers/writers across
# threads AND processes are safe.
_local = threading.local()


def _connect() -> sqlite3.Connection:
    """Get this thread's connection, opening it lazily."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30.0,                     # wait up to 30s for write lock
        isolation_level=None,             # autocommit; we use BEGIN/COMMIT explicitly
        check_same_thread=False,          # WAL allows it, but we still use _local
    )
    conn.row_factory = sqlite3.Row
    # Critical pragmas. Run on every connection because they're per-connection.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")  # safe + fast on WAL
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")  # ms; complements the timeout above
    _local.conn = conn
    return conn


def close():
    """Close this thread's connection. Optional — connections auto-close
    on thread exit, but tests/scripts can call this explicitly."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


@contextmanager
def transaction():
    """Wrap a write in BEGIN/COMMIT, rolling back on exception. Use for
    any multi-statement mutation. Reentrant: nested calls on the same
    thread (e.g. save_queue → queue_append) join the outer transaction
    instead of failing with 'cannot start a transaction within a transaction'."""
    conn = _connect()
    if getattr(_local, "in_txn", False):
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    _local.in_txn = True
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        _local.in_txn = False


# ─── Schema (idempotent) ────────────────────────────────────────────────────
SCHEMA = """
-- Per-image generation metadata. Primary key is (character, id) because the
-- id counter is per-character. The label column is the post-prefix part of
-- the PNG stem (e.g. "kantoku-witch" for "0042_kantoku-witch.png").
CREATE TABLE IF NOT EXISTS done (
    character      TEXT    NOT NULL,
    id             INTEGER NOT NULL,
    label          TEXT    NOT NULL,
    prompt         TEXT    NOT NULL DEFAULT '',
    negative       TEXT    NOT NULL DEFAULT '',
    seed           INTEGER,
    width          INTEGER,
    height         INTEGER,
    generated_at   TEXT,                                 -- 'YYYY-MM-DD HH:MM'
    output_path    TEXT,
    multi_girl     INTEGER NOT NULL DEFAULT 0,
    extra_json     TEXT,                                 -- engine-specific fields
    recovered_from TEXT,                                 -- 'original', 'scratch', 'claude', 'backups', 'stub'
    recovered_via  TEXT,                                 -- fuzzy-match marker, etc.
    recovered_note TEXT,
    PRIMARY KEY (character, id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_done_label ON done(character, label);
CREATE INDEX IF NOT EXISTS idx_done_gen_at ON done(character, generated_at DESC);

-- Pending generation queue. queue_pos is the ordering key (assigned at
-- enqueue time so insertion order is preserved across characters). Label
-- is unique per character so we can reorder/delete by label safely.
CREATE TABLE IF NOT EXISTS queue (
    queue_pos    INTEGER PRIMARY KEY AUTOINCREMENT,
    character    TEXT    NOT NULL,
    label        TEXT    NOT NULL,
    prompt       TEXT,
    negative     TEXT,
    seed         INTEGER,
    width        INTEGER,
    height       INTEGER,
    multi_girl   INTEGER NOT NULL DEFAULT 0,
    entry_json   TEXT    NOT NULL                        -- full entry, for engine
);
CREATE INDEX IF NOT EXISTS idx_queue_char ON queue(character, queue_pos);
CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_char_label ON queue(character, label);

-- User feedback (votes, comment) keyed by (character, stem). Stems are the
-- full PNG basename without extension, e.g. "0042_kantoku-witch".
CREATE TABLE IF NOT EXISTS feedback (
    character    TEXT NOT NULL,
    stem         TEXT NOT NULL,
    votes_json   TEXT NOT NULL DEFAULT '{}',             -- {"like": true, "love": false, ...}
    comment      TEXT NOT NULL DEFAULT '',
    first_voted  TEXT,
    last_updated TEXT,
    PRIMARY KEY (character, stem)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_feedback_updated ON feedback(character, last_updated DESC);

-- Upscale records — append-only history of every _2k generation.
CREATE TABLE IF NOT EXISTS upscale_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    character    TEXT NOT NULL,
    stem         TEXT NOT NULL,
    scale        REAL,
    model        TEXT,
    duration_s   REAL,
    ts           TEXT NOT NULL,
    extra_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_upscale_char ON upscale_log(character, ts DESC);

-- Project-wide audit log. Replaces activity.jsonl. Append-only in practice
-- but stored relationally so we can filter by event type / character
-- without scanning the whole file.
CREATE TABLE IF NOT EXISTS activity (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    event      TEXT NOT NULL,
    character  TEXT,
    fields_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity(ts DESC);
CREATE INDEX IF NOT EXISTS idx_activity_char ON activity(character, ts DESC);
CREATE INDEX IF NOT EXISTS idx_activity_event ON activity(event, ts DESC);

-- Per-character mutable counters and small state. last_id was previously
-- in last_id.txt. Add new columns here as we migrate other per-character
-- state out of files.
CREATE TABLE IF NOT EXISTS character_state (
    character    TEXT PRIMARY KEY,
    last_id      INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT
) WITHOUT ROWID;

-- Character configs (formerly characters/<name>/config.yaml). Stored as a
-- JSON blob because the schema is loose (character_tags, outfits dict,
-- negative_tags, character_lora path, trigger_word, etc.). Hand-editing
-- happens through the Characters page in the UI, not via vim.
CREATE TABLE IF NOT EXISTS character_config (
    character    TEXT PRIMARY KEY,
    config_json  TEXT NOT NULL,
    updated_at   TEXT
) WITHOUT ROWID;
"""


def init() -> None:
    """Create all tables and indexes if missing. Safe to call repeatedly."""
    conn = _connect()
    conn.executescript(SCHEMA)


# ─── Snapshot/backup ────────────────────────────────────────────────────────
def snapshot(label: str | None = None) -> Path:
    """Take a hot backup of the DB using SQLite's online .backup API.
    Safe to call while the DB is being written. Returns the snapshot
    path. Keeps the 20 newest snapshots, evicts older ones."""
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"-{label}" if label else ""
    out = SNAPSHOTS_DIR / f"vrfu.{ts}{suffix}.db"
    src = _connect()
    dst = sqlite3.connect(out)
    try:
        src.backup(dst)
    finally:
        dst.close()
    # Prune to 20 newest
    snaps = sorted(SNAPSHOTS_DIR.glob("vrfu.*.db"))
    for old in snaps[:-20]:
        try: old.unlink()
        except OSError: pass
    return out


# ─── Row helpers ────────────────────────────────────────────────────────────
def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    # Inflate any *_json columns into Python objects for convenience.
    for k in list(d.keys()):
        if k.endswith("_json") and isinstance(d[k], str):
            try:
                d[k[:-5]] = json.loads(d[k])
            except (json.JSONDecodeError, ValueError):
                d[k[:-5]] = {}
    return d


def _rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [_row_to_dict(r) for r in rows]  # type: ignore[return-value]


# ════════════════════════════════════════════════════════════════════════════
# done — per-image generation metadata
# ════════════════════════════════════════════════════════════════════════════

DONE_COLS = (
    "character", "id", "label", "prompt", "negative", "seed", "width",
    "height", "generated_at", "output_path", "multi_girl",
    "extra_json", "recovered_from", "recovered_via", "recovered_note",
)
DONE_PRIMARY = {"character", "id", "label", "prompt", "negative", "seed",
                "width", "height", "generated_at", "output_path",
                "multi_girl", "recovered_from", "recovered_via",
                "recovered_note"}


def done_upsert(entry: dict) -> None:
    """Insert or replace a single done row. `entry` is a dict with the
    columns named above; any extra keys are folded into extra_json. The
    write is atomic — concurrent generators can't lose each other's
    entries (this is the bug that wiped 1,352 entries in May 2026)."""
    if "character" not in entry or "id" not in entry:
        raise ValueError("done_upsert requires 'character' and 'id'")
    row = {k: entry.get(k) for k in DONE_COLS}
    # Fold non-primary keys into extra_json so we don't lose engine-specific
    # fields the schema doesn't know about.
    extra = {k: v for k, v in entry.items() if k not in DONE_PRIMARY and k != "extra_json"}
    if extra:
        row["extra_json"] = json.dumps(extra, ensure_ascii=False)
    elif row.get("extra_json") is None:
        row["extra_json"] = None
    row["multi_girl"] = int(bool(row.get("multi_girl")))
    cols = ", ".join(DONE_COLS)
    qs = ", ".join("?" * len(DONE_COLS))
    _connect().execute(
        f"INSERT OR REPLACE INTO done ({cols}) VALUES ({qs})",
        tuple(row[k] for k in DONE_COLS),
    )


def done_upsert_many(entries: Iterable[dict]) -> int:
    """Bulk upsert under a single transaction. Returns count."""
    n = 0
    with transaction():
        for e in entries:
            done_upsert(e)
            n += 1
    return n


def done_get(character: str, id_: int) -> dict | None:
    row = _connect().execute(
        "SELECT * FROM done WHERE character = ? AND id = ?",
        (character, id_),
    ).fetchone()
    return _row_to_dict(row)


def done_by_label(character: str, label: str) -> dict | None:
    """Look up by label — most-recently-generated wins if there are
    multiple rows with the same label (older runs may have collided)."""
    row = _connect().execute(
        "SELECT * FROM done WHERE character = ? AND label = ? "
        "ORDER BY id DESC LIMIT 1",
        (character, label),
    ).fetchone()
    return _row_to_dict(row)


def done_list(character: str | None = None, limit: int | None = None,
              order_desc: bool = True) -> list[dict]:
    sql = "SELECT * FROM done"
    args: list = []
    if character is not None:
        sql += " WHERE character = ?"
        args.append(character)
    sql += " ORDER BY generated_at " + ("DESC" if order_desc else "ASC")
    sql += ", id " + ("DESC" if order_desc else "ASC")
    if limit:
        sql += " LIMIT ?"
        args.append(limit)
    return _rows_to_dicts(_connect().execute(sql, args).fetchall())


def done_max_id(character: str) -> int:
    row = _connect().execute(
        "SELECT COALESCE(MAX(id), 0) AS m FROM done WHERE character = ?",
        (character,),
    ).fetchone()
    return int(row["m"]) if row else 0


def done_label_map(character: str) -> dict[str, dict]:
    """{label -> latest entry} for a character. Replaces load_yaml_metadata."""
    rows = _connect().execute(
        "SELECT * FROM done WHERE character = ? ORDER BY id ASC",
        (character,),
    ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        d = _row_to_dict(r)
        if d:
            out[d["label"]] = d  # later rows overwrite earlier ones
    return out


# ════════════════════════════════════════════════════════════════════════════
# queue — pending generations
# ════════════════════════════════════════════════════════════════════════════

def queue_append(entries: Iterable[dict]) -> int:
    """Add entries to the end of the queue. Each must have at least
    `character` and `label`. Duplicate (character, label) entries are
    silently skipped — the unique index would raise otherwise."""
    n = 0
    with transaction():
        conn = _connect()
        for e in entries:
            if "character" not in e or "label" not in e:
                continue
            try:
                conn.execute(
                    "INSERT INTO queue (character, label, prompt, negative, "
                    "seed, width, height, multi_girl, entry_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        e["character"], e["label"], e.get("prompt"),
                        e.get("negative"), e.get("seed"), e.get("width"),
                        e.get("height"), int(bool(e.get("multi_girl"))),
                        json.dumps(e, ensure_ascii=False),
                    ),
                )
                n += 1
            except sqlite3.IntegrityError:
                # Duplicate label for this character — skip silently
                pass
    return n


def queue_list(character: str | None = None) -> list[dict]:
    """All queued entries, in queue order. Returns the full original
    entry (as posted) augmented with `queue_pos`."""
    sql = "SELECT queue_pos, entry_json FROM queue"
    args: list = []
    if character is not None:
        sql += " WHERE character = ?"
        args.append(character)
    sql += " ORDER BY queue_pos ASC"
    out = []
    for row in _connect().execute(sql, args).fetchall():
        try:
            entry = json.loads(row["entry_json"])
        except (json.JSONDecodeError, ValueError, TypeError):
            entry = {}
        entry["queue_pos"] = row["queue_pos"]
        out.append(entry)
    return out


def queue_delete_by_labels(character: str, labels: Iterable[str]) -> int:
    """Remove entries by (character, label). Used when a generation
    completes (one entry consumed) and when the user clears items in
    the UI. Atomic — concurrent calls can't double-delete."""
    labels = list(labels)
    if not labels:
        return 0
    placeholders = ",".join("?" * len(labels))
    cur = _connect().execute(
        f"DELETE FROM queue WHERE character = ? AND label IN ({placeholders})",
        (character, *labels),
    )
    return cur.rowcount


def queue_clear(character: str | None = None) -> int:
    sql = "DELETE FROM queue"
    args: tuple = ()
    if character is not None:
        sql += " WHERE character = ?"
        args = (character,)
    return _connect().execute(sql, args).rowcount


def queue_update(character: str, label: str, fields: dict) -> bool:
    """Update an existing entry's fields (and refresh entry_json)."""
    conn = _connect()
    row = conn.execute(
        "SELECT entry_json FROM queue WHERE character = ? AND label = ?",
        (character, label),
    ).fetchone()
    if row is None:
        return False
    try:
        entry = json.loads(row["entry_json"]) or {}
    except (json.JSONDecodeError, ValueError, TypeError):
        entry = {}
    entry.update(fields)
    conn.execute(
        "UPDATE queue SET prompt=?, negative=?, seed=?, width=?, height=?, "
        "multi_girl=?, entry_json=? WHERE character=? AND label=?",
        (
            entry.get("prompt"), entry.get("negative"), entry.get("seed"),
            entry.get("width"), entry.get("height"),
            int(bool(entry.get("multi_girl"))),
            json.dumps(entry, ensure_ascii=False),
            character, label,
        ),
    )
    return True


def queue_reorder(character: str, ordered_labels: list[str]) -> None:
    """Set the queue order for a character to match `ordered_labels`.
    Labels not in the list are pushed to the end in their existing order."""
    with transaction():
        conn = _connect()
        # Find the current max queue_pos so we can give the reordered ones
        # a fresh ascending range.
        max_pos = conn.execute(
            "SELECT COALESCE(MAX(queue_pos), 0) AS m FROM queue"
        ).fetchone()["m"]
        # Assign each label a new position in the ordered range.
        for i, lab in enumerate(ordered_labels):
            new_pos = max_pos + i + 1
            conn.execute(
                "UPDATE queue SET queue_pos=? WHERE character=? AND label=?",
                (new_pos, character, lab),
            )


def queue_size(character: str | None = None) -> int:
    sql = "SELECT COUNT(*) AS n FROM queue"
    args: tuple = ()
    if character is not None:
        sql += " WHERE character = ?"
        args = (character,)
    return int(_connect().execute(sql, args).fetchone()["n"])


# ════════════════════════════════════════════════════════════════════════════
# feedback — votes and comments
# ════════════════════════════════════════════════════════════════════════════

def feedback_get(character: str, stem: str) -> dict:
    row = _connect().execute(
        "SELECT * FROM feedback WHERE character = ? AND stem = ?",
        (character, stem),
    ).fetchone()
    if row is None:
        return {"votes": {}, "comment": ""}
    d = _row_to_dict(row)
    return {"votes": d.get("votes", {}), "comment": d["comment"],
            "first_voted": d["first_voted"], "last_updated": d["last_updated"]}


def feedback_set_vote(character: str, stem: str, vote_type: str,
                      value: bool) -> dict:
    """Set/clear a vote bit. Atomic upsert; concurrent voters on the
    same image serialize naturally via SQLite's write lock."""
    now = datetime.now().isoformat(timespec="seconds")
    with transaction():
        conn = _connect()
        row = conn.execute(
            "SELECT votes_json, first_voted FROM feedback "
            "WHERE character=? AND stem=?",
            (character, stem),
        ).fetchone()
        if row is None:
            votes = {}
            first_voted = now
        else:
            try:
                votes = json.loads(row["votes_json"]) or {}
            except (json.JSONDecodeError, ValueError, TypeError):
                votes = {}
            first_voted = row["first_voted"] or now
        votes[vote_type] = bool(value)
        conn.execute(
            "INSERT OR REPLACE INTO feedback "
            "(character, stem, votes_json, comment, first_voted, last_updated) "
            "VALUES (?, ?, ?, COALESCE((SELECT comment FROM feedback "
            "WHERE character=? AND stem=?), ''), ?, ?)",
            (character, stem, json.dumps(votes, ensure_ascii=False),
             character, stem, first_voted, now),
        )
    return {"votes": votes, "first_voted": first_voted, "last_updated": now}


def feedback_set_comment(character: str, stem: str, comment: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with transaction():
        conn = _connect()
        row = conn.execute(
            "SELECT first_voted FROM feedback WHERE character=? AND stem=?",
            (character, stem),
        ).fetchone()
        first_voted = (row["first_voted"] if row else None) or now
        conn.execute(
            "INSERT OR REPLACE INTO feedback "
            "(character, stem, votes_json, comment, first_voted, last_updated) "
            "VALUES (?, ?, COALESCE((SELECT votes_json FROM feedback "
            "WHERE character=? AND stem=?), '{}'), ?, ?, ?)",
            (character, stem, character, stem, comment, first_voted, now),
        )


def feedback_all(character: str | None = None) -> dict[str, dict[str, dict]]:
    """Return {character -> {stem -> feedback_dict}} — replaces the old
    load_feedback() shape so existing callers keep working."""
    sql = "SELECT * FROM feedback"
    args: tuple = ()
    if character is not None:
        sql += " WHERE character = ?"
        args = (character,)
    out: dict[str, dict[str, dict]] = {}
    for row in _connect().execute(sql, args).fetchall():
        d = _row_to_dict(row)
        if d is None:
            continue
        out.setdefault(d["character"], {})[d["stem"]] = {
            "votes": d.get("votes", {}),
            "comment": d["comment"],
            "first_voted": d["first_voted"],
            "last_updated": d["last_updated"],
        }
    return out


# ════════════════════════════════════════════════════════════════════════════
# upscale_log
# ════════════════════════════════════════════════════════════════════════════

def upscale_log_insert(character: str, stem: str, scale: float | None = None,
                       model: str | None = None,
                       duration_s: float | None = None,
                       **extra) -> None:
    extra_json = json.dumps(extra, ensure_ascii=False) if extra else None
    _connect().execute(
        "INSERT INTO upscale_log (character, stem, scale, model, "
        "duration_s, ts, extra_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (character, stem, scale, model, duration_s,
         datetime.now().isoformat(timespec="seconds"), extra_json),
    )


def upscale_log_list(character: str | None = None,
                     limit: int = 1000) -> list[dict]:
    sql = "SELECT * FROM upscale_log"
    args: list = []
    if character is not None:
        sql += " WHERE character = ?"
        args.append(character)
    sql += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    return _rows_to_dicts(_connect().execute(sql, args).fetchall())


# ════════════════════════════════════════════════════════════════════════════
# activity — audit log (replaces activity.jsonl)
# ════════════════════════════════════════════════════════════════════════════

def activity_log(event: str, character: str | None = None, **fields) -> None:
    _connect().execute(
        "INSERT INTO activity (ts, event, character, fields_json) "
        "VALUES (?, ?, ?, ?)",
        (datetime.now().isoformat(timespec="seconds"), event, character,
         json.dumps(fields, ensure_ascii=False) if fields else "{}"),
    )


def activity_list(character: str | None = None, event: str | None = None,
                  limit: int = 100) -> list[dict]:
    sql = "SELECT * FROM activity WHERE 1=1"
    args: list = []
    if character is not None:
        sql += " AND character = ?"
        args.append(character)
    if event is not None:
        sql += " AND event = ?"
        args.append(event)
    sql += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    out = []
    for row in _connect().execute(sql, args).fetchall():
        d = _row_to_dict(row)
        if d is None:
            continue
        # Flatten fields_json into the top-level dict (matches old jsonl shape)
        fields = d.pop("fields", {}) or {}
        d.update(fields)
        out.append(d)
    return out


# ════════════════════════════════════════════════════════════════════════════
# character_state — per-character counters
# ════════════════════════════════════════════════════════════════════════════

def character_state_get(character: str) -> dict:
    row = _connect().execute(
        "SELECT * FROM character_state WHERE character = ?",
        (character,),
    ).fetchone()
    if row is None:
        return {"character": character, "last_id": 0, "updated_at": None}
    return dict(row)


def character_state_bump_last_id(character: str, new_id: int) -> int:
    """Atomically advance last_id to max(current, new_id). Returns the
    new value. Concurrent generators racing to write the same id are
    rejected by the done table's PRIMARY KEY, so this counter is just
    a hint — but keeping it monotonic prevents id reuse on restart."""
    now = datetime.now().isoformat(timespec="seconds")
    with transaction():
        conn = _connect()
        row = conn.execute(
            "SELECT last_id FROM character_state WHERE character = ?",
            (character,),
        ).fetchone()
        cur = int(row["last_id"]) if row else 0
        new = max(cur, new_id)
        conn.execute(
            "INSERT OR REPLACE INTO character_state "
            "(character, last_id, updated_at) VALUES (?, ?, ?)",
            (character, new, now),
        )
    return new


def character_state_next_id(character: str) -> int:
    """Atomically reserve the next id for a generation. Looks at both
    the counter AND MAX(done.id) to defend against counter rewind."""
    now = datetime.now().isoformat(timespec="seconds")
    with transaction():
        conn = _connect()
        cur_row = conn.execute(
            "SELECT last_id FROM character_state WHERE character = ?",
            (character,),
        ).fetchone()
        cur = int(cur_row["last_id"]) if cur_row else 0
        max_row = conn.execute(
            "SELECT COALESCE(MAX(id), 0) AS m FROM done WHERE character = ?",
            (character,),
        ).fetchone()
        done_max = int(max_row["m"])
        next_id = max(cur, done_max) + 1
        conn.execute(
            "INSERT OR REPLACE INTO character_state "
            "(character, last_id, updated_at) VALUES (?, ?, ?)",
            (character, next_id, now),
        )
    return next_id


# ════════════════════════════════════════════════════════════════════════════
# character_config — formerly config.yaml
# ════════════════════════════════════════════════════════════════════════════

def character_config_get(character: str) -> dict | None:
    row = _connect().execute(
        "SELECT config_json FROM character_config WHERE character = ?",
        (character,),
    ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["config_json"])
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def character_config_set(character: str, config: dict) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    _connect().execute(
        "INSERT OR REPLACE INTO character_config "
        "(character, config_json, updated_at) VALUES (?, ?, ?)",
        (character, json.dumps(config, ensure_ascii=False, indent=2), now),
    )


def character_config_list() -> list[str]:
    """All characters with a config in the DB. Replaces list_characters()
    that walked the filesystem for config.yaml files."""
    rows = _connect().execute(
        "SELECT character FROM character_config ORDER BY character"
    ).fetchall()
    return [r["character"] for r in rows]
