"""
vrfu-ai Generation Script (SDXL / Illustrious + Character LoRAs)
================================================================

Reads a character's config.yaml + queue.yaml, generates images one by one
into the character's output/ folder, and moves completed entries from
queue.yaml → archive/done.yaml.

Usage:
    python generate.py --character tsu_chocola
    python generate.py                      # uses the only character if there's exactly one
    python generate.py --dry --character X  # preview queue without generating

The script also writes a structured progress line for each image so the
website can parse it and show live progress:

    PROGRESS: 12/259 label=kantoku-witch seed=1234567 dur=71.2
    BATCH_START total=259
    BATCH_END duration_s=18234.5

SIGTERM is handled gracefully — the current image finishes, then the script exits.
"""

from __future__ import annotations

import argparse
import random
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Force UTF-8 stdout/stderr so em-dashes etc. don't crash on Windows cp932/cp1252.
# `errors="replace"` keeps the script alive even on legacy code-page consoles.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import torch
import yaml

# ── peft + torchao version-mismatch workaround ─────────────────────────────
# ai-toolkit pins torchao==0.10.0 (the only version compatible with the
# torch 2.5.1 it requires). peft hard-raises ImportError when it sees torchao
# < 0.16.0 during LoRA dispatch — even though we don't use torchao-quantized
# LoRAs. We're not allowed to upgrade torchao (breaks ai-toolkit) and we're
# not allowed to upgrade torch (breaks ai-toolkit's xformers pin). So patch
# peft's check to silently say "not available" on old versions instead of
# crashing. Must run BEFORE diffusers/peft submodules are imported.
def _patch_peft_torchao_check() -> None:
    try:
        from peft import import_utils as _piu
    except Exception:
        return
    _orig = _piu.is_torchao_available
    def _safe():
        try:
            return _orig()
        except ImportError:
            return False
    try:
        _orig.cache_clear()
    except Exception:
        pass
    _piu.is_torchao_available = _safe
    # peft eagerly imports peft.tuners.lora.torchao via peft/__init__.py, so it
    # has already captured the original `is_torchao_available` name. Patch the
    # call-site reference too.
    try:
        from peft.tuners.lora import torchao as _peft_lora_torchao
        _peft_lora_torchao.is_torchao_available = _safe
    except Exception:
        pass
_patch_peft_torchao_check()

from compel import CompelForSDXL
from diffusers import (
    StableDiffusionXLPipeline,
    StableDiffusionXLImg2ImgPipeline,
    DPMSolverMultistepScheduler,
    EulerAncestralDiscreteScheduler,
)
from PIL import Image

# Bring in shared paths + activity logger from this same scripts/ folder
sys.path.insert(0, str(Path(__file__).parent))
import _common as C  # noqa: E402

# ── VRAM threshold ─────────────────────────────────────────────────────────
MIN_FREE_VRAM_MIB = 8000

# ── Defaults (overridable per-prompt in queue.yaml) ────────────────────────
DEFAULT_WIDTH    = 1024
DEFAULT_HEIGHT   = 1024
DEFAULT_STEPS    = 28
# CFG: docs/PROMPTING.md research found 4.5-6.0 is the actual sweet spot for
# waiIllustrious despite the model card's CFG 7 recommendation. 5.5 gives the
# best balance between prompt adherence and aesthetic.
DEFAULT_GUIDANCE = 5.5
DEFAULT_SAMPLER  = "euler_a"

# Quality + style anchors per docs/PROMPTING.md canonical Illustrious stack.
# Goes FIRST so it survives CLIP's 77-token truncation. Keeping anime coloring
# + cel shading because the user's LoRA sources include 3D VRChat data that we
# need to actively steer back into 2D anime style.
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
    "multiple characters, multiple girls, 2girls, multiple views, split screen, "
    # project-specific identity protection
    "white tail tip, two-tone tail, multicolored tail"
)

QUEUE_HEADER = """# PROMPT QUEUE
# Add prompts below. Top entry runs first. Completed entries move to archive/done.yaml.
# See docs/DATA_FORMATS.md for full field reference.
"""
DONE_HEADER = "# COMPLETED GENERATIONS — auto-managed, do not edit"

