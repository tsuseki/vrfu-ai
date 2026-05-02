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
# BASE_POSITIVE / BASE_NEGATIVE / build_prompt now live in prompt_build.py
# so server.py can import them for the /api/prompt-preview endpoint without
# triggering this file's signal handlers + CUDA imports.
from prompt_build import BASE_POSITIVE, BASE_NEGATIVE, build_prompt, expand_outfits, OutfitNotFoundError  # noqa: F401

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
def load_pipeline_base(cfg: dict):
    """Load the SDXL checkpoint, scheduler, and memory strategy.

    Does NOT load any character LoRA — call load_character_lora() after this
    for the run's starting character. For mixed-character runs, call
    load_character_lora() again on each character switch.
    """
    checkpoint = Path(cfg["checkpoint"])
    if not checkpoint.exists():
        sys.exit(f"ERROR: checkpoint not found at {checkpoint}")

    print(f"Loading SDXL checkpoint: {checkpoint.name}")
    pipe = StableDiffusionXLPipeline.from_single_file(
        str(checkpoint), torch_dtype=torch.float16, use_safetensors=True,
    )
    pipe.scheduler = get_scheduler(pipe, cfg.get("sampler", DEFAULT_SAMPLER))

    # ── Memory strategy ──────────────────────────────────────────────────
    # VAE slicing + tiling: pure compute-time tricks that reclaim the
    # ~3-4 GB peak the VAE decode would otherwise want. No device juggling,
    # no Compel races, full GPU speed.
    #
    # Attention slicing: only enabled below 20 GB total VRAM. SDXL at
    # 1216x832 spikes to ~17 GB at the attention peak; on 16 GB cards that
    # overflows into Sysmem Fallback (silent 40x slowdown). Slicing pays
    # ~5% speed for ~3-5 GB of attention-peak headroom — keeps 16 GB cards
    # in real VRAM. NOT enabled on >=20 GB cards because the speed cost
    # is noticeable and unnecessary there.
    #
    # CPU offload (enable_model_cpu_offload) is NOT used — it on-demand
    # swaps text encoders between CPU/GPU, which races with CompelForSDXL
    # calling them at inference time → device-mismatch retry storm.
    pipe.to("cuda")
    pipe.enable_vae_slicing()
    pipe.enable_vae_tiling()
    total_mib = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
    if total_mib < 20480:
        pipe.enable_attention_slicing("auto")
        print(f"Low-VRAM mode: attention slicing enabled ({total_mib:,} MiB total).")

    img2img = StableDiffusionXLImg2ImgPipeline.from_pipe(pipe)
    return pipe, img2img


def load_character_lora(pipe, cfg: dict, prev_char: str | None = None) -> None:
    """(Re)load the character LoRA + any extras. Used both at startup and on
    cross-character LoRA switches mid-run.

    `prev_char` is the name of the character whose LoRA is currently loaded
    (if any). When switching, we delete the prior 'character' adapter (and
    any extras keyed by name) before loading the new one — peft would
    otherwise stack adapters and silently double-apply the previous one.
    """
    char_lora = Path(cfg["character_lora"])
    if not char_lora.exists():
        sys.exit(f"ERROR: character LoRA not found at {char_lora}")

    # Drop any previously-loaded adapters so we start clean. delete_adapters
    # is best-effort — if nothing's loaded yet (first call), it raises and
    # we just continue.
    if prev_char is not None:
        try:
            pipe.delete_adapters(["character"])
        except Exception:
            pass

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
    action = "Switching to" if prev_char else "Loading LoRA:"
    for lora in loras:
        print(f"{action} {lora['name']:<12} weight={lora['weight']}  ({lora['path'].name})")
        pipe.load_lora_weights(str(lora["path"].parent),
                               weight_name=lora["path"].name,
                               adapter_name=lora["name"])
        adapter_names.append(lora["name"])
        adapter_weights.append(lora["weight"])
    pipe.set_adapters(adapter_names, adapter_weights=adapter_weights)
    # Sampler may differ between characters — re-pick from the new cfg.
    pipe.scheduler = get_scheduler(pipe, cfg.get("sampler", DEFAULT_SAMPLER))


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
# build_prompt + expand_outfits live in prompt_build.py — see top of file


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
# Per-character context (per-entry character routing)
# ───────────────────────────────────────────────────────────────────────────
class CharContext:
    """Bundles all the per-character state the main loop needs.

    Each entry in the queue can specify `character: <name>` to route to a
    different character's LoRA + output folder. We cache the loaded
    contexts so we don't re-read configs on every iteration.
    """
    def __init__(self, name: str):
        self.name        = name
        self.cfg         = C.load_character(name)
        self.char_dir    = C.char_dir(name)
        self.output_dir  = C.output_dir(name)
        self.done_path   = C.done_file(name)
        self.input_dir   = self.char_dir / "input"
        self.last_id     = self.char_dir / "last_id.txt"
        self.done        = load_yaml(self.done_path)
        done_max = max((int(e["id"]) for e in self.done if isinstance(e, dict) and "id" in e), default=0)
        file_max = int(self.last_id.read_text().strip()) if self.last_id.exists() else 0
        self.next_id     = max(done_max, file_max) + 1


