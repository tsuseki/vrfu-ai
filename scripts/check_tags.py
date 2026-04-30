"""
Validate prompt tags against Danbooru's post counts.

Per docs/PROMPTING.md, tags with low post counts (< ~100) are unlikely to be
well-learned by booru-trained SDXL models. This script extracts tags from a
prompt or queue.yaml, queries Danbooru's tags API for each, and reports tags
that fall below a threshold.

Hits a small disk cache (characters/_cache/danbooru_tags.json) so repeated
runs don't re-query tags we've already seen.

Usage:
    # Validate all unique tags in a character's queue
    python scripts/check_tags.py --character kutsu_rindo

    # Validate a single prompt string
    python scripts/check_tags.py --prompt "1girl, solo, miko, engawa, wariza"

    # Different threshold (default 100)
    python scripts/check_tags.py --character kutsu_rindo --threshold 500

    # Show all tags including OK ones (default: only flags problems)
    python scripts/check_tags.py --character kutsu_rindo --verbose
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import _common as C  # noqa: E402

CACHE_PATH = C.CHARACTERS / "_cache" / "danbooru_tags.json"
DANBOORU_URL = "https://danbooru.donmai.us/tags.json"
USER_AGENT = "AI-Art-Project/1.0 (local prompt validator)"

# Tags we never need to validate — they're not real booru tags but custom
# project tokens, weighting syntax we strip elsewhere, or things the model
# learns from quality boosters.
SKIP_TAGS = {
    # Project triggers (will fail Danbooru lookup)
    "kutsu rindo", "cocoa mizu", "tsu chocola",
    # Quality / aesthetic stack — these ARE on Danbooru but always count high
    "masterpiece", "best quality", "amazing quality", "very aesthetic", "aesthetic",
    "absurdres", "highres", "lowres", "newest", "recent", "old", "oldest",
    "displeasing", "very displeasing", "worst aesthetic", "very awa",
    # Subject count
    "1girl", "1boy", "solo", "2girls", "multiple girls",
    # Rating
    "safe", "sensitive", "questionable", "nsfw", "explicit",
    # Negatives we always include
    "worst quality", "low quality", "bad quality", "normal quality",
    "bad anatomy", "bad hands", "bad proportions", "deformed", "mutated",
    "extra digits", "extra fingers", "fewer digits", "missing fingers",
    "fused fingers", "extra limbs", "blurry", "jpeg artifacts",
    "watermark", "signature", "text", "logo", "artist name", "username",
    "3d", "3dcg", "cgi", "blender", "render", "vrchat", "mmd",
    "photorealistic", "realistic", "photo",
    "cropped head", "cropped feet", "head out of frame", "multiple views",
    "split screen", "sketch", "censor", "chromatic aberration", "scan",
}


def strip_emphasis(tag: str) -> str:
    """(foo:1.3) -> foo;  [foo] -> foo"""
    t = tag.strip()
    m = re.match(r"^\(\s*(.+?)\s*(?::[\d.]+)?\)$", t)
    if m:
        t = m.group(1).strip()
    m = re.match(r"^\[\s*(.+?)\s*\]$", t)
    if m:
        t = m.group(1).strip()
    return t


def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def query_danbooru(tag: str) -> int | None:
    """Return post_count for the tag, or None if not found / network error."""
    # Danbooru uses underscores in tag names, but accepts spaces too via
    # name_matches. Use the exact-match `name` field for accuracy.
    api_tag = tag.replace(" ", "_").lower()
    url = f"{DANBOORU_URL}?{urllib.parse.urlencode({'search[name]': api_tag, 'limit': 1})}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, list) and data:
            return int(data[0].get("post_count", 0))
        return 0  # tag exists nowhere = post_count effectively 0
    except Exception as e:
        print(f"  WARN: query failed for '{tag}': {e}", file=sys.stderr)
        return None


def collect_prompt_tags(prompt: str) -> set[str]:
    """Split a prompt into individual normalized tags, dropping weighting/artist/skip."""
    tags = set()
    for raw in prompt.split(","):
        t = strip_emphasis(raw).lower()
        if not t:
            continue
        if t.startswith("artist:"):
            continue
        if t in SKIP_TAGS:
            continue
        # Heuristic: skip very long phrases (descriptive sentences leak through here)
        if len(t.split()) > 5:
            continue
        tags.add(t)
    return tags


def collect_queue_tags(queue_path: Path) -> set[str]:
    """Extract every unique non-skip tag across a character's queue."""
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8")) or []
    all_tags = set()
    for entry in queue:
        all_tags |= collect_prompt_tags(entry.get("prompt") or "")
    return all_tags


def validate(tags: set[str], threshold: int, verbose: bool = False) -> tuple[list, list, list]:
    """Returns (problems, ok, errors). Each is a list of (tag, post_count)."""
    cache = load_cache()
    problems, ok, errors = [], [], []
    new_queries = 0
    for tag in sorted(tags):
        if tag in cache:
            count = cache[tag]
        else:
            # Throttle: Danbooru asks for max 1 req/sec for anonymous users
            if new_queries > 0:
                time.sleep(1.1)
            count = query_danbooru(tag)
            new_queries += 1
            if count is not None:
                cache[tag] = count
        if count is None:
            errors.append((tag, None))
        elif count < threshold:
            problems.append((tag, count))
        else:
            ok.append((tag, count))
    save_cache(cache)
    return problems, ok, errors


def main():
    ap = argparse.ArgumentParser(description="Validate prompt tags against Danbooru post counts.")
    ap.add_argument("--character", help="Validate every prompt in this character's queue.yaml")
    ap.add_argument("--prompt", help="Validate a single comma-separated prompt string")
    ap.add_argument("--threshold", type=int, default=100,
                    help="Flag tags with fewer than this many posts (default: 100)")
    ap.add_argument("--verbose", action="store_true",
                    help="Show all tags, not just flagged ones")
    args = ap.parse_args()

    if not args.character and not args.prompt:
        ap.error("provide --character or --prompt")

    if args.prompt:
        tags = collect_prompt_tags(args.prompt)
        source = "prompt"
    else:
        char_dir = C.char_dir(args.character)
        queue_path = char_dir / "queue.yaml"
        if not queue_path.exists():
            sys.exit(f"ERROR: no queue.yaml at {queue_path}")
        tags = collect_queue_tags(queue_path)
        source = f"{args.character}/queue.yaml"

    if not tags:
        print(f"No validatable tags found in {source}.")
        return

    print(f"Validating {len(tags)} unique tag(s) from {source} against Danbooru "
          f"(threshold: {args.threshold} posts)...\n")
    problems, ok, errors = validate(tags, args.threshold, args.verbose)

    if problems:
        print(f"FLAGGED — {len(problems)} tag(s) below {args.threshold} posts:")
        for tag, count in sorted(problems, key=lambda x: x[1]):
            print(f"  {count:>7,}  {tag}")
        print()
    if errors:
        print(f"ERRORS — {len(errors)} tag(s) failed to query:")
        for tag, _ in errors:
            print(f"          {tag}")
        print()
    if args.verbose and ok:
        print(f"OK — {len(ok)} tag(s) above threshold:")
        for tag, count in sorted(ok, key=lambda x: -x[1]):
            print(f"  {count:>7,}  {tag}")
        print()

    if not problems and not errors:
        print(f"All {len(tags)} tag(s) above {args.threshold} posts. Looks clean.")


if __name__ == "__main__":
    main()