# ── SIGTERM handling: finish current image, then exit ──────────────────────
_stop_requested = False

def _handle_sigterm(signum, frame):
    global _stop_requested
    _stop_requested = True
    print("\n[SIGTERM received — finishing current image then stopping]\n", flush=True)

signal.signal(signal.SIGTERM, _handle_sigterm)
try:
    signal.signal(signal.SIGINT, _handle_sigterm)
except Exception:
    pass  # Windows may not have full SIGINT support in all contexts


# ───────────────────────────────────────────────────────────────────────────
# Utilities
# ───────────────────────────────────────────────────────────────────────────
def check_vram() -> None:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        free, used, total = [int(x.strip()) for x in r.stdout.strip().split(",")]
        print(f"VRAM: {used:,} / {total:,} MiB used  ({free:,} MiB free)")
        if free < MIN_FREE_VRAM_MIB:
            print(f"\nERROR: Only {free:,} MiB free — need {MIN_FREE_VRAM_MIB:,} MiB.\n")
            sys.exit(1)
    except FileNotFoundError:
        print("nvidia-smi not found, skipping VRAM check.")
    except Exception as e:
        print(f"VRAM check failed: {e}")


def load_yaml(path: Path) -> list | dict:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if data is not None else []


def save_yaml(path: Path, data, header: str = "") -> None:
    path.parent.mkdir(exist_ok=True, parents=True)
    with open(path, "w", encoding="utf-8") as f:
        if header:
            f.write(header + "\n")
        if data:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def get_scheduler(pipe, name: str):
    if name == "dpmpp_2m_karras":
        return DPMSolverMultistepScheduler.from_config(
            pipe.scheduler.config,
            algorithm_type="dpmsolver++",
            use_karras_sigmas=True,
        )
    return EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)


# ───────────────────────────────────────────────────────────────────────────
# Pipeline loading
# ───────────────────────────────────────────────────────────────────────────
def load_pipeline(cfg: dict):
    checkpoint = Path(cfg["checkpoint"])
    if not checkpoint.exists():
        sys.exit(f"ERROR: checkpoint not found at {checkpoint}")

    print(f"Loading SDXL checkpoint: {checkpoint.name}")
    pipe = StableDiffusionXLPipeline.from_single_file(
        str(checkpoint), torch_dtype=torch.float16, use_safetensors=True,
    )
    pipe.scheduler = get_scheduler(pipe, cfg.get("sampler", DEFAULT_SAMPLER))

    char_lora = Path(cfg["character_lora"])
    if not char_lora.exists():
        sys.exit(f"ERROR: character LoRA not found at {char_lora}")

    loras = [{"path": char_lora, "name": "character",
              "weight": cfg.get("character_lora_weight", 0.85)}]
    for extra in cfg.get("extra_loras", []) or []:
        p = Path(extra["path"])
        if not p.exists():
            print(f"WARN: extra LoRA not found, skipping: {p}")
            continue
        loras.append({"path": p, "name": extra.get("name", p.stem),
                      "weight": extra.get("weight", 0.5)})

    adapter_names, adapter_weights = [], []
    for lora in loras:
        print(f"Loading LoRA: {lora['name']:<12} weight={lora['weight']}  ({lora['path'].name})")
        pipe.load_lora_weights(str(lora["path"].parent),
                               weight_name=lora["path"].name,
                               adapter_name=lora["name"])
        adapter_names.append(lora["name"])
        adapter_weights.append(lora["weight"])
    pipe.set_adapters(adapter_names, adapter_weights=adapter_weights)

    # ── Memory strategy ──────────────────────────────────────────────────
    # SDXL + LoRA + img2img + text encoders fits 24 GB cleanly but is
    # right on the edge at 16 GB. When the friend's other apps eat VRAM,
    # the pipeline overflows into Windows "shared GPU memory" and steps
    # take 75 s/it instead of ~1.5 s/it. To prevent that on smaller
    # cards we offload text encoders + VAE to CPU between uses; UNet
    # stays GPU-resident for the hot loop.
    #
    # Known caveat: enable_model_cpu_offload races with CompelForSDXL.
    # Compel calls the text encoders directly with CPU-side token tensors,
    # the offload hook moves the encoder weights to GPU, but the inputs
    # stay on CPU → "Expected all tensors to be on the same device".
    # diffusers prints "Skipping and continuing..." and retries via the
    # standard pipeline path on the next image, costing ~10 s/image.
    # That's a much better deal than the 30-min/image swapping otherwise.
    total_vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
    if total_vram_gb < 20:
        print(f"VRAM {total_vram_gb:.1f} GB — enabling model CPU offload + VAE slicing.")
        print("(expect ~10 s of recovery time per image from a known Compel/offload race;")
        print(" still vastly faster than the alternative of swapping into shared memory.)")
        pipe.enable_model_cpu_offload()
        pipe.enable_vae_slicing()
        pipe.enable_vae_tiling()
    else:
        pipe.to("cuda")
        pipe.enable_vae_slicing()
        pipe.enable_vae_tiling()
    print("Pipeline ready.\n")
    img2img = StableDiffusionXLImg2ImgPipeline.from_pipe(pipe)
    return pipe, img2img


