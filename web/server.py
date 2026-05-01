"""
vrfu-ai — local web UI server.

Three pages:
  - Generation:  queue editor + start/stop a generation run
  - Review:      tabs for New / Liked / Archive, voting + Organize + Upscale
  - Activity:    tail of activity.jsonl

Runs at http://localhost:8765.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

# Pull shared paths + activity logger from scripts/
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import _common as C  # noqa: E402

PORT      = 8765
HERE      = Path(__file__).parent
DATA_DIR  = HERE / "data"
FEEDBACK  = DATA_DIR / "feedback.json"
BATCHES   = DATA_DIR / "batches.json"

# Path to the venv interpreter that has torch + diffusers installed.
# setup.bat builds this venv inside ai-toolkit/. Repo-relative so the
# project works wherever it's cloned.
VENV_PYTHON = C.ROOT / "ai-toolkit" / "venv" / "Scripts" / "python.exe"

DATA_DIR.mkdir(exist_ok=True)
for f, default in [(FEEDBACK, {}), (BATCHES, {})]:
    if not f.exists():
        f.write_text(json.dumps(default), encoding="utf-8")

# ─── Locks / caches ─────────────────────────────────────────────────────────
_lock = threading.Lock()
_yaml_cache: dict      = {}   # character → label→entry
_yaml_cache_key: dict  = {}   # character → (done.yaml mtime, output dir mtime)


# ─── Feedback JSON ──────────────────────────────────────────────────────────
def load_feedback() -> dict:
    with _lock:
        return json.loads(FEEDBACK.read_text(encoding="utf-8"))


def save_feedback(data: dict) -> None:
    with _lock:
        FEEDBACK.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ─── YAML metadata ──────────────────────────────────────────────────────────
def _cache_key(character: str) -> tuple:
    """Cache key combines done.yaml mtime AND output dir mtime so new files invalidate."""
    done = C.done_file(character)
    out  = C.output_dir(character)
    return (
        done.stat().st_mtime if done.exists() else 0,
        out.stat().st_mtime  if out.exists()  else 0,
    )


def load_yaml_metadata(character: str) -> dict:
    """Load done.yaml; auto-reloads on any mtime change."""
    key = _cache_key(character)
    if _yaml_cache_key.get(character) == key and character in _yaml_cache:
        return _yaml_cache[character]

    done = C.done_file(character)
    raw = []
    if done.exists():
        with done.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or []
    by_label = {e["label"]: e for e in raw if isinstance(e, dict) and "label" in e}
    _yaml_cache[character]      = by_label
    _yaml_cache_key[character]  = key
    return by_label


def parse_artists(prompt: str) -> list[str]:
    """Extract artist:NAME tags. Handles parens (bara_(rism)) and spaces (mika pikazo)."""
    return [a.strip() for a in re.findall(
        r"artist:([a-z0-9_\s\-\.\(\)]+?)(?=,|$)", prompt or "", re.IGNORECASE)]


# Tags that always show up because they're identity / quality / framing —
# not actual content suggestions. Mirrors web/app.js NOISY_TAGS.
_POPULAR_TAG_NOISE = {
    "1girl", "1boy", "solo", "2girls", "multiple girls",
    "masterpiece", "best quality", "amazing quality", "very aesthetic", "aesthetic",
    "displeasing", "very displeasing", "worst aesthetic", "very awa",
    "absurdres", "highres", "lowres", "newest", "recent", "old", "oldest",
    "year 2024", "year 2023", "year 2022",
    "safe", "sensitive", "questionable", "nsfw", "explicit",
    "anime coloring", "anime screencap", "cel shading", "flat color", "2d", "3d",
    "looking at viewer", "looking away", "looking back", "looking up", "looking down",
    "from above", "from below", "from behind", "from side", "from front",
    "facing viewer", "three quarter view", "side view", "profile",
    "head out of frame", "very aesthetic, absurdres",
    "blush", "smile",  # too generic to be a useful suggestion
}


def _strip_emphasis(tag: str) -> str:
    """(foo:1.3) -> foo;  [foo] -> foo"""
    t = tag.strip()
    m = re.match(r"^\(\s*(.+?)\s*(?::[\d.]+)?\)$", t)
    if m:
        t = m.group(1).strip()
    m = re.match(r"^\[\s*(.+?)\s*\]$", t)
    if m:
        t = m.group(1).strip()
    return t


def compute_popular_tags(character: str, top_n: int = 14) -> list[dict]:
    """Tag-frequency analysis over liked images for a character.

    Walks characters/<name>/liked/, looks up each stem's prompt in done.yaml,
    splits the prompt into comma-separated tags, drops noise (identity tags,
    quality stack, framing, character_tags from config, outfit-bundle tags),
    and returns the top-N tags by frequency.

    Returns: [{"tag": "tatami", "count": 7}, ...]
    """
    liked_dir = C.char_dir(character) / "liked"
    if not liked_dir.exists():
        return []

    by_label = load_yaml_metadata(character)

    # Build per-character noise: trigger_word + character_tags + every outfit's tags
    cfg = {}
    try:
        cfg = C.load_character(character) or {}
    except Exception:
        pass
    char_noise = set(_POPULAR_TAG_NOISE)
    if cfg.get("trigger_word"):
        char_noise.add(cfg["trigger_word"].lower())
    for s in [cfg.get("character_tags", "")] + list((cfg.get("outfits") or {}).values()):
        if isinstance(s, str):
            for t in s.split(","):
                norm = _strip_emphasis(t).lower()
                if norm:
                    char_noise.add(norm)

    counts: dict[str, int] = {}
    for png in liked_dir.iterdir():
        if png.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            continue
        m = re.match(r"^(\d+)_(.+?)(?:_2k)?$", png.stem)
        if not m:
            continue
        label = m.group(2)
        prompt = (by_label.get(label, {}) or {}).get("prompt", "")
        if not prompt:
            continue
        for raw in prompt.split(","):
            t = _strip_emphasis(raw).lower()
            if not t or t.startswith("artist:"):
                continue
            if t in char_noise:
                continue
            # skip long descriptive phrases (>5 words) — not real tags
            if len(t.split()) > 5:
                continue
            counts[t] = counts.get(t, 0) + 1

    sorted_tags = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"tag": t, "count": c} for t, c in sorted_tags[:top_n]]


def parse_category(label: str) -> str:
    lower = label.lower()
    if "nsfw" in lower or "nude" in lower or "lewd" in lower or "spread" in lower:
        return "nsfw"
    if any(k in lower for k in ["foot", "feet", "soles", "toes"]):
        return "feet"
    if any(k in lower for k in ["bikini", "lingerie", "stocking"]):
        return "lewd-light"
    return "general"


def make_image_info(stem: str, png: Path, by_label: dict, location: str,
                    character: str | None = None) -> dict:
    m = re.match(r"^(\d+)_(.+)$", stem)
    label = m.group(2) if m else stem
    entry = by_label.get(label, {})
    prompt = entry.get("prompt", "")
    info = {
        "id":           entry.get("id"),
        "label":        label,
        "filename":     png.name,
        "prompt":       prompt,
        "negative":     entry.get("negative", ""),
        "seed":         entry.get("seed"),
        "generated_at": entry.get("generated_at", ""),
        "artists":      parse_artists(prompt),
        "category":     parse_category(label),
        "location":     location,
    }
    # Only SDXL hires-fix output (_2k.png) counts as "upscaled" for the UI.
    # RealESRGAN (_up.png) files are kept on disk as archive/fallback but
    # don't surface in the website (no badge, no thumbnail swap).
    if character:
        candidate = C.upscaled_dir(character) / f"{stem}_2k.png"
        if candidate.exists():
            info["upscaled_filename"] = f"{stem}_2k.png"
    return info


def load_images_for_view(character: str, view: str) -> dict:
    by_label = load_yaml_metadata(character)
    images: dict = {}

    if view == "output":
        dirs = [(C.output_dir(character), "output")]
    elif view == "liked":
        # Both "in queue for upscale" AND "already upscaled (originals in liked_archive)"
        # show as Liked — the user thinks of them as the same set.
        dirs = [
            (C.liked_dir(character),         "liked"),
            (C.liked_archive_dir(character), "liked"),
        ]
    elif view == "archive":
        archive = C.archive_dir(character)
        dirs = []
        if archive.exists():
            for d in sorted(archive.iterdir()):
                if d.is_dir():
                    dirs.append((d, "archive"))
    elif view == "bookmarks":
        # Aggregate from every location — bookmarks live wherever the file physically is.
        # We'll filter by the bookmark vote afterwards.
        archive = C.archive_dir(character)
        dirs = [
            (C.output_dir(character),        "output"),
            (C.liked_dir(character),         "liked"),
            (C.liked_archive_dir(character), "liked"),
        ]
        if archive.exists():
            for d in sorted(archive.iterdir()):
                if d.is_dir():
                    dirs.append((d, "archive"))
    else:
        dirs = []

    for scan_dir, loc in dirs:
        if not scan_dir.exists():
            continue
        # Use glob *.png NOT rglob, so subfolders aren't doubly scanned
        for png in sorted(scan_dir.glob("*.png")):
            if png.stem in images:
                continue   # de-dupe across locations
            images[png.stem] = make_image_info(png.stem, png, by_label, loc, character=character)

    # For bookmarks view: filter to only images that have a bookmark vote
    if view == "bookmarks":
        feedback = load_feedback().get(character, {})
        images = {
            stem: info for stem, info in images.items()
            if feedback.get(stem, {}).get("votes", {}).get("bookmark")
        }
    return images


def load_all_images(character: str) -> dict:
    out = {}
    for v in ("output", "liked", "archive"):
        out.update(load_images_for_view(character, v))
    return out


# ─── File location / move ────────────────────────────────────────────────────
def locate_image_file(character: str, filename: str) -> Path | None:
    """Search every possible location for a PNG by filename (incl. _2k upscaled versions)."""
    for candidate in [
        C.output_dir(character) / filename,
        C.liked_dir(character) / filename,
        C.liked_archive_dir(character) / filename,
        C.upscaled_dir(character) / filename,
    ]:
        if candidate.exists():
            return candidate
    archive = C.archive_dir(character)
    if archive.exists():
        for f in archive.rglob(filename):
            return f
    return None


POSITIVE_KEYS = {"super_like", "love", "like", "style", "prompt", "pose", "outfit"}


def move_image(character: str, stem: str, target: str) -> bool:
    """Move stem.png to liked/ or archive/batch_<date>/. Returns True on success."""
    filename = f"{stem}.png"
    src = locate_image_file(character, filename)
    if src is None:
        return False
    char_dir = C.char_dir(character)
    src_top = src.relative_to(char_dir).parts[0]

    if target == "liked" and src_top == "liked":
        return False
    if target == "archive" and src_top == "archive":
        return False

    if target == "liked":
        dest_dir = C.liked_dir(character)
    elif target == "archive":
        # Use generated_at date for the batch name
        by_label = load_yaml_metadata(character)
        m = re.match(r"^(\d+)_(.+)$", stem)
        label = m.group(2) if m else stem
        ts = str(by_label.get(label, {}).get("generated_at", ""))
        try:
            dt = datetime.fromisoformat(ts.replace(" ", "T")) if ts else datetime.now()
            batch = f"batch_{dt.strftime('%Y-%m-%d')}"
        except Exception:
            batch = f"batch_{datetime.now().strftime('%Y-%m-%d')}"
        dest_dir = C.archive_dir(character) / batch
    else:
        return False

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    if dest == src:
        return False
    if dest.exists():
        dest.unlink()
    try:
        shutil.move(str(src), str(dest))
        C.log_event("moved", character=character, stem=stem,
                    from_=src_top, to=target)
        return True
    except Exception as e:
        print(f"move_image error: {e}")
        return False


def organize_output(character: str) -> dict:
    """Move all output/ images to liked/ or archive/ based on votes.
    Optimized: loads metadata once, does raw shutil.move per file (no per-call cache reloads)."""
    output = C.output_dir(character)
    if not output.exists():
        return {"moved_liked": 0, "moved_archive": 0, "skipped": 0}

    feedback   = load_feedback().get(character, {})
    by_label   = load_yaml_metadata(character)         # ONE parse of done.yaml
    liked_dir  = C.liked_dir(character)
    archive_root = C.archive_dir(character)
    today_batch  = f"batch_{datetime.now().strftime('%Y-%m-%d')}"

    # Pre-build set of filenames already in archive (for de-dupe) — single dir walk
    existing_archive = set()
    if archive_root.exists():
        for p in archive_root.rglob("*.png"):
            existing_archive.add(p.name)

    # Cache target archive subfolders by date so we don't recompute per-file
    archive_subdir_cache: dict[str, Path] = {}
    def archive_dest_for(stem: str) -> Path:
        m = re.match(r"^(\d+)_(.+)$", stem)
        label = m.group(2) if m else stem
        ts = str(by_label.get(label, {}).get("generated_at", ""))
        try:
            dt = datetime.fromisoformat(ts.replace(" ", "T")) if ts else None
            batch = f"batch_{dt.strftime('%Y-%m-%d')}" if dt else today_batch
        except Exception:
            batch = today_batch
        if batch not in archive_subdir_cache:
            d = archive_root / batch
            d.mkdir(parents=True, exist_ok=True)
            archive_subdir_cache[batch] = d
        return archive_subdir_cache[batch]

    liked_dir.mkdir(parents=True, exist_ok=True)

    pngs = list(output.glob("*.png"))
    moved_liked = moved_archive = skipped = 0

    for png in pngs:
        stem  = png.stem
        votes = feedback.get(stem, {}).get("votes", {})
        is_positive = any(votes.get(k) for k in POSITIVE_KEYS)
        is_disliked = votes.get("dislike")

        if is_positive and not is_disliked:
            dest = liked_dir / png.name
            try:
                if dest.exists(): dest.unlink()
                shutil.move(str(png), str(dest))
                moved_liked += 1
            except Exception as e:
                print(f"organize move-to-liked error: {e}")
                skipped += 1
        else:
            # If archive already has this filename, just delete from output/
            if png.name in existing_archive:
                try:
                    png.unlink()
                    skipped += 1
                    continue
                except Exception:
                    pass
            dest = archive_dest_for(stem) / png.name
            try:
                if dest.exists(): dest.unlink()
                shutil.move(str(png), str(dest))
                existing_archive.add(png.name)
                moved_archive += 1
            except Exception as e:
                print(f"organize move-to-archive error: {e}")
                skipped += 1

    # Invalidate cache so subsequent reads see the updated state
    _yaml_cache_key.pop(character, None)
    C.log_event("organize_clicked", character=character,
                moved_liked=moved_liked, moved_archive=moved_archive, skipped=skipped)
    return {"moved_liked": moved_liked, "moved_archive": moved_archive, "skipped": skipped}


# ─── Batch detection (output view only) ─────────────────────────────────────
def assign_batches(character: str) -> dict:
    images = load_images_for_view(character, "output")
    times = []
    for stem, info in images.items():
        ts = str(info.get("generated_at", ""))
        try:
            dt = datetime.fromisoformat(ts.replace(" ", "T")) if ts else None
        except Exception:
            dt = None
        times.append((stem, dt))
    times.sort(key=lambda x: x[1] or datetime.min)

    batches: dict = {}
    current = None
    last = None
    for stem, dt in times:
        if dt is None:
            continue
        if last is None or (dt - last).total_seconds() > 7200:
            current = dt.strftime("%Y-%m-%d_%H%M")
            batches[current] = {"start": dt.isoformat(), "end": dt.isoformat(),
                                "count": 0, "stems": []}
        batches[current]["end"] = dt.isoformat()
        batches[current]["count"] += 1
        batches[current]["stems"].append(stem)
        last = dt
    return batches


# ─── Stats ───────────────────────────────────────────────────────────────────
def aggregate_stats(character: str) -> dict:
    feedback   = load_feedback().get(character, {})
    all_images = load_all_images(character)

    counters = {
        "total": len(all_images), "voted": 0,
        "super_liked": 0, "loved": 0, "liked": 0, "disliked": 0,
        "style": 0, "prompt": 0, "pose": 0, "outfit": 0,
        "anatomy_issue": 0, "with_comment": 0,
    }
    artist_score: dict   = {}
    artist_issue: dict   = {}
    category_score: dict = {}

    for stem, fb in feedback.items():
        info = all_images.get(stem)
        if not info: continue
        votes = fb.get("votes", {})
        counters["voted"] += 1 if any(votes.values()) else 0
        for key in ["super_liked", "loved", "liked", "disliked", "style", "prompt", "pose", "outfit", "anatomy_issue"]:
            short = (key.replace("super_liked", "super_like")
                       .replace("loved", "love")
                       .replace("liked", "like")
                       .replace("disliked", "dislike"))
            if votes.get(short):
                counters[key] += 1
        if fb.get("comment", "").strip():
            counters["with_comment"] += 1
        # Per-image artist score: super_like + love + like + style contribute independently.
        # 💜 super_like is the strongest signal — top tier.
        img_score = 0
        if votes.get("super_like"): img_score += 3
        if votes.get("love"):       img_score += 2
        if votes.get("like"):       img_score += 1
        if votes.get("style"):      img_score += 1
        if img_score > 0:
            for a in info["artists"]:
                artist_score[a] = artist_score.get(a, 0) + img_score
        if votes.get("anatomy_issue") or votes.get("dislike"):
            for a in info["artists"]:
                artist_issue[a] = artist_issue.get(a, 0) + 1
        if votes.get("love") or votes.get("like"):
            cat = info["category"]
            category_score[cat] = category_score.get(cat, 0) + 1

    def top(d, n=5):
        return sorted(d.items(), key=lambda kv: -kv[1])[:n]
    return {
        "counts": counters,
        "top_artists":       top(artist_score, 8),
        "top_categories":    top(category_score, 6),
        "top_issue_artists": top(artist_issue, 5),
    }


# ─── Queue management ────────────────────────────────────────────────────────
QUEUE_HEADER = """# PROMPT QUEUE
# Add prompts below. Top entry runs first. Completed entries move to archive/done.yaml.
# See docs/DATA_FORMATS.md for full field reference.
"""


def load_queue(character: str) -> list[dict]:
    p = C.queue_file(character)
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    return [e for e in raw if isinstance(e, dict)]


def save_queue(character: str, entries: list[dict]) -> None:
    p = C.queue_file(character)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        f.write(QUEUE_HEADER)
        if entries:
            yaml.dump(entries, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def make_unique_label(base: str, existing: set) -> str:
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


# ─── Run control (subprocess management) ─────────────────────────────────────
# Map: character -> True if a generation should auto-start when upscale finishes successfully
_chain_after_upscale: dict[str, bool] = {}
# Map: character -> True if a generation should auto-start when training finishes successfully
_chain_after_training: dict[str, bool] = {}

_run_state = {
    "state":         "idle",       # idle | running | completed | error
    "character":     None,
    "pid":           None,
    "started_at":    None,
    "log_path":      None,
    "current_index": 0,
    "total":         0,
    "current_label": "",
    "last_dur_s":    0.0,
    "completed":     0,
    "exit_code":     None,
}
_run_lock = threading.Lock()
_run_proc: subprocess.Popen | None = None


def _watch_run(proc: subprocess.Popen, log_path: Path) -> None:
    """Poll the run log and update _run_state in place."""
    global _run_proc
    pat_progress = re.compile(r"PROGRESS:\s*(\d+)/(\d+)\s+label=(\S+)\s+seed=(\S+)\s+dur=([\d.]+)")
    pat_total    = re.compile(r"BATCH_START\s+total=(\d+)")
    pat_end      = re.compile(r"BATCH_END")
    last_size = 0
    while proc.poll() is None:
        try:
            if log_path.exists():
                with log_path.open("r", encoding="utf-8", errors="ignore") as f:
                    f.seek(last_size)
                    chunk = f.read()
                    last_size = f.tell()
                for line in chunk.splitlines():
                    m = pat_total.search(line)
                    if m:
                        with _run_lock:
                            _run_state["total"] = int(m.group(1))
                    m = pat_progress.search(line)
                    if m:
                        with _run_lock:
                            _run_state["current_index"] = int(m.group(1))
                            _run_state["total"]         = int(m.group(2))
                            _run_state["current_label"] = m.group(3)
                            _run_state["last_dur_s"]    = float(m.group(5))
                            _run_state["completed"]     = int(m.group(1))
        except Exception:
            pass
        time.sleep(0.7)

    # Process exited
    code = proc.returncode
    with _run_lock:
        _run_state["state"]     = "completed" if code == 0 else "error"
        _run_state["exit_code"] = code
        _run_proc_local = _run_proc
    _run_proc = None


def run_start(character: str) -> dict:
    """Spawn `python scripts/generate.py --character <name>` as a subprocess."""
    global _run_proc
    if _run_proc is not None and _run_proc.poll() is None:
        return {"ok": False, "err": "A run is already in progress."}
    # Mutual exclusion with upscaler + training — they all share the GPU
    upscale_proc = _tool_procs.get("upscale")
    if upscale_proc and upscale_proc.poll() is None:
        return {"ok": False, "err": "Upscaler is running. Stop it first (GPU is shared)."}
    training_proc = _tool_procs.get("training")
    if training_proc and training_proc.poll() is None:
        return {"ok": False, "err": "Training is running. Stop it first (GPU is shared)."}

    logs = C.logs_dir(character)
    logs.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs / f"run_{ts}.txt"

    venv_python = VENV_PYTHON
    cmd = [str(venv_python), str(C.SCRIPTS / "generate.py"), "--character", character]

    log_f = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd, stdout=log_f, stderr=subprocess.STDOUT,
        cwd=str(C.SCRIPTS),
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    _run_proc = proc

    with _run_lock:
        _run_state.update({
            "state":         "running",
            "character":     character,
            "pid":           proc.pid,
            "started_at":    datetime.now().isoformat(timespec="seconds"),
            "log_path":      str(log_path),
            "current_index": 0,
            "total":         0,
            "current_label": "",
            "last_dur_s":    0.0,
            "completed":     0,
            "exit_code":     None,
        })

    threading.Thread(target=_watch_run, args=(proc, log_path), daemon=True).start()
    return {"ok": True, "pid": proc.pid, "log_path": str(log_path)}


def run_stop() -> dict:
    """Send terminate to the running generate.py."""
    global _run_proc
    if _run_proc is None or _run_proc.poll() is not None:
        return {"ok": False, "err": "No run in progress."}
    pid = _run_proc.pid
    try:
        # Windows: taskkill the process tree
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                           capture_output=True, timeout=10)
        else:
            _run_proc.send_signal(signal.SIGTERM)
        with _run_lock:
            _run_state["state"] = "completed"
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "err": str(e)}


def tail_log(character: str, n: int = 50) -> str:
    log = _run_state.get("log_path")
    if log and Path(log).exists():
        with Path(log).open("r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    return ""


def latest_image(character: str) -> str | None:
    out = C.output_dir(character)
    if not out.exists():
        return None
    pngs = list(out.glob("*.png"))
    if not pngs:
        return None
    pngs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return pngs[0].name


# ─── Background-tool spawner (upscale, build-reference) ──────────────────────
_tool_state: dict = {}                      # tool_name → status dict
_tool_procs: dict[str, subprocess.Popen] = {}
_tool_lock = threading.Lock()


def _watch_tool(tool_name: str, proc: subprocess.Popen, log_path: Path) -> None:
    """Tail the log: parse PROGRESS / BATCH_START lines into _tool_state. Detect exit."""
    # upscale.py emits:  "PROGRESS: N/M label=foo dur=1.23"
    pat_progress = re.compile(r"PROGRESS:\s*(\d+)/(\d+)\s+label=(\S+)(?:\s+\S+)*\s+dur=([\d.]+)")
    # train.py emits:    "PROGRESS: N/M step=N loss=X"  (no label=/dur=)
    pat_train    = re.compile(r"PROGRESS:\s*(\d+)/(\d+)\s+step=(\d+)\s+loss=([0-9.eE+-]*)")
    pat_total    = re.compile(r"BATCH_START\s+total=(\d+)")
    last_size = 0
    last_step_ts: float | None = None
    while proc.poll() is None:
        try:
            if log_path.exists():
                with log_path.open("r", encoding="utf-8", errors="ignore") as f:
                    f.seek(last_size)
                    chunk = f.read()
                    last_size = f.tell()
                for line in chunk.splitlines():
                    m = pat_total.search(line)
                    if m:
                        with _tool_lock:
                            _tool_state[tool_name]["total"] = int(m.group(1))
                    m = pat_progress.search(line)
                    if m:
                        with _tool_lock:
                            _tool_state[tool_name]["current_index"] = int(m.group(1))
                            _tool_state[tool_name]["total"]         = int(m.group(2))
                            _tool_state[tool_name]["current_label"] = m.group(3)
                            _tool_state[tool_name]["last_dur_s"]    = float(m.group(4))
                        continue
                    m = pat_train.search(line)
                    if m:
                        now = time.monotonic()
                        # Estimate per-step duration from wall-clock between PROGRESS lines
                        dur = (now - last_step_ts) if last_step_ts is not None else 0.0
                        last_step_ts = now
                        loss = m.group(4) or "?"
                        with _tool_lock:
                            _tool_state[tool_name]["current_index"] = int(m.group(1))
                            _tool_state[tool_name]["total"]         = int(m.group(2))
                            _tool_state[tool_name]["current_label"] = f"step {m.group(3)} (loss {loss})"
                            if dur > 0:
                                _tool_state[tool_name]["last_dur_s"] = dur
        except Exception:
            pass
        time.sleep(0.7)
    # Process exited
    with _tool_lock:
        _tool_state[tool_name]["state"]     = "completed" if proc.returncode == 0 else "error"
        _tool_state[tool_name]["exit_code"] = proc.returncode
        _tool_procs.pop(tool_name, None)
        chain_char = None
        chain_after = None
        if proc.returncode == 0 and tool_name == "upscale":
            char = _tool_state[tool_name].get("character")
            if char and _chain_after_upscale.pop(char, False):
                chain_char, chain_after = char, "upscale"
        elif proc.returncode == 0 and tool_name == "training":
            char = _tool_state[tool_name].get("character")
            if char and _chain_after_training.pop(char, False):
                chain_char, chain_after = char, "training"
    # Outside the lock, kick off the chained generation
    if chain_char:
        print(f"[chain] {chain_after} finished — auto-starting generation for {chain_char}")
        time.sleep(5)   # let GPU settle / VRAM clear
        try:
            run_start(chain_char)
            C.log_event("chain_run_started", character=chain_char, after=chain_after)
        except Exception as e:
            print(f"[chain] failed to start gen: {e}")


def spawn_tool(tool_name: str, character: str, script_name: str,
               extra_args: list[str] | None = None) -> dict:
    """Spawn `python scripts/<script_name> --character <name>` as a subprocess.

    extra_args: forwarded to the subprocess (e.g. ['--scale', '1.5']).
    """
    with _tool_lock:
        existing = _tool_state.get(tool_name)
        if existing and existing.get("state") == "running":
            return {"ok": False, "err": f"{tool_name} already running"}

        # Upscaler / training share the GPU with generation — refuse if a gen run is in progress
        if tool_name in ("upscale", "training") and _run_proc and _run_proc.poll() is None:
            return {"ok": False, "err": "Generation run in progress. Stop it first (GPU is shared)."}
        # And training/upscaler can't co-exist either
        if tool_name == "training":
            up = _tool_procs.get("upscale")
            if up and up.poll() is None:
                return {"ok": False, "err": "Upscaler is running. Stop it first (GPU is shared)."}
        if tool_name == "upscale":
            tr = _tool_procs.get("training")
            if tr and tr.poll() is None:
                return {"ok": False, "err": "Training is running. Stop it first (GPU is shared)."}

        logs = C.logs_dir(character)
        logs.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = logs / f"{tool_name}_{ts}.txt"

        venv_python = VENV_PYTHON
        cmd = [str(venv_python), str(C.SCRIPTS / script_name), "--character", character]
        if extra_args:
            cmd.extend(extra_args)
        log_f = log_path.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd, stdout=log_f, stderr=subprocess.STDOUT,
            cwd=str(C.SCRIPTS),
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        _tool_procs[tool_name] = proc
        _tool_state[tool_name] = {
            "state":         "running",
            "character":     character,
            "started_at":    datetime.now().isoformat(timespec="seconds"),
            "log_path":      str(log_path),
            "pid":           proc.pid,
            "current_index": 0,
            "total":         0,
            "current_label": "",
            "last_dur_s":    0.0,
            "exit_code":     None,
        }

    threading.Thread(target=_watch_tool, args=(tool_name, proc, log_path), daemon=True).start()
    return {"ok": True, "log_path": str(log_path)}


def spawn_upscale_single(character: str, src_path: str, stem: str,
                         scale: float | None = None) -> dict:
    """Spawn upscale.py for ONE arbitrary image using --src-file mode."""
    with _tool_lock:
        if _tool_state.get("upscale", {}).get("state") == "running":
            return {"ok": False, "err": "upscale tool already running"}
        logs = C.logs_dir(character)
        logs.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = logs / f"upscale_one_{ts}.txt"
        venv_python = VENV_PYTHON
        cmd = [
            str(venv_python), str(C.SCRIPTS / "upscale.py"),
            "--character", character,
            "--src-file", src_path,
            "--stem-as", stem,
        ]
        if scale and scale > 0:
            cmd.extend(["--scale", str(float(scale))])
        log_f = log_path.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd, stdout=log_f, stderr=subprocess.STDOUT,
            cwd=str(C.SCRIPTS),
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        _tool_procs["upscale"] = proc
        _tool_state["upscale"] = {
            "state":         "running",
            "character":     character,
            "started_at":    datetime.now().isoformat(timespec="seconds"),
            "log_path":      str(log_path),
            "pid":           proc.pid,
            "current_index": 0,
            "total":         1,
            "current_label": stem,
            "last_dur_s":    0.0,
            "exit_code":     None,
            "single":        True,
        }

    threading.Thread(target=_watch_tool, args=("upscale", proc, log_path), daemon=True).start()
    return {"ok": True, "log_path": str(log_path), "stem": stem}


def stop_tool(tool_name: str) -> dict:
    """Terminate a running background tool subprocess."""
    proc = _tool_procs.get(tool_name)
    if proc is None or proc.poll() is not None:
        return {"ok": False, "err": "no running tool"}
    pid = proc.pid
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                           capture_output=True, timeout=10)
        else:
            proc.send_signal(signal.SIGTERM)
        with _tool_lock:
            _tool_state[tool_name]["state"] = "completed"
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "err": str(e)}


def tail_tool_log(tool_name: str, n: int = 30) -> str:
    state = _tool_state.get(tool_name, {})
    log = state.get("log_path")
    if log and Path(log).exists():
        with Path(log).open("r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    return ""


# ─── HTTP handler ────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    # Endpoints the frontend polls every couple seconds. Logging them spams
    # the cmd window so badly that real requests (page loads, button clicks,
    # errors) get drowned out. Suppress them — everything else still logs.
    _QUIET_PATH_PREFIXES = (
        "/api/run/status",
        "/api/run/log",
        "/api/tool/status",
    )

    def log_message(self, fmt, *args):
        path = self.path
        if any(path.startswith(p) for p in self._QUIET_PATH_PREFIXES):
            return
        if "/api/" in path or path == "/":
            sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] {self.command} {path}\n")

    # ── helpers ──────────────────────────────────────────────────────────────
    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str | None = None):
        if not path.exists():
            self.send_error(404, f"Not found: {path.name}")
            return
        if content_type is None:
            ext = path.suffix.lower()
            content_type = {
                ".html": "text/html; charset=utf-8",
                ".js":   "application/javascript; charset=utf-8",
                ".css":  "text/css; charset=utf-8",
                ".png":  "image/png",
                ".jpg":  "image/jpeg",
                ".jpeg": "image/jpeg",
                ".json": "application/json",
                ".yaml": "text/yaml; charset=utf-8",
                ".yml":  "text/yaml; charset=utf-8",
                ".txt":  "text/plain; charset=utf-8",
            }.get(ext, "application/octet-stream")
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=3600" if path.suffix in (".png", ".jpg", ".jpeg") else "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        if n == 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    # ── GET ──────────────────────────────────────────────────────────────────
    def do_GET(self):
        url   = urllib.parse.urlparse(self.path)
        path  = url.path
        qs    = urllib.parse.parse_qs(url.query)
        char  = qs.get("character", [""])[0] or None

        # Static
        if path in ("/", "/index.html"):
            return self._send_file(HERE / "index.html")
        if path in ("/style.css", "/app.js"):
            return self._send_file(HERE / path.lstrip("/"))

        # ── Characters ──────────────────────────────────────────────────────
        if path == "/api/characters":
            return self._send_json({"characters": C.list_characters()})

        if path == "/api/character-info":
            character = char or (C.list_characters() or ["tsu_chocola"])[0]
            try:
                cfg = C.load_character(character)
                return self._send_json({
                    "character_name": cfg.get("character_name", character),
                    "trigger_word":   cfg.get("trigger_word", ""),
                    "character_tags": cfg.get("character_tags", ""),
                    "checkpoint":     Path(cfg.get("checkpoint", "")).name,
                    "character_lora": Path(cfg.get("character_lora", "")).name,
                    "lora_weight":    cfg.get("character_lora_weight", 0.85),
                    "extra_loras":    [{"name": e.get("name", Path(e.get("path","")).stem),
                                        "weight": e.get("weight", 0.5)}
                                       for e in (cfg.get("extra_loras") or [])],
                    "outfits":        cfg.get("outfits") or {},
                    "popular_tags":   compute_popular_tags(character),
                    "training_dir":   str(C.char_dir(character) / "training"),
                    "base_positive":  "masterpiece, best quality, amazing quality, very aesthetic, newest, absurdres, anime coloring, cel shading",
                })
            except Exception as e:
                return self._send_json({"err": str(e)}, 500)

        if path == "/api/refresh":
            _yaml_cache.clear()
            _yaml_cache_key.clear()
            return self._send_json({"ok": True})

        # ── Images / artists / batches / stats ──────────────────────────────
        if path == "/api/images":
            character = char or (C.list_characters() or ["tsu_chocola"])[0]
            view      = qs.get("view", ["output"])[0]
            page      = int(qs.get("page", ["1"])[0])
            per_page  = int(qs.get("per_page", ["50"])[0])
            filt      = qs.get("filter", ["all"])[0]
            batch     = qs.get("batch", ["all"])[0]
            artist    = qs.get("artist", ["all"])[0]
            search_q  = qs.get("q", [""])[0].strip().lower()

            meta     = load_images_for_view(character, view)
            feedback = load_feedback().get(character, {})
            stems    = list(meta.keys())

            if view == "output" and batch != "all":
                bs = assign_batches(character)
                if batch == "latest" and bs:
                    stems = bs[max(bs.keys())]["stems"]
                elif batch in bs:
                    stems = bs[batch]["stems"]
                stems = [s for s in stems if s in meta]

            def matches(stem):
                fb    = feedback.get(stem, {})
                votes = fb.get("votes", {})
                if filt == "all":          return True
                if filt == "unvoted":      return not any(votes.values()) and not fb.get("comment", "").strip()
                if filt == "super_liked":  return votes.get("super_like")
                if filt == "loved":        return votes.get("love")
                if filt == "liked":        return votes.get("like")
                if filt == "bookmark":     return votes.get("bookmark")
                if filt == "style":        return votes.get("style")
                if filt == "prompt":       return votes.get("prompt")
                if filt == "pose":         return votes.get("pose")
                if filt == "outfit":       return votes.get("outfit")
                if filt == "anatomy":      return votes.get("anatomy_issue")
                if filt == "disliked":     return votes.get("dislike")
                if filt == "comment":      return bool(fb.get("comment", "").strip())
                if filt == "any-positive": return any(votes.get(k) for k in POSITIVE_KEYS)
                return True

            stems = [s for s in stems if matches(s)]

            if artist != "all":
                if artist == "no-artist":
                    stems = [s for s in stems if not meta[s].get("artists")]
                else:
                    al = artist.lower()
                    stems = [s for s in stems
                             if any(a.lower() == al for a in meta[s].get("artists", []))]

            # Free-text search across label, full prompt, and artist tags.
            # Multiple words = AND (each must match somewhere in the haystack).
            if search_q:
                terms = [t for t in search_q.split() if t]
                def hay(stem: str) -> str:
                    info = meta[stem]
                    return " ".join([
                        stem.lower(),
                        (info.get("label") or "").lower(),
                        (info.get("prompt") or "").lower(),
                        " ".join(info.get("artists") or []).lower(),
                        (feedback.get(stem, {}).get("comment") or "").lower(),
                    ])
                stems = [s for s in stems if all(t in hay(s) for t in terms)]

            # Newest first — higher id = generated more recently.
            # Items without an id (e.g. external imports) fall to the end.
            stems.sort(key=lambda s: meta[s].get("id") or 0, reverse=True)
            total = len(stems)
            page_stems = stems[(page - 1) * per_page: page * per_page]

            images = []
            for stem in page_stems:
                info = dict(meta[stem])
                fb   = feedback.get(stem, {})
                info["stem"]    = stem
                info["votes"]   = fb.get("votes", {})
                info["comment"] = fb.get("comment", "")
                images.append(info)

            return self._send_json({
                "images": images, "total": total,
                "page": page, "per_page": per_page,
                "pages": max(1, (total + per_page - 1) // per_page),
            })

        if path == "/api/artists":
            character = char or (C.list_characters() or ["tsu_chocola"])[0]
            view      = qs.get("view", ["output"])[0]
            meta      = load_images_for_view(character, view)
            counts: dict = {}
            no_artist = 0
            for info in meta.values():
                artists = info.get("artists", [])
                if not artists:
                    no_artist += 1
                for a in artists:
                    al = a.strip().lower()
                    if al:
                        counts[al] = counts.get(al, 0) + 1
            ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            return self._send_json({
                "artists":   [{"name": a, "count": n} for a, n in ranked],
                "no_artist": no_artist,
            })

        if path == "/api/stats":
            character = char or (C.list_characters() or ["tsu_chocola"])[0]
            return self._send_json(aggregate_stats(character))

        if path == "/api/batches":
            character = char or (C.list_characters() or ["tsu_chocola"])[0]
            bs = assign_batches(character)
            simple = {bid: {"start": b["start"], "end": b["end"], "count": b["count"]}
                      for bid, b in bs.items()}
            return self._send_json({"batches": simple})

        # ── Queue ───────────────────────────────────────────────────────────
        if path == "/api/queue":
            character = char or (C.list_characters() or ["tsu_chocola"])[0]
            return self._send_json({"queue": load_queue(character)})

        if path == "/api/queue/export":
            character = char or (C.list_characters() or ["tsu_chocola"])[0]
            p = C.queue_file(character)
            self.send_response(200)
            self.send_header("Content-Type", "text/yaml; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="queue_{character}.yaml"')
            self.end_headers()
            self.wfile.write(p.read_bytes() if p.exists() else b"# empty\n")
            return

        # ── Run controls ────────────────────────────────────────────────────
        if path == "/api/run/status":
            with _run_lock:
                state = dict(_run_state)
            state["latest_image"] = latest_image(state["character"]) if state.get("character") else None
            char = char or state.get("character")
            state["chain_after_upscale"] = bool(_chain_after_upscale.get(char, False)) if char else False
            return self._send_json(state)

        if path == "/api/run/log":
            character = char or _run_state.get("character")
            n = int(qs.get("tail", ["80"])[0])
            return self._send_json({"log": tail_log(character, n) if character else ""})

        if path == "/api/run/latest-image":
            character = char or (C.list_characters() or ["tsu_chocola"])[0]
            return self._send_json({"filename": latest_image(character)})

        if path == "/api/tool/status":
            tool = qs.get("tool", [""])[0]
            with _tool_lock:
                state = dict(_tool_state.get(tool, {"state": "idle"}))
            state["log_tail"] = tail_tool_log(tool, 8) if tool else ""
            return self._send_json(state)

        # ── Activity log ────────────────────────────────────────────────────
        if path == "/api/activity":
            character = char
            limit     = int(qs.get("limit", ["100"])[0])
            event     = qs.get("event", [None])[0]
            return self._send_json({"events": C.read_activity(character, limit, event)})

        # ── Character thumbnail ─────────────────────────────────────────────
        if path == "/api/character/thumbnail":
            character = qs.get("character", [""])[0]
            if not character or character not in C.list_characters():
                return self._send_json({"ok": False, "err": "no character"}, 404)
            char_dir = C.char_dir(character)
            # Preference order: liked/* (the user's favorite), then liked_upscaled,
            # then output/* (most recent generation), then training/* (reference shot)
            for sub in ("liked", "liked_upscaled", "output", "training"):
                folder = char_dir / sub
                if not folder.exists():
                    continue
                imgs = sorted(
                    [p for p in folder.iterdir()
                     if p.suffix.lower() in (".png", ".jpg", ".jpeg")],
                    key=lambda p: -p.stat().st_mtime,
                )
                if imgs:
                    return self._send_file(imgs[0])
            return self._send_json({"ok": False, "err": "no images"}, 404)

        # ── Docs (markdown viewer) ──────────────────────────────────────────
        if path == "/api/docs":
            # List every .md in docs/ + the project README if present.
            docs_dir = C.DOCS
            entries = []
            for md in sorted(docs_dir.glob("*.md")):
                entries.append({"name": md.stem, "filename": md.name,
                                "size": md.stat().st_size})
            return self._send_json({"docs": entries})

        if path.startswith("/api/docs/"):
            # Serve the raw markdown content. Slug is the filename without
            # extension; reject anything with path-traversal characters.
            slug = path[len("/api/docs/"):]
            if not re.match(r"^[a-zA-Z0-9_\-]+$", slug):
                return self._send_json({"ok": False, "err": "bad slug"}, 400)
            md_path = C.DOCS / f"{slug}.md"
            if not md_path.is_file():
                return self._send_json({"ok": False, "err": "not found"}, 404)
            return self._send_json({
                "ok": True, "name": slug,
                "filename": md_path.name,
                "content": md_path.read_text(encoding="utf-8"),
            })

        # ── Image serving ───────────────────────────────────────────────────
        if path.startswith("/img/"):
            parts = path.lstrip("/").split("/", 2)
            if len(parts) == 3:
                _, character, filename = parts
                f = locate_image_file(character, urllib.parse.unquote(filename))
                if f and f.is_file():
                    return self._send_file(f)
            return self.send_error(404, "image not found")

        # Backward-compat
        if path.startswith("/output/"):
            parts = path.lstrip("/").split("/", 2)
            if len(parts) == 3:
                _, character, filename = parts
                f = C.output_dir(character) / urllib.parse.unquote(filename)
                if f.exists():
                    return self._send_file(f)
            return self.send_error(404, "image not found")

        return self.send_error(404, f"not found: {path}")

    # ── POST ─────────────────────────────────────────────────────────────────
    def do_POST(self):
        body = self._read_body()
        path = self.path

        if path == "/api/vote":
            character = body.get("character")
            stem      = body.get("stem")
            vote_type = body.get("vote_type")
            value     = bool(body.get("value"))
            view      = body.get("view", "output")

            if not character or not stem or vote_type not in (
                "love", "like", "dislike", "style", "prompt", "pose", "outfit",
                "anatomy_issue", "bookmark", "super_like",
            ):
                return self._send_json({"ok": False, "err": "bad request"}, 400)

            data = load_feedback()
            entry = data.setdefault(character, {}).setdefault(stem, {})
            entry.setdefault("votes", {})
            entry["votes"][vote_type] = value
            now = datetime.now().isoformat(timespec="seconds")
            entry.setdefault("first_voted", now)
            entry["last_updated"] = now
            save_feedback(data)
            C.log_event("voted", character=character, stem=stem,
                        vote_type=vote_type, value=value)

            moved = None
            # Bookmark votes never trigger movement — they're just a flag.
            if view in ("liked", "archive") and vote_type != "bookmark":
                all_votes   = entry["votes"]
                is_positive = any(all_votes.get(k) for k in POSITIVE_KEYS)
                is_disliked = all_votes.get("dislike")
                if view == "liked" and is_disliked:
                    if move_image(character, stem, "archive"):
                        moved = "archive"
                elif view == "archive" and is_positive and not is_disliked:
                    if move_image(character, stem, "liked"):
                        moved = "liked"
            return self._send_json({"ok": True, "moved": moved})

        if path == "/api/comment":
            character = body.get("character")
            stem      = body.get("stem")
            comment   = body.get("comment", "")
            if not character or not stem:
                return self._send_json({"ok": False, "err": "bad request"}, 400)
            data  = load_feedback()
            entry = data.setdefault(character, {}).setdefault(stem, {})
            entry["comment"]      = comment
            entry["last_updated"] = datetime.now().isoformat(timespec="seconds")
            save_feedback(data)
            if comment.strip():
                C.log_event("comment", character=character, stem=stem)
            return self._send_json({"ok": True})

        if path == "/api/organize":
            character = body.get("character")
            if not character:
                return self._send_json({"ok": False, "err": "missing character"}, 400)
            return self._send_json({"ok": True, **organize_output(character)})

        # ── Queue mutations ─────────────────────────────────────────────────
        if path == "/api/queue/add":
            character = body.get("character")
            if not character:
                return self._send_json({"ok": False, "err": "missing character"}, 400)
            entries = load_queue(character)
            existing = {e.get("label", "") for e in entries}
            label    = body.get("label") or "untitled"
            label    = make_unique_label(re.sub(r"[^a-zA-Z0-9_-]+", "-", label).strip("-"), existing)
            new_entry = {"label": label, "prompt": body.get("prompt", "").strip()}
            for k in ("width", "height", "seed", "steps", "guidance", "negative"):
                if body.get(k) not in (None, ""):
                    new_entry[k] = body[k]
            entries.insert(0, new_entry)   # PREPEND so it runs next
            save_queue(character, entries)
            C.log_event("queue_added", character=character, label=label)
            return self._send_json({"ok": True, "label": label, "count": len(entries)})

        if path == "/api/queue/update":
            character = body.get("character")
            label     = body.get("label")
            fields    = body.get("fields", {})
            entries = load_queue(character)
            # If the label is being changed, ensure it's unique (rename collisions get suffixed).
            new_label = fields.get("label")
            if new_label and new_label != label:
                existing = {e.get("label", "") for e in entries if e.get("label") != label}
                fields["label"] = make_unique_label(re.sub(r"[^a-zA-Z0-9_-]+", "-", new_label).strip("-"), existing)
            found = False
            for e in entries:
                if e.get("label") == label:
                    e.update({k: v for k, v in fields.items() if v is not None})
                    found = True
                    break
            if not found:
                return self._send_json({"ok": False, "err": "label not found"}, 404)
            save_queue(character, entries)
            C.log_event("queue_updated", character=character, label=label)
            return self._send_json({"ok": True, "label": fields.get("label", label)})

        if path == "/api/queue/duplicate":
            character = body.get("character")
            label     = body.get("label")
            entries = load_queue(character)
            existing = {e.get("label", "") for e in entries}
            for i, e in enumerate(entries):
                if e.get("label") == label:
                    copy = dict(e)
                    base = re.sub(r"-(?:copy|copy-\d+)$", "", e["label"]) + "-copy"
                    copy["label"] = make_unique_label(base, existing)
                    # Insert right after the original
                    entries.insert(i + 1, copy)
                    save_queue(character, entries)
                    C.log_event("queue_duplicated", character=character,
                                source=label, new_label=copy["label"])
                    return self._send_json({"ok": True, "label": copy["label"]})
            return self._send_json({"ok": False, "err": "label not found"}, 404)

        if path == "/api/queue/delete":
            character = body.get("character")
            labels    = set(body.get("labels", []))
            entries = [e for e in load_queue(character) if e.get("label") not in labels]
            save_queue(character, entries)
            C.log_event("queue_deleted", character=character, labels=list(labels))
            return self._send_json({"ok": True, "remaining": len(entries)})

        if path == "/api/queue/reorder":
            character = body.get("character")
            order     = body.get("labels", [])
            entries = load_queue(character)
            by_label = {e.get("label"): e for e in entries}
            reordered = [by_label[l] for l in order if l in by_label]
            # Append any missing ones at the end
            for e in entries:
                if e.get("label") not in order:
                    reordered.append(e)
            save_queue(character, reordered)
            return self._send_json({"ok": True})

        if path == "/api/queue/clear":
            character = body.get("character")
            confirm   = body.get("confirm")
            if confirm != True:
                return self._send_json({"ok": False, "err": "confirm flag required"}, 400)
            save_queue(character, [])
            C.log_event("queue_cleared", character=character)
            return self._send_json({"ok": True})

        if path == "/api/queue/shuffle":
            import random as _random
            character = body.get("character")
            if not character:
                return self._send_json({"ok": False, "err": "missing character"}, 400)
            queue_path = C.queue_file(character)
            try:
                queue = yaml.safe_load(queue_path.read_text(encoding="utf-8")) or []
            except Exception as e:
                return self._send_json({"ok": False, "err": f"queue.yaml unreadable: {e}"}, 500)
            if not isinstance(queue, list) or len(queue) < 2:
                return self._send_json({"ok": True, "shuffled": 0})
            _random.shuffle(queue)
            queue_path.write_text(
                yaml.safe_dump(queue, allow_unicode=True, sort_keys=False, width=120),
                encoding="utf-8",
            )
            C.log_event("queue_shuffled", character=character, count=len(queue))
            return self._send_json({"ok": True, "shuffled": len(queue)})

        if path == "/api/queue/import":
            character = body.get("character")
            yaml_text = body.get("yaml", "")
            try:
                parsed = yaml.safe_load(yaml_text) or []
                if not isinstance(parsed, list):
                    return self._send_json({"ok": False, "err": "expected a YAML list"}, 400)
                parsed = [e for e in parsed if isinstance(e, dict) and e.get("label") and e.get("prompt")]
            except Exception as e:
                return self._send_json({"ok": False, "err": f"YAML parse: {e}"}, 400)
            entries = load_queue(character)
            existing = {e.get("label", "") for e in entries}
            added = 0
            for e in parsed:
                e["label"] = make_unique_label(e["label"], existing)
                existing.add(e["label"])
                entries.append(e)
                added += 1
            save_queue(character, entries)
            C.log_event("queue_imported", character=character, added=added)
            return self._send_json({"ok": True, "added": added, "total": len(entries)})

        # ── Run controls ────────────────────────────────────────────────────
        if path == "/api/run/start":
            character = body.get("character")
            if not character:
                return self._send_json({"ok": False, "err": "missing character"}, 400)
            return self._send_json(run_start(character))

        if path == "/api/run/stop":
            return self._send_json(run_stop())

        if path == "/api/run/chain-after-upscale":
            character = body.get("character")
            enabled   = bool(body.get("enabled", True))
            if not character:
                return self._send_json({"ok": False, "err": "missing character"}, 400)
            if enabled:
                _chain_after_upscale[character] = True
            else:
                _chain_after_upscale.pop(character, None)
            return self._send_json({"ok": True, "chain_after_upscale": enabled})

        # ── Character creation ──────────────────────────────────────────────
        if path == "/api/character/create":
            name = (body.get("name") or "").strip()
            if not name:
                return self._send_json({"ok": False, "err": "missing name"}, 400)
            # Filename safety: lowercase, only [a-z0-9_], no leading underscore
            if not re.match(r"^[a-z][a-z0-9_]{1,30}$", name):
                return self._send_json({"ok": False,
                    "err": "name must be lowercase, start with a letter, "
                           "use only a-z, 0-9, _ (1–31 chars)"}, 400)
            target = C.CHARACTERS / name
            if target.exists():
                return self._send_json({"ok": False,
                    "err": f"character '{name}' already exists"}, 400)
            template = C.CHARACTERS / "_template"
            if not template.exists():
                return self._send_json({"ok": False,
                    "err": "missing characters/_template/ — reinstall or restore from git"}, 500)
            # Copy template, rewriting placeholders to the new character's name
            shutil.copytree(template, target)
            for f in (target / "config.yaml", target / "training_config.yaml",
                      target / "queue.yaml"):
                if f.exists():
                    txt = f.read_text(encoding="utf-8")
                    txt = (txt
                           .replace("__CHARACTER__", name)
                           .replace("__CHARACTER_NAME__", name.replace("_", " ").title())
                           .replace("__TRIGGER_WORD__", name.replace("_", " "))
                           .replace("__VISUAL_TAGS__",
                                    "<add visual tags here, e.g. fox girl, black hair, blue eyes>")
                           .replace("__DEFAULT_OUTFIT_TAGS__",
                                    "<add default outfit tags here, e.g. white camisole, black shorts>"))
                    f.write_text(txt, encoding="utf-8")
            C.log_event("character_created", character=name)
            return self._send_json({"ok": True, "character": name})

        # ── Tools ───────────────────────────────────────────────────────────
        if path == "/api/upscale":
            character = body.get("character")
            if not character:
                return self._send_json({"ok": False, "err": "missing character"}, 400)
            extra: list[str] = []
            scale = body.get("scale")
            if isinstance(scale, (int, float)) and scale > 0:
                extra.extend(["--scale", str(float(scale))])
            return self._send_json(spawn_tool("upscale", character, "upscale.py",
                                              extra_args=extra))

        if path == "/api/training/start":
            character = body.get("character")
            if not character:
                return self._send_json({"ok": False, "err": "missing character"}, 400)
            cfg = C.char_dir(character) / "training_config.yaml"
            if not cfg.exists():
                return self._send_json({"ok": False,
                    "err": f"No training_config.yaml at {cfg}. Create one first."}, 400)
            # Capture chain-to-gen intent atomically with the start request so
            # restarts / character-switches / page reloads can't silently drop it.
            if body.get("chain_to_gen"):
                _chain_after_training[character] = True
            return self._send_json(spawn_tool("training", character, "train.py"))

        if path == "/api/training/stop":
            return self._send_json(stop_tool("training"))

        if path == "/api/training/chain-to-gen":
            character = body.get("character")
            enabled   = bool(body.get("enabled", True))
            if not character:
                return self._send_json({"ok": False, "err": "missing character"}, 400)
            if enabled:
                _chain_after_training[character] = True
            else:
                _chain_after_training.pop(character, None)
            return self._send_json({"ok": True, "chain_after_training": enabled})

        if path == "/api/upscale-one":
            character = body.get("character")
            stem      = body.get("stem")
            if not character or not stem:
                return self._send_json({"ok": False, "err": "missing character or stem"}, 400)
            # Find the source PNG (could be in output/, liked/, liked_archive/, or any archive batch)
            src = locate_image_file(character, f"{stem}.png")
            if not src:
                return self._send_json({"ok": False, "err": f"source not found: {stem}.png"}, 404)
            # If a SDXL upscale already exists, refuse
            if (C.upscaled_dir(character) / f"{stem}_2k.png").exists():
                return self._send_json({"ok": False, "err": "already upscaled (_2k.png exists)"}, 409)
            # Refuse if the batch upscaler is currently running
            with _tool_lock:
                up = _tool_state.get("upscale", {})
                if up.get("state") == "running":
                    return self._send_json({"ok": False, "err": "Batch upscaler is running."}, 409)
            # GPU mutual exclusion with generation
            if _run_proc and _run_proc.poll() is None:
                return self._send_json({"ok": False, "err": "Generation run in progress."}, 409)
            scale = body.get("scale")
            scale_arg = float(scale) if isinstance(scale, (int, float)) and scale > 0 else None
            return self._send_json(spawn_upscale_single(character, str(src), stem, scale_arg))

        if path == "/api/build-reference":
            character = body.get("character")
            if not character:
                return self._send_json({"ok": False, "err": "missing character"}, 400)
            return self._send_json(spawn_tool("build_reference", character, "build_reference.py"))

        if path == "/api/tool/stop":
            tool = body.get("tool")
            if not tool:
                return self._send_json({"ok": False, "err": "missing tool"}, 400)
            return self._send_json(stop_tool(tool))

        return self.send_error(404, f"not found: {path}")


def run() -> None:
    # Force stdout/stderr to UTF-8 on Windows so logging emoji etc. works
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"\n  vrfu-ai - local web UI")
    print(f"  http://localhost:{PORT}")
    print(f"  Ctrl+C to stop\n")
    C.log_event("server_started", port=PORT)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        srv.server_close()
        C.log_event("server_stopped")


if __name__ == "__main__":
    run()
