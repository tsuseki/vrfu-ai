"""
Build a human-readable reference of what the user liked.

Reads:
  - web/data/feedback.json
  - characters/<character>/archive/done.yaml

Writes:
  - docs/REFERENCE_<character>.md   — markdown report (artists, categories, scenes, outfits)
  - characters/<character>/liked_images.txt  — flat list of liked stems

Usage:
    python build_reference.py --character tsu_chocola
    python build_reference.py                 # auto-pick if there's exactly one character
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import _common as C  # noqa: E402

POSITIVE_KEYS = {"super_like", "love", "like", "style", "prompt", "pose", "outfit"}
NOISY = {
    "1girl", "solo", "fox girl",
    "black fox ears", "solid black fox tail", "black fox tail",
    "black hair", "red eyes", "diamond-shaped pupils", "red feather hair ornament",
    "facial mark", "masterpiece", "best quality", "amazing quality", "very aesthetic",
    "highres", "absurdres", "newest", "year 2024", "anime coloring", "anime screencap",
    "cel shading", "flat color", "2d", "looking at viewer",
}


def parse_artists(prompt: str) -> list[str]:
    """Match artist:NAME including parens (bara_(rism)) and spaces (mika pikazo)."""
    return [a.strip() for a in re.findall(
        r"artist:([a-z0-9_\s\-\.\(\)]+?)(?=,|$)", prompt or "", re.IGNORECASE)]


def parse_category(label: str) -> str:
    lower = label.lower()
    if any(k in lower for k in ["foot", "feet", "soles", "toes"]):
        return "feet/foot-focus"
    if "nsfw" in lower or "nude" in lower:
        return "nsfw"
    if any(k in lower for k in ["bikini", "lingerie"]):
        return "lewd-light"
    if "sfw" in lower:
        return "sfw"
    return "other"


def extract_scene_tags(prompt: str, character_name_lower: str) -> list[str]:
    parts = [p.strip() for p in (prompt or "").split(",")]
    out = []
    for p in parts:
        if not p:                       continue
        if p.startswith("artist:"):     continue
        if p.lower() in NOISY:          continue
        if p.lower() == character_name_lower: continue
        out.append(p)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the liked-images reference report.")
    parser.add_argument("--character", help="Character name (folder under characters/)")
    args = parser.parse_args()

    char_name = C.resolve_default_character(args.character)
    feedback_path = C.WEB / "data" / "feedback.json"
    done_path     = C.done_file(char_name)
    out_md        = C.DOCS / f"REFERENCE_{char_name}.md"
    out_txt       = C.char_dir(char_name) / "liked_images.txt"

    feedback = {}
    if feedback_path.exists():
        feedback = json.loads(feedback_path.read_text(encoding="utf-8")).get(char_name, {})

    done = []
    if done_path.exists():
        done = [e for e in (yaml.safe_load(done_path.read_text(encoding="utf-8")) or [])
                if isinstance(e, dict)]
    done_by_label = {e["label"]: e for e in done if "label" in e}

    char_lower = char_name.replace("_", " ").lower()

    artists_in_batch  = Counter()
    artist_score      = Counter()
    artist_seen_voted = Counter()
    artist_issues     = Counter()
    category_score    = Counter()
    outfit_tags       = Counter()
    pose_tags         = Counter()
    prompt_tags       = Counter()
    all_tags_in_liked = Counter()

    for entry in done:
        for a in parse_artists(entry.get("prompt", "")):
            artists_in_batch[a.lower()] += 1

    loved_stems    = []
    liked_stems    = []
    disliked_stems = []
    issue_stems    = []
    positive_stems = []

    for stem, fb in feedback.items():
        votes = fb.get("votes", {})
        label = stem.split("_", 1)[1] if "_" in stem and stem.split("_", 1)[0].isdigit() else stem
        entry = done_by_label.get(label, {})
        prompt = entry.get("prompt", "")
        artists = parse_artists(prompt)
        scene = extract_scene_tags(prompt, char_lower)
        cat = parse_category(label)

        is_loved    = votes.get("love")
        is_liked    = votes.get("like")
        is_disliked = votes.get("dislike")
        is_issue    = votes.get("anatomy_issue")
        is_positive = any(votes.get(k) for k in POSITIVE_KEYS)

        if is_disliked: disliked_stems.append(stem)
        if is_issue:    issue_stems.append(stem)
        if is_loved:    loved_stems.append(stem)
        if is_liked and not is_loved: liked_stems.append(stem)
        if is_positive and not is_disliked:
            positive_stems.append(stem)
            for t in scene: all_tags_in_liked[t.lower()] += 1
            category_score[cat] += 1

        is_super = votes.get("super_like")
        for a in artists:
            a_low = a.lower()
            artist_seen_voted[a_low] += 1
            score = 0
            if is_super:    score += 5    # 💜 strongest signal
            if is_loved:    score += 3
            if is_liked:    score += 1
            if votes.get("style"): score += 2
            if is_disliked: score -= 3
            # Note: anatomy issues are the model's fault, not the artist's,
            # so they don't penalize the artist score.
            artist_score[a_low] += score
            if is_disliked:
                artist_issues[a_low] += 1

        if votes.get("outfit"):
            for t in scene: outfit_tags[t.lower()] += 1
        if votes.get("pose"):
            for t in scene: pose_tags[t.lower()] += 1
        if votes.get("prompt"):
            for t in scene: prompt_tags[t.lower()] += 1

    # ── Render markdown ─────────────────────────────────────────────────────
    md = []
    md.append(f"# {char_name} — Liked Reference")
    md.append("")
    md.append(f"_Generated by `scripts/build_reference.py`._")
    md.append("")
    md.append(f"**Total voted:** {len(feedback)} · **❤️ Loved:** {len(loved_stems)} · "
              f"**👍 Liked:** {len(liked_stems)} · **👎 Disliked:** {len(disliked_stems)} · "
              f"**⚠️ Issues:** {len(issue_stems)}")
    md.append("")
    md.append("## 🎨 Artist Rankings")
    md.append("")
    md.append("Score = (5×super-like) + (3×love) + (1×like) + (2×style) − (3×dislike).")
    md.append("(Anatomy issues are not counted — those are model glitches, not the artist's fault.)")
    md.append("")
    md.append("| Artist | Score | Voted | In batch | Issues | Verdict |")
    md.append("|---|---:|---:|---:|---:|---|")
    all_artists = set(artists_in_batch) | set(artist_score)
    rows = []
    for a in all_artists:
        score = artist_score[a]
        voted = artist_seen_voted[a]
        total = artists_in_batch[a]
        issues = artist_issues[a]
        if score > 0:                       v = "✅ keep"
        elif score < 0:                     v = "❌ drop"
        elif total > 0 and voted == 0:      v = "❓ test more"
        elif voted > 0 and score == 0:      v = "🟡 didn't land"
        else:                               v = "—"
        rows.append((a, score, voted, total, issues, v))
    rows.sort(key=lambda r: (-r[1], -r[2]))
    for a, s, v, t, i, verdict in rows:
        md.append(f"| {a} | {s:+d} | {v} | {t} | {i} | {verdict} |")

    md.append("")
    md.append("## 📍 Categories you liked")
    md.append("")
    md.append("| Category | Liked count |")
    md.append("|---|---:|")
    for c, n in category_score.most_common():
        md.append(f"| {c} | {n} |")

    def section(title: str, counter: Counter, n: int = 25) -> list[str]:
        out = ["", f"## {title}", ""]
        if not counter:
            out.append("_(no votes in this category)_")
            return out
        out.append("| Tag | Count |")
        out.append("|---|---:|")
        for t, c in counter.most_common(n):
            out.append(f"| {t} | {c} |")
        return out

    md += section("👗 Outfit tags (from outfit-voted images)", outfit_tags)
    md += section("🤸 Pose tags (from pose-voted images)", pose_tags)
    md += section("📍 Scene tags (from prompt-voted images)", prompt_tags)
    md += section("✨ Common scene tags across all liked", all_tags_in_liked)

    md.append("")
    md.append("## ❤️ Loved images")
    md.append("")
    for stem in loved_stems:
        label = stem.split("_", 1)[1] if "_" in stem and stem.split("_", 1)[0].isdigit() else stem
        e = done_by_label.get(label, {})
        artists = parse_artists(e.get("prompt", "")) or ["—"]
        md.append(f"- `{stem}` — artists: {', '.join(artists)}")

    md.append("")
    md.append("## 👍 Liked images")
    md.append("")
    for stem in liked_stems:
        label = stem.split("_", 1)[1] if "_" in stem and stem.split("_", 1)[0].isdigit() else stem
        e = done_by_label.get(label, {})
        artists = parse_artists(e.get("prompt", "")) or ["—"]
        md.append(f"- `{stem}` — artists: {', '.join(artists)}")

    if issue_stems:
        md.append("")
        md.append("## ⚠️ Anatomy-issue images")
        md.append("")
        for stem in issue_stems:
            md.append(f"- `{stem}`")

    if disliked_stems:
        md.append("")
        md.append("## 👎 Disliked images")
        md.append("")
        for stem in disliked_stems:
            md.append(f"- `{stem}`")

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(md), encoding="utf-8")
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text("\n".join(positive_stems), encoding="utf-8")

    print(f"Wrote {out_md}")
    print(f"Wrote {out_txt}  ({len(positive_stems)} stems)")
    print()
    print("Top artists (positive score):")
    for a, s in artist_score.most_common(8):
        if s > 0:
            print(f"  {a:<20} score={s:+d}  voted={artist_seen_voted[a]}  in_batch={artists_in_batch[a]}")

    C.log_event("reference_built", character=char_name,
                positive=len(positive_stems), total_voted=len(feedback))


if __name__ == "__main__":
    main()
