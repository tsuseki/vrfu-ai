"""
Review prompts in a character's queue.yaml against best-practice rules.

Combines tag-validity checking (via check_tags.py) with structural lints
derived from docs/PROMPTING.md. Emits a report of issues per prompt so you
can spot bad tags, conflicts, or style mistakes before generation runs.

Usage:
    # Review every prompt in a character's queue (default mode)
    python scripts/review_prompts.py --character kutsu_rindo

    # Review only the first N prompts
    python scripts/review_prompts.py --character kutsu_rindo --limit 5

    # Skip the Danbooru tag validation pass (faster, no network)
    python scripts/review_prompts.py --character kutsu_rindo --no-tag-check

    # Different post-count threshold for tag flagging
    python scripts/review_prompts.py --character kutsu_rindo --threshold 500

The report shows for each prompt:
  - Structural issues (missing 1girl/solo, conflicting tags, sentence-style
    descriptions, mixed Pony+Illustrious quality stacks, etc.)
  - Low-post-count Danbooru tags (under threshold = model probably doesn't
    know the tag well)
  - Bad combinations (e.g. nude + outfit, foot focus without full body)

Exit code is 0 if no issues, 1 if any prompt has problems — handy for hooking
into a pre-generation check or a /loop validator.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import _common as C  # noqa: E402
import check_tags as CT  # noqa: E402

# ── Lint rules ─────────────────────────────────────────────────────────────

# Quality stacks that don't belong on Illustrious. Per PROMPTING.md these are
# Pony-only and either do nothing or actively hurt on waiIllustrious.
PONY_QUALITY_TAGS = {
    "score_9", "score_8_up", "score_7_up", "score_6_up", "score_5_up", "score_4_up",
    "source_anime", "source_furry", "rating_safe", "rating_explicit",
}

# Outdated noise that doesn't help on any modern booru-trained SDXL
OUTDATED_QUALITY_TAGS = {
    "8k", "4k", "ultra hd", "uhd", "high resolution", "ultra detailed",
    "extremely detailed", "intricate details",
}

# Pairs that conflict with each other in the same prompt
CONFLICTING_PAIRS = [
    ({"upper body", "head focus", "portrait", "close-up"}, {"foot focus", "feet", "soles", "full body", "lower body"}),
    ({"nude", "topless"}, {"white kimono", "red hakama", "miko", "bikini", "swimsuit",
                            "school uniform", "white camisole", "white sailor top"}),
    ({"day", "daytime", "morning", "afternoon"}, {"night", "moonlight", "midnight"}),
    ({"sitting"}, {"standing", "running", "walking"}),
    ({"on back", "lying down"}, {"standing", "sitting", "running"}),
]

# Common typo / not-actually-a-danbooru-tag swaps to suggest. Maps wrong -> right.
TAG_SUGGESTIONS = {
    "engawa": "veranda  (engawa is a 0-post Danbooru tag; veranda has ~2900)",
    "shrine maiden": "miko  (shrine maiden works as alias but miko is canonical)",
    "shrine maiden outfit": "miko, japanese clothes",
    "off shoulder white sleeves": "detached sleeves, wide sleeves",
    "long blonde hair": "blonde hair, long hair  (split into two canonical tags)",
    "long fluffy fox tail": "fox tail, fluffy tail  (split; canonical Danbooru tags)",
    "low twin ponytails": "low twintails  (twintails is one word on Danbooru)",
    "thick red blush": "blush, heavy makeup  (no thick-red-blush tag exists)",
    "red whisker markings": "whisker markings  (color is rarely used as tag prefix)",
    "red cheek stripes": "facial mark  (cheek stripes is not a canonical tag)",
    "red eyeshadow": "eyeshadow, red eyeliner",
    "blue toenails": "blue nails, nail polish  (toenail-color tags rare on Danbooru)",
    "soft lighting": "(implicit; rarely needed as explicit tag)",
    "soft window light": "indoors, sunlight  (descriptive phrase, not a tag)",
    "soft natural light": "(descriptive phrase; drop or use 'sunlight')",
    "dappled sunlight": "(real tag, OK to keep)",
    "stone bench": "bench  (stone-bench rarely a canonical tag)",
    "stone path": "path, stone walkway  (varies by booru tag set)",
}


def strip_emphasis(tag: str) -> str:
    return CT.strip_emphasis(tag)


def lint_prompt(prompt: str, label: str) -> list[str]:
    """Return a list of issue strings for this prompt."""
    issues = []
    raw_tokens = [t.strip() for t in prompt.split(",") if t.strip()]
    norm = [strip_emphasis(t).lower() for t in raw_tokens]
    norm_set = set(norm)

    # 1. Subject anchor: must have 1girl + solo (or equivalent)
    if "1girl" not in norm_set and "1boy" not in norm_set:
        issues.append("missing subject count (1girl / 1boy)")
    if "solo" not in norm_set and not any(t in norm_set for t in ("2girls", "multiple girls")):
        issues.append("missing 'solo' (multi-figure protection)")

    # 2. Pony quality stack on Illustrious
    pony_used = norm_set & PONY_QUALITY_TAGS
    if pony_used:
        issues.append(f"Pony-only quality tags don't work on Illustrious: {', '.join(sorted(pony_used))}")

    # 3. Outdated noise tags
    outdated = norm_set & OUTDATED_QUALITY_TAGS
    if outdated:
        issues.append(f"outdated quality noise: {', '.join(sorted(outdated))}")

    # 4. Conflicting pairs
    for lhs, rhs in CONFLICTING_PAIRS:
        l = norm_set & lhs
        r = norm_set & rhs
        if l and r:
            issues.append(f"conflict: {sorted(l)} clashes with {sorted(r)}")

    # 5. Tags that look like sentences (>5 words)
    for raw, n in zip(raw_tokens, norm):
        # Skip artist tags and the {outfit} placeholder
        if n.startswith("artist:") or "{outfit" in raw:
            continue
        if len(n.split()) > 5:
            issues.append(f"long descriptive phrase (use shorter tags): \"{n}\"")

    # 6. Suggested swaps
    for tag in norm:
        if tag in TAG_SUGGESTIONS:
            issues.append(f"replace '{tag}' -> {TAG_SUGGESTIONS[tag]}")

    # 7. Foot focus without supporting framing
    if "foot focus" in norm_set and "full body" not in norm_set and "lower body" not in norm_set:
        issues.append("foot focus without 'full body' or 'lower body' — model may default to upper body")

    # 8. Duplicate tags
    seen = {}
    for n in norm:
        seen[n] = seen.get(n, 0) + 1
    dups = [k for k, v in seen.items() if v > 1]
    if dups:
        issues.append(f"duplicate tags: {', '.join(dups)}")

    return issues


def review_queue(character: str, limit: int | None, do_tag_check: bool, threshold: int):
    char_dir = C.char_dir(character)
    queue_path = char_dir / "queue.yaml"
    if not queue_path.exists():
        sys.exit(f"ERROR: no queue.yaml at {queue_path}")
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8")) or []
    if limit:
        queue = queue[:limit]

    print(f"=== Reviewing {len(queue)} prompt(s) from {character}/queue.yaml ===\n")

    flagged_count = 0
    for entry in queue:
        label = entry.get("label", "<no label>")
        prompt = entry.get("prompt") or ""
        issues = lint_prompt(prompt, label)
        if issues:
            flagged_count += 1
            print(f"[{label}]")
            for issue in issues:
                print(f"  - {issue}")
            print()

    if flagged_count == 0:
        print("No structural issues found.\n")
    else:
        print(f"--- {flagged_count} of {len(queue)} prompts have structural issues ---\n")

    # Tag-validity pass
    if do_tag_check:
        print("=== Danbooru tag-validity pass ===\n")
        all_tags = set()
        for entry in queue:
            all_tags |= CT.collect_prompt_tags(entry.get("prompt") or "")
        problems, _ok, errors = CT.validate(all_tags, threshold)

        if problems:
            print(f"FLAGGED — {len(problems)} unique tag(s) below {threshold} posts:")
            for tag, count in sorted(problems, key=lambda x: x[1]):
                print(f"  {count:>7,}  {tag}")
            print()
            flagged_count += 1
        if errors:
            print(f"ERRORS — {len(errors)} tag(s) failed to query:")
            for tag, _ in errors:
                print(f"          {tag}")
            print()
        if not problems and not errors:
            print(f"All {len(all_tags)} unique tags above {threshold} posts. Clean.\n")

    return flagged_count


def main():
    ap = argparse.ArgumentParser(description="Review queue prompts for issues per docs/PROMPTING.md.")
    ap.add_argument("--character", required=True, help="Character whose queue.yaml to review")
    ap.add_argument("--limit", type=int, help="Only review the first N prompts")
    ap.add_argument("--no-tag-check", action="store_true",
                    help="Skip the Danbooru post-count check (faster, offline)")
    ap.add_argument("--threshold", type=int, default=100,
                    help="Post-count threshold for tag flagging (default: 100)")
    args = ap.parse_args()

    n_flagged = review_queue(args.character, args.limit, not args.no_tag_check, args.threshold)
    sys.exit(0 if n_flagged == 0 else 1)


if __name__ == "__main__":
    main()
