"""
Shared utilities for the vrfu-ai.

Imported by every script under scripts/ and by web/server.py. Centralizes:
  - Project paths (so no script has hardcoded F:\\vrfu-ai\\... paths)
  - Character config loading
  - The append-only activity log
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import yaml

# ─── Project paths ──────────────────────────────────────────────────────────
# Computed from this file's location: scripts/_common.py is one level deep,
# so its parent.parent is the repo root. This means the project works wherever
# the user clones it — no env vars, no config edits.
#
# Worktree fix: if this file is being imported from inside `.claude/worktrees/<name>/`
# (Claude Code creates one of these when the user runs scripts in agent mode),
# the naive parent.parent points to the worktree, which doesn't have the heavy
# gitignored assets (checkpoints/, loras/, characters/<personal>/). Resolve to
# the real project root by trimming everything from `.claude/worktrees/<name>/`
# inward. Without this, diffusers.from_pretrained() gets a path that doesn't
# exist and falls back to interpreting it as a HuggingFace repo ID, which fails
# validation because Windows backslashes aren't valid in HF repo IDs.
def _resolve_root() -> Path:
    naive = Path(__file__).resolve().parent.parent
    parts = naive.parts
    for i, p in enumerate(parts):
        if p == ".claude" and i + 1 < len(parts) and parts[i + 1] == "worktrees":
            return Path(*parts[:i])
    return naive

ROOT        = _resolve_root()
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
    """All characters with a config in the DB. Replaces the old
    filesystem walk for `characters/*/config.yaml`. Names starting
    with '_' are excluded as project scaffolding (`_template`,
    `_demo_character`), except '_base' (the no-LoRA pseudo-character),
    which is a real selectable character.
    """
    # Lazy import to avoid circular dependency (store imports _common).
    import store  # scripts/ is on sys.path for all entry points
    # `_base` (the no-LoRA pseudo-character) is the only `_`-prefixed name that
    # is a real, selectable character; everything else starting with `_` is
    # scaffolding (`_template`, `_demo_character`) and stays hidden from the UI.
    names = [n for n in store.character_config_list()
             if n == "_base" or not n.startswith("_")]
    return sorted(names)


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
    """Read this character's config from the DB. Validates required fields.

    Path-valued fields (checkpoint, character_lora, extra_loras[].path) are
    resolved against ROOT so configs can use repo-relative paths and the
    project still works wherever the user clones it.
    """
    import store  # scripts/ is on sys.path for all entry points
    cfg = store.character_config_get(name)
    if cfg is None:
        raise FileNotFoundError(f"No config for character '{name}' in DB")

    required = ["trigger_word", "character_tags", "checkpoint", "character_lora"]
    missing = [k for k in required if k not in cfg]
    if missing:
        raise ValueError(f"config for '{name}' is missing: {missing}")

    # Resolve path-valued fields against ROOT. character_lora may be an
    # empty string for the no-LoRA pseudo-character ('_base') — leave it
    # empty so generate.py's load_character_lora() can skip the load.
    cfg["checkpoint"]     = _resolve_project_path(cfg["checkpoint"])
    if cfg["character_lora"]:
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


# ─── Data-safety primitives ─────────────────────────────────────────────────
# These exist because we lost 1352 done.yaml entries to a stale-snapshot race
# (May 2026). State now lives in SQLite (see scripts/store.py's header for the
# full rationale); these file primitives remain for the few non-DB files still
# written wholesale. Every such writer should go through `atomic_write_text`
# and every concurrent-mutation site should be protected by `file_lock` or
# `character_busy_lock`.
_activity_lock = threading.Lock()


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Atomic rewrite of `path`: write to `path.tmp.<pid>`, fsync, then
    `os.replace()` onto the final path. Readers never observe a partial
    file — they see either the previous version or the new one in full.

    Use this for any state file that's rewritten wholesale (feedback.json,
    done.yaml, queue.yaml, config.yaml, last_id.txt, etc.). Do NOT use for
    append-only files (use `append_jsonl` instead) or for very large files
    where the cost of an fsync per write matters (none in this project)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with open(tmp, "w", encoding=encoding, newline="") as f:
        f.write(text)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass  # not all filesystems support fsync (e.g. some network mounts)
    os.replace(tmp, path)


@contextmanager
def file_lock(lock_path: Path, timeout: float = 30.0, poll: float = 0.1):
    """Cross-process advisory lock on `lock_path` (NOT the file being
    protected — pass a sibling `.lock` path). msvcrt on Windows, fcntl on
    POSIX. Raises TimeoutError if the lock isn't acquired within `timeout`.

    The lock file is created if missing and kept open for the duration.
    Stale locks from crashed processes are reclaimed automatically because
    the OS releases file locks when a process dies."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "a+b")
    deadline = time.monotonic() + timeout
    try:
        if os.name == "nt":
            import msvcrt
            while True:
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"file_lock timeout on {lock_path}")
                    time.sleep(poll)
        else:
            import fcntl
            while True:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except (OSError, BlockingIOError):
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"file_lock timeout on {lock_path}")
                    time.sleep(poll)
        try:
            yield f
        finally:
            if os.name == "nt":
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    finally:
        f.close()