def entry_character(entry: dict, default: str) -> str:
    """Resolve which character/LoRA an entry targets. Falls back to the
    queue's owner if the entry doesn't override."""
    return entry.get("character") or default


def pick_next_entry(queue: list[dict], current_char: str | None,
                    run_target: str, order: str) -> dict:
    """Pick the next entry to run.

    order == "character" (default): if there's an entry matching the
    currently-loaded character, prefer it (no LoRA switch). Otherwise
    fall back to first entry.

    order == "original": always return queue[0]. Respects user's manual
    ordering even if it forces a LoRA switch on every iteration.
    """
    if order == "character" and current_char is not None:
        for e in queue:
            if entry_character(e, run_target) == current_char:
                return e
    return queue[0]


# ───────────────────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Generate images from a character's queue.")
    parser.add_argument("--character", help="Character name (folder under characters/)")
    parser.add_argument("--dry", action="store_true", help="Preview queue without generating")
    parser.add_argument("--order", choices=["character", "original"], default="character",
                        help=("character (default): when next entry could be either current-char or "
                              "another, prefer current-char to minimize ~3-5 sec LoRA switches. "
                              "original: respect queue file order verbatim."))
    args = parser.parse_args()

    run_target = C.resolve_default_character(args.character)
    queue_path = C.queue_file(run_target)

    # Per-character context cache. Run-target loaded eagerly; others
    # populated lazily when an entry first routes to them.
    ctx_cache: dict[str, CharContext] = {run_target: CharContext(run_target)}
    def get_ctx(name: str) -> CharContext:
        if name not in ctx_cache:
            ctx_cache[name] = CharContext(name)
        return ctx_cache[name]

    run_ctx = ctx_cache[run_target]
    print(f"=== {run_ctx.cfg.get('character_name', run_target)} ===")
    print(f"Trigger : {run_ctx.cfg['trigger_word']}")
    print(f"Base    : {Path(run_ctx.cfg['checkpoint']).name}")
    print(f"LoRA    : {Path(run_ctx.cfg['character_lora']).name} @ {run_ctx.cfg.get('character_lora_weight', 0.85)}\n")

    queue = [e for e in load_yaml(queue_path) if isinstance(e, dict)]
    if not queue:
        print("Queue is empty. Add prompts to queue.yaml and run again.")
        sys.exit(0)
    print(f"Found {len(queue)} prompt(s) in queue.\n")

    # Count LoRA switches the user is about to incur and warn if --order original
    # would force many switches (could've used --order character to coalesce).
    targets_in_file_order = [entry_character(e, run_target) for e in queue]
    file_switches = sum(1 for i in range(1, len(targets_in_file_order))
                        if targets_in_file_order[i] != targets_in_file_order[i-1])
    unique_chars = sorted(set(targets_in_file_order))
    if len(unique_chars) > 1:
        if args.order == "character":
            print(f"Mixed-character queue: {len(unique_chars)} characters "
                  f"({', '.join(unique_chars)}). --order=character will incur "
                  f"~{len(unique_chars) - 1} LoRA switch(es) (~3-5s each).\n")
        else:
            print(f"Mixed-character queue: {len(unique_chars)} characters. "
                  f"--order=original will incur {file_switches} LoRA switch(es) "
                  f"(~3-5s each). Use --order=character to coalesce to "
                  f"{len(unique_chars) - 1}.\n")

    if args.dry:
        # Simulate ordering exactly as the run loop would
        remaining = list(queue)
        cur_char = None
        while remaining:
            entry = pick_next_entry(remaining, cur_char, run_target, args.order)
            tgt = entry_character(entry, run_target)
            ctx = get_ctx(tgt)
            switch = " (LoRA switch)" if cur_char and cur_char != tgt else ""
            print(f"  [{str(ctx.next_id).zfill(3)}] {entry['label']}  → {tgt}{switch}")
            print(f"       {entry['prompt']}\n")
            ctx.next_id += 1
            cur_char = tgt
            remaining.remove(entry)
        sys.exit(0)

    check_vram()
    pipe, img2img_pipe = load_pipeline_base(run_ctx.cfg)
    load_character_lora(pipe, run_ctx.cfg)
    current_lora_char = run_target
    compel = make_compel(pipe)
    print("Compel weighting active: (term:1.5), [term], etc. respected. "
          "Long prompts (>77 tokens) are chunked and concatenated.\n")

    initial_total = len(queue)
    total = initial_total                # may grow if user adds to queue mid-run
    print(f"BATCH_START total={total}", flush=True)
    C.log_event("batch_started", character=run_target, total=total)
    batch_t0 = time.monotonic()
    completed = 0

    while not _stop_requested:
        # ALWAYS re-read the queue file: takes top entry freshly each iteration,
        # so reordering / new-prepends / deletions take effect immediately.
        queue_now = [e for e in load_yaml(queue_path) if isinstance(e, dict)]
        if not queue_now:
            print("[queue empty — done]", flush=True)
            break
        # Picks next entry per --order policy: in 'character' mode, prefer
        # entries matching the currently-loaded LoRA to avoid a switch.
        entry = pick_next_entry(queue_now, current_lora_char, run_target, args.order)

        # Resolve which character this entry routes to. Switch LoRA if
        # the previous entry was for a different one.
        target_char = entry_character(entry, run_target)
        try:
            ctx = get_ctx(target_char)
        except SystemExit as e:
            # Bad character name — config not found. Skip the entry rather
            # than crashing the whole run.
            print(f"  ERROR resolving character '{target_char}': {e}")
            rest = [x for x in load_yaml(queue_path)
                    if isinstance(x, dict) and x.get("label") != entry["label"]]
            rest.append(entry)
            save_yaml(queue_path, rest, header=QUEUE_HEADER)
            continue

        if target_char != current_lora_char:
            print(f"\n[character switch] {current_lora_char} → {target_char}", flush=True)
            load_character_lora(pipe, ctx.cfg, prev_char=current_lora_char)
            current_lora_char = target_char

        try:
            entry["id"] = ctx.next_id
            output_path, duration, full_prompt, full_negative = generate_image(
                pipe, img2img_pipe, compel, entry, ctx.next_id, ctx.cfg, ctx.output_dir, ctx.input_dir,
            )
            # Mutate ONLY after success — done.yaml gets the actual sent prompt.
            entry["prompt"]       = full_prompt
            entry["negative"]     = full_negative
            entry["output"]       = str(output_path.relative_to(ctx.char_dir))
            entry["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            ctx.done.append(entry)
            ctx.last_id.write_text(str(entry["id"]))

            # Remove the entry we just completed (by label, in case the user reordered
            # or deleted it while we were processing — this is the safe key).
            remaining = [
                e for e in load_yaml(queue_path)
                if isinstance(e, dict) and e.get("label") != entry["label"]
            ]
            save_yaml(queue_path, remaining, header=QUEUE_HEADER)
            save_yaml(ctx.done_path,
                      sorted(ctx.done, key=lambda e: int(e.get("id", 0))),
                      header=DONE_HEADER)

            completed += 1
            # Total = how many we've done + how many remain. May grow if user adds.
            total = max(total, completed + len(remaining))
            # PROGRESS includes target character so the run banner can update.
            print(f"PROGRESS: {completed}/{total} label={entry['label']} char={target_char} seed={entry.get('seed')} dur={duration:.1f}",
                  flush=True)
            C.log_event("generated",
                        character=target_char,
                        label=entry["label"],
                        seed=entry.get("seed"),
                        width=entry.get("width"),
                        height=entry.get("height"),
                        duration_s=round(duration, 1))
            ctx.next_id += 1

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
                character=run_target,
                completed=completed,
                total=total,
                duration_s=round(batch_duration, 1),
                stopped=bool(_stop_requested))
    # Output went to multiple character folders if the queue was mixed.
    output_dirs = sorted({str(c.output_dir) for c in ctx_cache.values()})
    if len(output_dirs) == 1:
        print(f"Done. Output: {output_dirs[0]}")
    else:
        print(f"Done. Output across {len(output_dirs)} character folders:")
        for d in output_dirs:
            print(f"  {d}")


if __name__ == "__main__":
    main()
