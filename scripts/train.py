"""
Train a character LoRA via ai-toolkit.

Reads:  characters/<character>/training_config.yaml
Spawns: python C:\\Programs\\ai-toolkit\\run.py <training_config.yaml>
Writes: F:\\vrfu-ai\\loras\\characters\\<name>_v1\\<name>_v1.safetensors

Usage:
    python train.py --character cocoa_mizu

Prints a structured PROGRESS line per training step so the website can
parse it for the live banner:

    PROGRESS: 250/2000 step=250 loss=0.143
    BATCH_START total=2000
    BATCH_END duration_s=14400
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import _common as C  # noqa: E402

# Force UTF-8 on our own stdout/stderr so we can relay ai-toolkit's progress
# bars (which contain Unicode block chars like █) without Windows cp932
# choking. errors="replace" turns any straggler into "?" instead of crashing.
for stream in (sys.stdout, sys.stderr):
    try:
        if stream.encoding and stream.encoding.lower() not in ("utf-8", "utf8"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ai-toolkit is a git submodule at the repo root. Friends cloning with
# --recursive get the source automatically; setup.bat builds the venv on
# their machine (gitignored — too big and machine-specific).
_PROJECT_ROOT  = Path(__file__).resolve().parent.parent
AI_TOOLKIT_DIR = _PROJECT_ROOT / "ai-toolkit"
AI_TOOLKIT_RUN = AI_TOOLKIT_DIR / "run.py"
VENV_PYTHON    = AI_TOOLKIT_DIR / "venv" / "Scripts" / "python.exe"


def find_training_config(character: str) -> Path:
    p = C.char_dir(character) / "training_config.yaml"
    if not p.exists():
        sys.exit(f"ERROR: no training_config.yaml at {p}\n"
                 f"Create one (see characters/tsu_chocola/training_config.yaml for a template).")
    return p


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a character LoRA via ai-toolkit.")
    parser.add_argument("--character", help="Character name (folder under characters/)")
    parser.add_argument("--no-archive", action="store_true",
                        help="Don't auto-archive an existing LoRA folder before retraining (retrain in place)")
    args = parser.parse_args()

    char_name = C.resolve_default_character(args.character)
    cfg_path  = find_training_config(char_name)

    # Read total steps so we can compute progress
    with cfg_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    total_steps = (
        cfg.get("config", {}).get("process", [{}])[0]
           .get("train", {}).get("steps", 0)
    )
    out_dir = C.LORAS / char_name
    print(f"=== Training {char_name} ===")
    print(f"Config:        {cfg_path}")
    print(f"Total steps:   {total_steps}")
    print(f"Output LoRA:   {out_dir / f'{char_name}_v1.safetensors'}")
    print()

    # Pre-flight: ai-toolkit silently skips training if optimizer.pt exists
    # at or past total_steps (sees the run as already complete, just regenerates
    # samples — produced confusing "training succeeded in 90 seconds" no-ops).
    # Auto-archive an existing finished LoRA into <name>/archived_<date>/ so
    # the new run starts clean AND prior versions stay together with the
    # active one inside the same character folder.
    optimizer_pt = out_dir / "optimizer.pt"
    final_lora = out_dir / f"{char_name}.safetensors"
    if optimizer_pt.exists() and final_lora.exists() and not args.no_archive:
        archive_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_dir = out_dir / f"archived_{archive_suffix}"
        print(f"Archiving existing LoRA contents into: {archive_dir.name}")
        archive_dir.mkdir(parents=True, exist_ok=True)
        # Move every file/folder at the top of out_dir EXCEPT existing archives
        for item in list(out_dir.iterdir()):
            if item.name.startswith("archived_") or item == archive_dir:
                continue
            item.rename(archive_dir / item.name)
        C.log_event("lora_archived", character=char_name,
                    archived_to=str(archive_dir))
        print()

    if not AI_TOOLKIT_RUN.exists():
        sys.exit(f"ERROR: ai-toolkit not found at {AI_TOOLKIT_RUN}")

    # Spawn ai-toolkit. Run from its own directory so its imports resolve.
    cmd = [str(VENV_PYTHON), str(AI_TOOLKIT_RUN), str(cfg_path)]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"

    print(f"BATCH_START total={total_steps}", flush=True)
    C.log_event("training_started", character=char_name, total_steps=total_steps,
                config=str(cfg_path))
    t0 = time.monotonic()

    proc = subprocess.Popen(
        cmd,
        cwd=str(AI_TOOLKIT_RUN.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        bufsize=1,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    # ai-toolkit prints lines like:
    #   "step 250/2000 loss: 0.1234 ..."  or
    #   "100%|██| 250/2000 [..., loss=0.123]"
    # We tolerate either form by extracting any X/Y pair plus loss=N where present.
    pat_step = re.compile(r"(\d+)\s*/\s*(\d+)")
    pat_loss = re.compile(r"loss[:=]?\s*([0-9.]+)", re.IGNORECASE)

    last_step = 0
    try:
        for line in proc.stdout:
            line = line.rstrip()
            try:
                print(line, flush=True)
            except UnicodeEncodeError:
                # Last-ditch: scrub any leftover non-encodable chars
                print(line.encode("ascii", "replace").decode("ascii"), flush=True)
            m_step = pat_step.search(line)
            m_loss = pat_loss.search(line)
            if m_step:
                cur = int(m_step.group(1))
                tot = int(m_step.group(2))
                # Only emit a structured PROGRESS line if the step number advanced
                # (the progress bar redraws many times per step otherwise).
                if cur != last_step and 1 <= cur <= tot and tot >= 100:
                    last_step = cur
                    loss = m_loss.group(1) if m_loss else ""
                    print(f"PROGRESS: {cur}/{tot} step={cur} loss={loss}", flush=True)
                    if cur % 250 == 0:
                        C.log_event("training_step", character=char_name,
                                    step=cur, total=tot, loss=loss or None)
    except KeyboardInterrupt:
        proc.terminate()
        print("\n[interrupted]", flush=True)

    proc.wait()
    duration = time.monotonic() - t0

    # Post-flight: an exit-0 run that completes far faster than the expected
    # per-step pace (~1.2-2 s/step on this rig) is almost certainly a no-op.
    # Surface it loudly so it can't masquerade as success — the most common
    # cause is a stale optimizer.pt; the pre-flight check above should now
    # prevent it, but warn anyway in case something else slips through.
    expected_min_seconds = total_steps * 0.5  # half-second per step floor
    is_suspicious_no_op = (
        proc.returncode == 0
        and total_steps >= 100
        and duration < max(expected_min_seconds, 120)
    )
    if is_suspicious_no_op:
        print()
        print("=" * 60)
        print(f"  WARNING: training completed in {duration:.1f} seconds")
        print(f"  Expected at least {expected_min_seconds:.0f}s for {total_steps} steps.")
        print(f"  This run probably did NOT actually train — a stale")
        print(f"  optimizer.pt or finished LoRA likely caused ai-toolkit")
        print(f"  to skip straight to 100%. Archive the output folder and")
        print(f"  retry, or pass --force.")
        print("=" * 60)
        print()

    print(f"BATCH_END duration_s={duration:.1f} exit_code={proc.returncode}", flush=True)
    C.log_event("training_ended", character=char_name,
                duration_s=round(duration, 1),
                exit_code=proc.returncode,
                suspicious_no_op=is_suspicious_no_op)
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
