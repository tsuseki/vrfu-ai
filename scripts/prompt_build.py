"""Prompt assembly logic shared between generate.py and server.py.

Lives in its own module (instead of inside generate.py) so the website can
import it for the prompt-preview endpoint without triggering generate.py's
top-level signal handlers and CUDA imports.

If you change BASE_POSITIVE / BASE_NEGATIVE here, update PROMPTING.md §9.
"""

from __future__ import annotations

import re


# Goes FIRST in the prompt so it survives CLIP's 77-token truncation. Keeps
# anime coloring + cel shading because the project's LoRA sources include 3D
# VRChat data that we need to actively steer back into 2D anime style.
BASE_POSITIVE = (
    "masterpiece, best quality, amazing quality, very aesthetic, newest, "
    "absurdres, anime coloring, cel shading"
)

# Negative per the guide's "stronger general-purpose" list, plus this project's
# specific add-ons: 3D-source negation (VRChat / MMD bias), multi-figure
# protection, and the white-tail-tip kill that comes from prior LoRA training
# bugs. Order doesn't affect negatives much, so grouped by category for
# readability.
BASE_NEGATIVE = (
    # quality
    "lowres, worst quality, low quality, bad quality, normal quality, "
    "displeasing, very displeasing, worst aesthetic, "
    # age/recency
    "oldest, early, "
    # artifacts
    "sketch, jpeg artifacts, blurry, chromatic aberration, artistic error, scan, censor, "
    # anatomy
    "bad anatomy, bad hands, bad proportions, deformed, mutated, malformed, "
    "extra digits, extra fingers, fewer digits, missing fingers, fused fingers, extra limbs, "
    # text/marks
    "watermark, signature, text, logo, artist name, username, "
    # 3D-source kill (VRChat / MMD / blender bias from training data)
    "3d, 3dcg, cgi, blender, render, vrchat, mmd, sourcefilmmaker, "
    "photorealistic, realistic, photo, "
    # multi-figure
    "multiple characters, multiple girls, 2girls, multiple views, split screen"
    # NOTE: per-character identity-protection negatives (e.g. "white tail tip"
    # for tsu_chocola) live in each character's config.yaml under
    # `negative_tags`, NOT here — they don't apply to all characters and
    # actively hurt characters who legitimately have those features
    # (e.g. cocoa_mizu has multicolored hair and a striped tail).
)


_OUTFIT_PLACEHOLDER = re.compile(r"\{outfit(?::([a-zA-Z0-9_-]+))?\}")
_SOLO_TAGS_RE = re.compile(r"\b(?:1girl|solo)\b\s*,?\s*", re.IGNORECASE)
_MULTIGIRL_NEG_RE = re.compile(
    r"\b(?:multiple\s+characters|multiple\s+girls|2girls|3girls|4girls|5girls|"
    r"6\+girls|multiple\s+views|split\s+screen)\b\s*,?\s*", re.IGNORECASE,
)


class OutfitNotFoundError(Exception):
    """Raised by expand_outfits when a {outfit:name} reference doesn't match
    any defined outfit. Callers decide whether to abort the run (generate.py)
    or surface the error to the UI (server.py preview endpoint)."""


def expand_outfits(prompt: str, cfg: dict) -> str:
    """Expand {outfit} and {outfit:name} placeholders using cfg['outfits']."""
    outfits = cfg.get("outfits") or {}
    def repl(m):
        name = m.group(1) or "default"
        if name not in outfits:
            available = ", ".join(sorted(outfits)) or "(none defined)"
            raise OutfitNotFoundError(
                f"prompt references {{outfit:{name}}} but config has no "
                f"outfits.{name}. Available: {available}"
            )
        return outfits[name]
    return _OUTFIT_PLACEHOLDER.sub(repl, prompt)


def _strip_solo_tags(s: str) -> str:
    """Remove '1girl' and 'solo' tokens from a comma-separated tag string."""
    return re.sub(r",\s*,", ", ", _SOLO_TAGS_RE.sub("", s)).strip(", ")


def _strip_multigirl_negatives(s: str) -> str:
    """Remove the multi-girl/multi-view negatives so they don't fight a clone scenario."""
    return re.sub(r",\s*,", ", ", _MULTIGIRL_NEG_RE.sub("", s)).strip(", ")


def build_prompt(entry: dict, cfg: dict) -> tuple[str, str]:
    """Compose the final positive + negative prompt that goes to the model.

    Order: BASE_POSITIVE → trigger → character_tags → user prompt
    so the highest-impact tags survive CLIP's 77-token cut.

    Negative: BASE_NEGATIVE (with multi-girl tags stripped if multi_girl mode),
    optionally appended with entry['negative'].
    """
    user_prompt = expand_outfits(entry["prompt"], cfg)
    trigger     = cfg.get("trigger_word", "")
    char_tags   = cfg.get("character_tags", "")

    # multi_girl mode: clone scenarios where multiple copies of the same
    # character appear together. Strips "1girl, solo" from character_tags
    # and removes the multi-girl tags from BASE_NEGATIVE so they don't
    # fight the prompt's "(multiple girls:1.6), (Ngirls:1.6)" weighting.
    multi_girl = bool(entry.get("multi_girl"))
    if multi_girl and char_tags:
        char_tags = _strip_solo_tags(char_tags)
    elif char_tags and re.match(r"\s*(?:1girl\b|solo\b)", user_prompt, re.IGNORECASE):
        # Convention says each user prompt also starts with "1girl, solo"
        # for emphasis. character_tags also has them. Without this dedupe
        # the final prompt has the pair twice. Strip from char_tags so the
        # user prompt's copy is the authoritative one.
        char_tags = _strip_solo_tags(char_tags)

    if trigger and trigger.lower() in user_prompt.lower():
        prompt = user_prompt if entry.get("no_base_tags") else f"{BASE_POSITIVE}, {user_prompt}"
    else:
        parts = []
        if not entry.get("no_base_tags"):
            parts.append(BASE_POSITIVE)
        if trigger:
            parts.append(trigger)
        if char_tags:
            parts.append(char_tags)
        prompt = ", ".join(parts) + ", " + user_prompt

    negative = _strip_multigirl_negatives(BASE_NEGATIVE) if multi_girl else BASE_NEGATIVE
    char_neg = cfg.get("negative_tags", "").strip()
    if char_neg:
        negative = f"{negative}, {char_neg}"
    if entry.get("negative"):
        negative = f"{negative}, {entry['negative']}"
    return prompt, negative