def append_jsonl(path: Path, record: dict) -> None:
    """Append one JSON record to `path` under a cross-process file lock.
    Each appended line is fsync'd so a crash mid-batch never loses
    already-acknowledged events. Lines are bounded short (~hundreds of
    bytes), so this is the safe pattern for high-frequency audit logs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with file_lock(path.with_suffix(path.suffix + ".lock"), timeout=10.0):
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass


def _pid_alive(pid: int) -> bool:
    """Cross-platform liveness check. Returns False for invalid PIDs and
    for processes that have exited; True if the process is currently
    running (even if owned by another user)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            exit_code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
            return bool(ok) and exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but is owned by another user


class CharacterBusy(RuntimeError):
    """Raised when a long-running tool tries to operate on a character that
    another live process is already mutating. Concurrent generate.py /
    upscale.py runs on the same character cause data loss (the 1352-entry
    done.yaml wipe of May 2026); refusing to start is the safe default."""


@contextmanager
def tool_busy_lock(tool: str, timeout: float = 0.0):
    """Project-wide mutual exclusion for a tool (generate, upscale, train).
    Only one process holding this lock at a time. Lock file at
    `<ROOT>/.<tool>.busy.lock`. PID-aware, so a crashed holder is
    reclaimed automatically.

    Use this where the offending race would be "two of the same tool
    running on overlapping data" (the GPU is shared; two generate.py
    processes will produce concurrent writes to the same per-character
    state). For finer-grained mutual exclusion (e.g., two tools on
    different characters), use `character_busy_lock` instead."""
    busy_path = ROOT / f".{tool}.busy.lock"

    deadline = time.monotonic() + timeout
    while True:
        if busy_path.exists():
            try:
                content = busy_path.read_text(encoding="utf-8").strip()
                pid_str, _, prev_tool = content.partition("|")
                prev_pid = int(pid_str)
            except (ValueError, OSError):
                prev_pid, prev_tool = 0, "?"
            if prev_pid and _pid_alive(prev_pid):
                if time.monotonic() > deadline:
                    raise CharacterBusy(
                        f"Tool '{tool}' is already running (PID {prev_pid}). "
                        f"Refusing to start a second copy — concurrent "
                        f"writers cause data loss."
                    )
                time.sleep(0.2)
                continue
            print(f"[tool_busy_lock] reclaiming stale lock from PID "
                  f"{prev_pid} ({prev_tool}) on tool '{tool}'", flush=True)
        atomic_write_text(busy_path, f"{os.getpid()}|{tool}\n")
        break

    try:
        yield
    finally:
        try:
            if busy_path.exists():
                content = busy_path.read_text(encoding="utf-8").strip()
                pid_str = content.partition("|")[0]
                if pid_str == str(os.getpid()):
                    busy_path.unlink()
        except OSError:
            pass


@contextmanager
def character_busy_lock(character: str, tool: str, timeout: float = 0.0):
    """Per-character mutual exclusion for long-running tools (generate,
    upscale, train). Writes the holder's PID+tool to `<char>/.busy.lock`
    so error messages can name the offender. PID-aware: a lock held by a
    dead process is reclaimed automatically (stale-lock cleanup).

    Raises `CharacterBusy` immediately if the lock is held by a LIVE PID
    and `timeout==0`. With `timeout>0`, polls for the lock to clear before
    giving up — useful when a kicked-off subprocess is winding down."""
    busy_path = char_dir(character) / ".busy.lock"
    busy_path.parent.mkdir(parents=True, exist_ok=True)

    deadline = time.monotonic() + timeout
    while True:
        if busy_path.exists():
            try:
                content = busy_path.read_text(encoding="utf-8").strip()
                pid_str, _, prev_tool = content.partition("|")
                prev_pid = int(pid_str)
            except (ValueError, OSError):
                prev_pid, prev_tool = 0, "?"
            if prev_pid and _pid_alive(prev_pid):
                if time.monotonic() > deadline:
                    raise CharacterBusy(
                        f"Character '{character}' is busy: '{prev_tool}' is "
                        f"running as PID {prev_pid}. Refusing to start '{tool}' — "
                        f"two writers on the same character cause data loss."
                    )
                time.sleep(0.2)
                continue
            # Stale lock — log and reclaim.
            print(f"[character_busy_lock] reclaiming stale lock from PID "
                  f"{prev_pid} ({prev_tool}) on {character}", flush=True)
        atomic_write_text(busy_path, f"{os.getpid()}|{tool}\n")
        break

    try:
        yield
    finally:
        try:
            # Only remove if we still own it (defense against the rare case
            # where a stale-lock reclaimer ran while we held it).
            if busy_path.exists():
                content = busy_path.read_text(encoding="utf-8").strip()
                pid_str = content.partition("|")[0]
                if pid_str == str(os.getpid()):
                    busy_path.unlink()
        except OSError:
            pass


def log_event(event: str, character: str | None = None, **fields) -> None:
    """Insert a row into the activity table. Cross-process safe via
    SQLite's WAL — any number of processes can log concurrently without
    interleaving or loss.

    Example:
        log_event("generated", character="tsu_chocola", label="kantoku-witch",
                  seed=12345, duration_s=71.2)
    """
    # The old API allowed callers to pass `character` as a kwarg without
    # treating it specially. The DB has it as a column; pull it out so it
    # gets stored in the indexed column rather than buried in fields_json.
    if character is None and "character" in fields:
        character = fields.pop("character")
    import store  # scripts/ is on sys.path for all entry points
    store.activity_log(event, character=character, **fields)


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
