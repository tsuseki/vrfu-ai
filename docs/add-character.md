# Adding a new character

Full setup walkthrough — from blank slate to a trained LoRA generating images.

## 1. Click "➕ New" next to the character dropdown

In the website header (top right) there's a `➕ New` button. Click it.

A modal opens asking for a name. Use lowercase letters, digits, and underscores only — e.g. `cocoa_mizu`, `ren_takeda`, `my_oc`. The name becomes the folder under `characters/` and the trigger word for the LoRA, so pick something **unique** that the base model doesn't already know (don't use real anime character names if you want your own identity to dominate).

Click **Create**. The site:
- Scaffolds `characters/<name>/` from `characters/_template/`
- Fills in the placeholders with your chosen name
- Switches the active character to the new one

## 2. Drop training images into `characters/<name>/training/`

You need **30–50 reference images** of the character. Tips for a good set:
- Vary the poses: face close-ups, half-body, full-body, side, back
- Vary the outfits: at least 1 reference shot per outfit you want the LoRA to know
- Show **bare feet** in 5–10 of them if you want feet to fire well (otherwise the LoRA learns "this character is upper-body content" and ignores `foot focus` later)
- Same character in every image (don't mix in lookalikes)
- **Avoid** sticker sheets, screenshot grids, multi-character composites, UI screenshots

PNG or JPG, any resolution. The trainer downscales to 512/768/1024 buckets automatically.

### Shot-type breakdown for a 30-image set

If you want a target distribution rather than just "vary the poses", aim for
roughly:

| Shot type | Count | Notes |
|---|---|---|
| Front, full body | 3–4 | Neutral pose, arms visible |
| Front, upper body | 3–4 | Waist up, face clearly visible |
| ¾ left, upper body | 3–4 | Most useful angle for anime art |
| ¾ right, upper body | 3–4 | |
| Side profile | 2–3 | Left and right |
| Close-up face | 3–4 | Fill the frame with the face |
| Back view | 1–2 | Hair / outfit details |
| Full body, varied poses | 3–4 | T-pose, A-pose, casual stand, sitting |

**Background:** plain solid colour (white, grey, or any flat backdrop) beats
busy scenes. Cluttered backgrounds end up weakly anchored to the character.

### Capturing references inside VRChat

If your character is a VRChat avatar:

- Use VRChat's **in-game camera** (not a screenshot) with background-blur
  enabled — gives clean depth-of-field and a smooth backdrop.
- Pick a world with a plain or low-detail backdrop (a studio world, an empty
  unity demo scene, a solid-colour skybox). Avoid worlds with text, signage,
  or busy patterns behind you.
- Lock the camera then cycle through poses/expressions instead of moving the
  camera each shot — gives consistent framing across a set.
- Shoot at 1024×1024 or higher; crop later if needed. Sharper input = sharper
  LoRA.

## 3. Caption every image

Each `<image>.png` needs a `<image>.txt` next to it with comma-separated Danbooru tags.

**Caption schema** (see `docs/PROMPTING.md` for details):
```
<trigger_word>, 1girl, solo, <key identity tags>, <outfit tags>, <pose>, <scene>, <expression>, <framing>
```

**Example** (from tsu_chocola — see `characters/_template/training/example_caption.txt`):
```
tsu chocola, fox girl, black fox ears, black fox tail, black hair, red eyes,
red feather hair ornament, solo, simple background, grey background,
white camisole, black shorts, black cardigan, off shoulder, barefoot,
red toenails, long hair, side braid, full body, standing, facing viewer, blush
```

**Critical: keep captions under ~60 tokens.** ai-toolkit truncates at 77 tokens. If your identity prefix is too long, the per-image specific tags (outfit, pose, scene) get silently dropped and the LoRA never learns them.

### Captioning options

- **Browser tagger (easiest, no install)** — drop each image into a WD14 tagger
  web app like **[SmilingWolf/wd-tagger](https://huggingface.co/spaces/SmilingWolf/wd-tagger)**.
  It returns Danbooru-style tags; paste them into the image's `.txt`, then tidy:
  put your `trigger_word` first, drop wrong tags, keep it under ~60 tokens.
- **Manual** — type each `.txt` by hand. Slow but precise; fine for a small set.
- **Helper script** — loop over the images and write the shared identity prefix
  automatically, then hand-edit per-image specifics. Good when most images share
  the same identity tags.

For a worked example, open the captioned images in
`characters/_demo_character/training/` — each `.png` has a sibling `.txt` so you
can see exactly which tags map to which image. Whichever route you take,
**review every caption before training** — wrong tags = wrong LoRA.

## 4. Fill in the character's config

Creating the character already seeded its config (template defaults) into the
`character_config` table in `vrfu.db` — that's what the runtime reads, not the
file. The **easiest way to fill in your real values** is the **Characters**
page in the UI: it edits `character_name`, `trigger_word`, `character_tags`,
`negative_tags`, `character_lora_weight`, `sampler`, and `outfits`, and saves
straight to the DB. The fields you're setting:

```yaml
character_name: My Character          # Pretty display name
trigger_word:   "my character"        # Must match what's in your captions

character_tags: "1girl, solo, fox girl, blue eyes, long blonde hair"
                # ↑ The visual identity that should fire on every prompt.
                # Keep tight (~10 tags). Don't repeat what trigger word implies.

outfits:
  default: "white camisole, black shorts, off shoulder"
  # Add named outfits as you discover them:
  # bikini:  "white bikini"
  # winter:  "black sweater, knit cap"
```

**`character_tags`** gets auto-prepended to every prompt, so it's the LoRA's "always-on" features.
**`outfits`** are the named outfit bundles you can reference in queue prompts as `{outfit}` (default) or `{outfit:bikini}`. `generate.py` expands these at gen time.

> **Prefer the form, or re-sync if you hand-edit.** The Characters page writes
> the DB directly. If you'd rather edit `characters/<name>/config.yaml` in a
> text editor (e.g. to set a field the form doesn't expose), your changes won't
> take effect until you re-sync them into the DB:
> `ai-toolkit\venv\Scripts\python.exe scripts\migrate_to_db.py` (idempotent —
> imports every `characters/*/config.yaml`). Don't do both at once: editing the
> file and re-running migrate will overwrite whatever you changed in the form.

## 5. (Usually skip) Edit `training_config.yaml`

The template's defaults (rank 32, 2000 steps, lr 1e-4) work for most characters. You only need to touch this if:
- You want a different rank (16 = lighter, 64 = stronger but heavier)
- You want fewer or more training steps
- You're training on FLUX instead of SDXL

## 6. Click 🎓 Train LoRA

In the website header, switch to your new character in the dropdown if it isn't already, then go to the Generation page and click **🎓 Train LoRA**.

- Takes ~55 minutes on a 3090, ~50 min on a 4070 Ti Super
- The wrapper auto-archives any prior LoRA at `loras/<name>/archived_<date>` so you can compare or roll back
- Live progress shows in the run banner
- If you check **⛓ Auto-start gen after training**, the queue runs automatically when training finishes

## 7. Smoke-test prompts

Before writing 100 prompts, do 3–5 test prompts to verify the LoRA learned what you wanted. Add them through the **Add Prompt** modal in the UI (or `POST /api/queue/import`) — the queue lives in `vrfu.db`, so don't hand-edit a file. The entries look like:

```yaml
- label: smoke-portrait
  prompt: 1girl, solo, sensitive, {outfit}, looking at viewer, upper body, simple background, white background, very aesthetic, absurdres
  width: 832
  height: 1216
  negative: 2girls, multiple girls, multiple views, (cropped head:1.4), bad anatomy, bad hands, deformed, lowres, worst quality

- label: smoke-fullbody
  prompt: 1girl, solo, sensitive, {outfit}, full body, standing, simple background, white background, very aesthetic, absurdres
  width: 832
  height: 1216
  negative: 2girls, multiple girls, multiple views, (cropped head:1.4), bad anatomy, bad hands, deformed, lowres, worst quality
```

Click ▶️ Start. After they generate, check the New tab:
- Identity correct? (face, hair color, ears, etc.)
- Outfit firing when `{outfit}` is in the prompt?
- If "no" to either, the captions or `character_tags` need work — see `docs/PROMPTING.md`'s troubleshooting section.

## 8. Build out the queue

Once smoke tests look right, write 50–400 real prompts. Use the chip suggestions in the **Add Prompt** modal — the **Outfit** chips show your defined outfits, the **Popular** chips show tags from your liked images (computed every time you click Organize).

## 9. Vote → Organize → Upscale → Iterate

The standard daily loop:
1. **▶️ Start run** to chew through the queue
2. Switch to **Review** → 📥 New tab → vote ❤️/👍 on what you like
3. **📦 Organize** to move liked → `liked/`, the rest → `archive/`
4. **🔼 Upscale liked** to make 2K versions
5. As you vote, the **Popular tags** chip suggestions improve — use them to write smarter follow-up prompts

## What's where on disk

```
characters/<name>/
├── config.yaml             ← seed for the DB config (edit, then migrate_to_db.py)
├── training_config.yaml    ← rarely edit
├── training/               ← drop training images + captions here
├── output/                 (auto, generated images)
├── archive/                (auto, post-Organize rejects)
├── liked/                  (auto, post-Organize favorites)
├── liked_upscaled/         (auto, 2K versions)
└── logs/                   (auto, training/upscale/run logs)

loras/<name>/<name>.safetensors    ← your trained LoRA
loras/<name>/archived_<date>/         ← prior versions (auto-archived on retrain)
```

## Multi-character notes

- The dropdown and stats are per-character; everything is isolated except the base SDXL checkpoint and ai-toolkit (one install shared across all characters)
- LoRAs are independent — training one doesn't affect others
- State (queue, done, votes, activity) is global — one `vrfu.db` — but every row carries a `character` field, so characters stay isolated