def make_compel(pipe) -> CompelForSDXL:
    """Build a CompelForSDXL processor for prompt weighting + long-prompt support.

    CompelForSDXL is the modern compel API (replaces the deprecated
    multi-tokenizer Compel constructor). It handles both SDXL text encoders
    internally, manages truncate_long_prompts=False properly (no hangs, no
    empty_z errors), and pads positive/negative to the same shape in one call.

    Reference: compel/convenience_wrappers.py CompelForSDXL.__call__
    """
    return CompelForSDXL(pipe)


def encode_with_compel(compel: CompelForSDXL, prompt: str, negative: str):
    """Encode positive + negative through Compel.

    Returns (pos_cond, pos_pool, neg_cond, neg_pool) matching the old
    multi-tokenizer compel's tuple shape so call sites don't need updating.
    """
    result = compel(main_prompt=prompt, negative_prompt=negative or "")
    return (result.embeds, result.pooled_embeds,
            result.negative_embeds, result.negative_pooled_embeds)


# ───────────────────────────────────────────────────────────────────────────
# Single-image generation
# ───────────────────────────────────────────────────────────────────────────
_OUTFIT_PLACEHOLDER = re.compile(r"\{outfit(?::([a-zA-Z0-9_-]+))?\}")


def expand_outfits(prompt: str, cfg: dict) -> str:
    """Expand {outfit} and {outfit:name} placeholders using cfg['outfits']."""
    outfits = cfg.get("outfits") or {}
    def repl(m):
        name = m.group(1) or "default"
        if name not in outfits:
            available = ", ".join(sorted(outfits)) or "(none defined)"
            raise SystemExit(
                f"ERROR: prompt references {{outfit:{name}}} but config has no "
                f"outfits.{name}. Available: {available}"
            )
        return outfits[name]
    return _OUTFIT_PLACEHOLDER.sub(repl, prompt)


def build_prompt(entry: dict, cfg: dict) -> tuple[str, str]:
    user_prompt = expand_outfits(entry["prompt"], cfg)
    trigger     = cfg["trigger_word"]
    char_tags   = cfg.get("character_tags", "")

    # Order: BASE_POSITIVE → trigger → character_tags → user prompt
    # so the highest-impact tags survive CLIP's 77-token cut.
    if trigger.lower() in user_prompt.lower():
        prompt = user_prompt if entry.get("no_base_tags") else f"{BASE_POSITIVE}, {user_prompt}"
    else:
        parts = []
        if not entry.get("no_base_tags"):
            parts.append(BASE_POSITIVE)
        parts.append(trigger)
        if char_tags:
            parts.append(char_tags)
        prompt = ", ".join(parts) + ", " + user_prompt

    negative = BASE_NEGATIVE
    if entry.get("negative"):
        negative = f"{negative}, {entry['negative']}"
    return prompt, negative


