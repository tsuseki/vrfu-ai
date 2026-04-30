# Training images go here

Drop **30–50** reference images of your character into this folder. PNG or JPG, any resolution (the trainer downscales to 512/768/1024 buckets automatically).

## What makes a good training set

- **Varied poses** — face close-ups, half-body, full-body, side, back
- **Varied outfits** — at least 1 reference shot per outfit you want the LoRA to know
- **Consistent identity** — same character across all images (don't mix in lookalikes)
- **Bare feet shots** if you want feet to fire — at least 5–10 with feet clearly visible (otherwise the LoRA learns "this character is upper-body content")
- **Avoid** sticker sheets, screenshots of UIs, multi-character composites — these confuse the LoRA

## Captioning

Every image needs a `.txt` file next to it with the same name, e.g. `pose_001.png` ↔ `pose_001.txt`.

The caption should be a comma-separated list of Danbooru-style tags:

```
my_trigger_word, 1girl, solo, fox girl, black fox ears, white camisole, black shorts,
sitting on bed, indoor, looking at viewer, blush, three quarter view
```

**Keep captions under ~60 tokens.** ai-toolkit truncates at 77 tokens during training; if your prefix is too long, the per-image specific tags (outfit, pose, scene) get silently dropped and the LoRA never learns them.

## Example pair (from tsu_chocola)

`example_caption.txt`:
```
tsu chocola, fox girl, black fox ears, black fox tail, black hair, red eyes, red feather hair ornament, solo, simple background, grey background, white camisole, black shorts, black cardigan, off shoulder, barefoot, red toenails, long hair, side braid, full body, standing, facing viewer, blush
```

The character's identity prefix (fox girl, black ears, etc.) repeats across every caption; only the per-image specifics (outfit, pose, expression, framing) vary.

## After captioning

Once you have 30+ image+caption pairs in this folder:

1. Edit `config.yaml` — set `trigger_word`, `character_tags`, and `outfits.default`
2. Click **🎓 Train LoRA** in the website
3. Wait ~55 minutes
4. The trained LoRA lands at `loras/characters/<name>_v1/<name>_v1.safetensors`
5. Add a few smoke-test prompts to `queue.yaml` and click ▶️ Start
