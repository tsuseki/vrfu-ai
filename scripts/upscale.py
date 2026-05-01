"""
Hires-fix upscaler for liked images (SDXL img2img).

Reads PNGs from `characters/<char>/liked/`, runs each through SDXL img2img at
~0.40 denoise on a 2x resized source. Output goes to `characters/<char>/liked_upscaled/<stem>_2k.png`.

After each successful upscale, the source moves from `liked/` to `liked/liked_archive/`
so the next run skips it.

Usage:
    python upscale.py --character tsu_chocola
    python upscale.py --character tsu_chocola --stems 244_kantoku-witch       # one image
    python upscale.py --character tsu_chocola --stems s1,s2,s3                 # several images
    python upscale.py --src-file "F:/path/to/file.png" --character X --stem-as 244_x
        # off-tree single-shot (used by web's "Upscale now" button)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Force UTF-8 stdout/stderr so em-dashes etc. don't crash on Windows cp932/cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import torch
import yaml

# ── peft + torchao version-mismatch workaround ─────────────────────────────
# See generate.py for full explanation. ai-toolkit pins torchao==0.10.0 (only
# version compatible with the torch 2.5.1 it requires); peft hard-raises on
# torchao < 0.16.0 even when we don't use torchao-quantized LoRAs. Patch the
# check to return False instead of raising.
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
    try:
        from peft.tuners.lora import torchao as _peft_lora_torchao
        _peft_lora_torchao.is_torchao_available = _safe
    except Exception:
        pass
_patch_peft_torchao_check()

from compel import CompelForSDXL
from diffusers import StableDiffusionXLImg2ImgPipeline, EulerAncestralDiscreteScheduler
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import _common as C  # noqa: E402

# ── Hires-fix parameters ───────────────────────────────────────────────────
DENOISE = 0.40   # 0.30-0.45 sweet spot — preserves composition, adds detail
STEPS   = 22
GUIDANCE = 6.0
LORA_WEIGHT = 0.85
MIN_FREE_VRAM_MIB = 8000
SUFFIX = "_2k"


def auto_pick_scale(cfg: dict) -> float:
    """Pick the upscale factor based on the character's config (if set) or
    available VRAM. SDXL hires-fix at 2x peaks ~13–15 GB; scale 1.5x peaks ~9–11 GB.

    Override via config.yaml: `upscale_scale: 1.5` (or 2.0).
    Default behaviour: auto = 2.0 if total VRAM ≥ 18 GB else 1.5.
    """
    explicit = cfg.get("upscale_scale")
    if isinstance(explicit, (int, float)) and explicit > 0:
        return float(explicit)
    try:
        total_gib = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        return 2.0 if total_gib >= 18 else 1.5
    except Exception:
        return 1.5  # safe default if VRAM probe fails


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
            print(f"\nWARNING: only {free:,} MiB free — need >={MIN_FREE_VRAM_MIB:,} for 2048x2048.\n")
    except Exception:
        pass


def load_done_index(character: str) -> dict[str, dict]:
    """Build label -> done.yaml entry map for prompt lookup."""
    p = C.done_file(character)
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    return {e["label"]: e for e in raw if isinstance(e, dict) and "label" in e}


def append_upscale_log(character: str, record: dict) -> None:
    log_path = C.upscaled_log_file(character)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if log_path.exists() and log_path.stat().st_size > 0:
        existing = yaml.safe_load(log_path.read_text(encoding="utf-8")) or []
    if not isinstance(existing, list):
        existing = []
    existing.append(record)
    with log_path.open("w", encoding="utf-8") as f:
        f.write("# UPSCALED IMAGES — auto-managed log\n")
        yaml.dump(existing, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def build_pipe(cfg: dict):
    checkpoint = Path(cfg["checkpoint"])
    char_lora  = Path(cfg["character_lora"])
    print(f"Loading checkpoint: {checkpoint.name}")
    pipe = StableDiffusionXLImg2ImgPipeline.from_single_file(
        str(checkpoint), torch_dtype=torch.float16, use_safetensors=True,
    )
    pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)
    print(f"Loading LoRA: {char_lora.name} @ {LORA_WEIGHT}")
    pipe.load_lora_weights(str(char_lora.parent), weight_name=char_lora.name, adapter_name="character")
    pipe.set_adapters(["character"], adapter_weights=[LORA_WEIGHT])
    # Same VRAM strategy as generate.py: skip enable_model_cpu_offload
    # because it races with CompelForSDXL (text encoders bounce to CPU
    # between calls and trigger device-mismatch errors). VAE slicing +
    # tiling are always safe and reclaim the 3-4 GB peak that the VAE
    # decode at higher upscale resolutions would otherwise want.
    # 16 GB users hitting OOM at 2.0x can drop to 1.5x or 1.25x via the
    # website's new scale picker.
    pipe.to("cuda")
    pipe.enable_vae_slicing()
    pipe.vae.enable_tiling()
    # CompelForSDXL hooks into the pipeline's offload mechanism so encoders
    # used here move with the rest of the pipeline. The old Compel(...) ctor
    # takes direct refs to text_encoder objects and breaks under
    # enable_model_cpu_offload (encoders bounce to CPU but Compel keeps
    # feeding CUDA token tensors → "Expected all tensors to be on the
    # same device" errors that cost 10s/image in retry/recovery).
    compel = CompelForSDXL(pipe)
    print("Pipeline ready (with Compel weighting).\n")
    return pipe, compel


def upscale_one(pipe, compel, png: Path, out_path: Path, entry: dict,
                scale: float = 2.0) -> tuple[float, tuple[int, int]]:
    """Run hires-fix on a single PNG. Returns (duration_s, (out_w, out_h))."""
    prompt   = entry.get("prompt", "")
    negative = entry.get("negative", "")
    try:
        seed = int(entry.get("seed")) if entry.get("seed") is not None else 0
    except (TypeError, ValueError):
        seed = 0

    src = Image.open(png).convert("RGB")
    src_w, src_h = src.size
    tgt_w = int(src_w * scale) // 8 * 8
    tgt_h = int(src_h * scale) // 8 * 8
    tgt = src.resize((tgt_w, tgt_h), Image.LANCZOS)
    gen = torch.Generator("cuda").manual_seed(seed) if seed else None
    torch.cuda.empty_cache()

    # Encode prompts via CompelForSDXL — single call returns matched-length
    # positive + negative embeddings with proper (term:1.5) weighting and
    # long-prompt chunking. The wrapper handles offloaded text encoders.
    enc = compel(main_prompt=prompt or "", negative_prompt=negative or "")

    t0 = time.monotonic()
    result = pipe(
        prompt_embeds=enc.embeds, pooled_prompt_embeds=enc.pooled_embeds,
        negative_prompt_embeds=enc.negative_embeds,
        negative_pooled_prompt_embeds=enc.negative_pooled_embeds,
        image=tgt, strength=DENOISE, num_inference_steps=STEPS,
        guidance_scale=GUIDANCE, generator=gen,
    ).images[0]
    result.save(out_path)
    return time.monotonic() - t0, (tgt_w, tgt_h)


def main() -> None:
    parser = argparse.ArgumentParser(description="SDXL hires-fix upscaler.")
    parser.add_argument("--character", help="Character name (folder under characters/)")
    parser.add_argument("--stems", help="Comma-separated list of stems to process; default = all of liked/")
    parser.add_argument("--src-file", help="Process a single PNG path directly (off-tree mode)")
    parser.add_argument("--stem-as", help="Treat --src-file as having this stem (for output naming)")
    parser.add_argument("--scale", type=float, default=None,
                        help="Override upscale factor (e.g. 1.25, 1.5, 2.0). "
                             "Falls back to config.yaml's upscale_scale, then VRAM auto-pick.")
    args = parser.parse_args()

    char_name = C.resolve_default_character(args.character)
    cfg       = C.load_character(char_name)
    liked     = C.liked_dir(char_name)
    archive   = C.liked_archive_dir(char_name)
    out_dir   = C.upscaled_dir(char_name)
    archive.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Determine the work list
    if args.src_file:
        src_path = Path(args.src_file)
        if not src_path.exists():
            sys.exit(f"ERROR: --src-file not found: {src_path}")
        stem_label = args.stem_as or src_path.stem
        work = [(src_path, stem_label, False)]   # don't move source after
    else:
        if not liked.exists():
            sys.exit(f"ERROR: liked folder not found: {liked}")
        all_pngs = sorted(p for p in liked.glob("*.png") if p.is_file())
        if args.stems:
            wanted = {s.strip() for s in args.stems.split(",") if s.strip()}
            pngs = [p for p in all_pngs if p.stem in wanted]
        else:
            pngs = all_pngs
        # Skip ones already SDXL-upscaled
        pngs = [p for p in pngs if not (out_dir / f"{p.stem}{SUFFIX}.png").exists()]
        work = [(p, p.stem, True) for p in pngs]

    if not work:
        print("Nothing to do.")
        return

    print(f"Found {len(work)} image(s) to upscale.\n")
    check_vram()
    pipe, compel = build_pipe(cfg)
    done_idx = load_done_index(char_name)

    if args.scale and args.scale > 0:
        scale = float(args.scale)
        scale_source = "CLI flag"
    else:
        scale = auto_pick_scale(cfg)
        scale_source = "config override" if cfg.get("upscale_scale") else "VRAM auto-pick"
    print(f"Upscale factor: {scale}x  ({scale_source})\n")

    failures: list[str] = []
    total = len(work)
    print(f"BATCH_START total={total}", flush=True)
    C.log_event("upscale_started", character=char_name, total=total,
                model="SDXL hires-fix", scale=scale)
    batch_t0 = time.monotonic()

    for i, (png, stem, move_after) in enumerate(work, start=1):
        # Look up the original prompt (strip leading "NNN_" if present)
        label = stem.split("_", 1)[1] if "_" in stem and stem.split("_", 1)[0].isdigit() else stem
        entry = done_idx.get(label, {})
        out_path = out_dir / f"{stem}{SUFFIX}.png"

        try:
            print(f"  [{i}/{total}] {stem} -> {out_path.name}")
            duration, (tw, th) = upscale_one(pipe, compel, png, out_path, entry, scale)

            if move_after:
                shutil.move(str(png), str(archive / png.name))

            append_upscale_log(char_name, {
                "stem": stem,
                "denoise": DENOISE,
                "src_dim": list(Image.open(out_path).size),  # already saved at out
                "out_dim": [tw, th],
                "seed": entry.get("seed"),
                "generated_at": entry.get("generated_at"),
                "upscaled_at": datetime.now().isoformat(timespec="seconds"),
                "duration_s": round(duration, 1),
                "model": "SDXL hires-fix",
            })
            print(f"PROGRESS: {i}/{total} label={label} dur={duration:.1f}", flush=True)
            C.log_event("upscaled", character=char_name, stem=stem,
                        duration_s=round(duration, 1))
        except Exception as e:
            print(f"      ERROR: {e}")
            failures.append(stem)

    batch_duration = time.monotonic() - batch_t0
    print(f"BATCH_END duration_s={batch_duration:.1f} completed={total - len(failures)}/{total}",
          flush=True)
    C.log_event("upscale_ended", character=char_name,
                completed=total - len(failures), total=total,
                duration_s=round(batch_duration, 1))
    print(f"\nDone. {total - len(failures)} upscaled.")
    if failures:
        print("Failures:")
        for s in failures:
            print(f"  - {s}")


if __name__ == "__main__":
    main()