def generate_image(pipe, img2img_pipe, compel, entry: dict, id_: int,
                   cfg: dict, output_dir: Path, input_dir: Path) -> tuple[Path, float]:
    seed     = entry.get("seed") or random.randint(0, 2**32 - 1)
    steps    = entry.get("steps", DEFAULT_STEPS)
    guidance = entry.get("guidance", DEFAULT_GUIDANCE)
    width    = entry.get("width", DEFAULT_WIDTH)
    height   = entry.get("height", DEFAULT_HEIGHT)
    strength = entry.get("strength", 0.75)

    # Build the full prompt locally — DO NOT mutate `entry["prompt"]` here.
    # If we mutated and a downstream call errored, the polluted entry would
    # get re-saved to queue.yaml (because the error handler appends `entry`
    # back). That used to compound — each error cycle prepended BASE_POSITIVE
    # again, eventually filling the entire CLIP token window with junk.
    full_prompt, full_negative = build_prompt(entry, cfg)

    label    = entry["label"]
    id_str   = str(id_).zfill(3)
    filename = output_dir / f"{id_str}_{label}.png"

    torch.cuda.empty_cache()
    generator = torch.Generator("cuda").manual_seed(int(seed))

    # Encode through Compel — handles (term:1.5) weighting; truncates past 77 tokens
    pos_cond, pos_pool, neg_cond, neg_pool = encode_with_compel(compel, full_prompt, full_negative)

    mode = "img2img" if "image" in entry else "txt2img"
    print(f"  [{id_str}] {label}  ({mode})")
    print(f"  prompt   : {full_prompt}")
    print(f"  negative : {full_negative}")
    print(f"  seed     : {seed}  steps: {steps}  cfg: {guidance}  size: {width}x{height}")

    t0 = time.monotonic()
    if mode == "img2img":
        src_path = Path(entry["image"])
        if not src_path.is_absolute():
            src_path = input_dir / src_path.name
        if not src_path.exists():
            raise FileNotFoundError(f"img2img source not found: {src_path}")
        source = Image.open(src_path).convert("RGB").resize((width, height), Image.LANCZOS)
        print(f"  source   : {src_path.name}  strength: {strength}")
        result = img2img_pipe(
            prompt_embeds=pos_cond, pooled_prompt_embeds=pos_pool,
            negative_prompt_embeds=neg_cond, negative_pooled_prompt_embeds=neg_pool,
            image=source, strength=strength, num_inference_steps=steps,
            guidance_scale=guidance, generator=generator,
        ).images[0]
    else:
        result = pipe(
            prompt_embeds=pos_cond, pooled_prompt_embeds=pos_pool,
            negative_prompt_embeds=neg_cond, negative_pooled_prompt_embeds=neg_pool,
            width=width, height=height,
            num_inference_steps=steps, guidance_scale=guidance, generator=generator,
        ).images[0]
    duration = time.monotonic() - t0

    output_dir.mkdir(exist_ok=True)
    result.save(filename)
    torch.cuda.empty_cache()

    entry["seed"]     = int(seed)
    entry["steps"]    = steps
    entry["guidance"] = guidance
    entry["width"]    = width
    entry["height"]   = height

    print(f"  saved    : {filename.name}  ({duration:.1f}s)\n")
    return filename, duration, full_prompt, full_negative


# ───────────────────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Generate images from a character's queue.")
    parser.add_argument("--character", help="Character name (folder under characters/)")
    parser.add_argument("--dry", action="store_true", help="Preview queue without generating")
    args = parser.parse_args()

    char_name = C.resolve_default_character(args.character)
    cfg       = C.load_character(char_name)
    char_dir  = C.char_dir(char_name)
    queue_path = C.queue_file(char_name)
    done_path  = C.done_file(char_name)
    output_dir = C.output_dir(char_name)
    input_dir  = char_dir / "input"
    last_id    = char_dir / "last_id.txt"

    print(f"=== {cfg.get('character_name', char_name)} ===")
    print(f"Trigger : {cfg['trigger_word']}")
    print(f"Base    : {Path(cfg['checkpoint']).name}")
    print(f"LoRA    : {Path(cfg['character_lora']).name} @ {cfg.get('character_lora_weight', 0.85)}\n")

    queue = [e for e in load_yaml(queue_path) if isinstance(e, dict)]
    if not queue:
        print("Queue is empty. Add prompts to queue.yaml and run again.")
        sys.exit(0)
    print(f"Found {len(queue)} prompt(s) in queue.\n")

    done = load_yaml(done_path)
    done_max = max((int(e["id"]) for e in done if isinstance(e, dict) and "id" in e), default=0)
    file_max = int(last_id.read_text().strip()) if last_id.exists() else 0
    next_id  = max(done_max, file_max) + 1

    if args.dry:
        for e in queue:
            print(f"  [{str(next_id).zfill(3)}] {e['label']}")
            print(f"       {e['prompt']}\n")
            next_id += 1
        sys.exit(0)

    check_vram()
    pipe, img2img_pipe = load_pipeline(cfg)
    compel = make_compel(pipe)
    print("Compel weighting active: (term:1.5), [term], etc. respected. "
          "Long prompts (>77 tokens) are chunked and concatenated.\n")

    initial_total = len(queue)
    total = initial_total                # may grow if user adds to queue mid-run
    print(f"BATCH_START total={total}", flush=True)
    C.log_event("batch_started", character=char_name, total=total)
    batch_t0 = time.monotonic()
    completed = 0

    while not _stop_requested:
        # ALWAYS re-read the queue file: takes top entry freshly each iteration,
        # so reordering / new-prepends / deletions take effect immediately.
        queue_now = [e for e in load_yaml(queue_path) if isinstance(e, dict)]
        if not queue_now:
            print("[queue empty — done]", flush=True)
            break
        entry = queue_now[0]
        try:
            entry["id"] = next_id
            output_path, duration, full_prompt, full_negative = generate_image(
                pipe, img2img_pipe, compel, entry, next_id, cfg, output_dir, input_dir,
            )
            # Mutate ONLY after success — done.yaml gets the actual sent prompt.
            entry["prompt"]       = full_prompt
            entry["negative"]     = full_negative
            entry["output"]       = str(output_path.relative_to(char_dir))
            entry["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            done.append(entry)
            last_id.write_text(str(entry["id"]))

            # Remove the entry we just completed (by label, in case the user reordered
            # or deleted it while we were processing — this is the safe key).
            remaining = [
                e for e in load_yaml(queue_path)
                if isinstance(e, dict) and e.get("label") != entry["label"]
            ]
            save_yaml(queue_path, remaining, header=QUEUE_HEADER)
            save_yaml(done_path,
                      sorted(done, key=lambda e: int(e.get("id", 0))),
                      header=DONE_HEADER)

            completed += 1
            # Total = how many we've done + how many remain. May grow if user adds.
            total = max(total, completed + len(remaining))
            print(f"PROGRESS: {completed}/{total} label={entry['label']} seed={entry.get('seed')} dur={duration:.1f}",
                  flush=True)
            C.log_event("generated",
                        character=char_name,
                        label=entry["label"],
                        seed=entry.get("seed"),
                        width=entry.get("width"),
                        height=entry.get("height"),
                        duration_s=round(duration, 1))
            next_id += 1

        except Exception as e:
            print(f"  ERROR on [{entry.get('id')}] {entry.get('label')}: {e}")
            print("  Skipping and continuing...\n")
            # Move the failed entry to the end so we don't infinite-loop on it
            try:
                rest = [
                    e for e in load_yaml(queue_path)
                    if isinstance(e, dict) and e.get("label") != entry["label"]
                ]
                rest.append(entry)
                save_yaml(queue_path, rest, header=QUEUE_HEADER)
            except Exception:
                pass

    batch_duration = time.monotonic() - batch_t0
    print(f"BATCH_END duration_s={batch_duration:.1f} completed={completed}/{total}", flush=True)
    C.log_event("batch_ended",
                character=char_name,
                completed=completed,
                total=total,
                duration_s=round(batch_duration, 1),
                stopped=bool(_stop_requested))
    print(f"Done. Output: {output_dir}")


if __name__ == "__main__":
    main()
