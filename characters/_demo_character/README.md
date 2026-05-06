# Demo character

This folder is a **worked example** copied straight from the project author's
character `tsu_chocola`. It exists so a fresh installer can:

1. Verify the install works end-to-end **without** having to train a LoRA first.
2. See exactly how `config.yaml`, training captions, and outfits are wired up
   on a real character before setting up their own.

It is intentionally **not** runnable as-is: there's no LoRA file at the path
this config points to. The .png/.txt pairs in `training/` are reference
material, not a generation target.

## What's in this folder

```
_demo_character/
├── config.yaml          ← Copied verbatim from characters/tsu_chocola/.
│                          Real production config — outfits, character_tags,
│                          LoRA path, weight, sampler, negative tags.
├── training/
│   ├── 04-29-26-133739.png + .txt   ← Black bodysuit, sitting (couch)
│   ├── 04-29-26-133755.png + .txt   ← Default outfit, standing (full body)
│   └── 04-29-26-133826.png + .txt   ← Outdoor casual (terrace)
│                                      All SFW. Each .png has a sibling .txt
│                                      with the booru-style caption used for
│                                      LoRA training. Compare image ↔ caption
│                                      to see what tags map to what.
└── queue.yaml           ← Smoke-test prompts.
```

## To turn this into a working character

You're either pointing the config at someone else's LoRA, or training your
own. Three things need to match:

### 1. Drop a LoRA file at the configured path

`config.yaml` currently points to `loras/tsu_chocola/tsu_chocola.safetensors`.
Either:
- **Use someone else's LoRA:** rename their .safetensors so the path matches,
  or edit `character_lora` in config.yaml to wherever you put the file.
- **Train your own:** put 30–60 reference images of your character in
  `training/` (delete the demo ones first), caption them as `.txt` files
  with the same stem as each .png, edit `training_config.yaml`, then click
  🎓 Train LoRA in the web UI.

### 2. Make `trigger_word` and `character_tags` match what the LoRA was trained on

The current values describe `tsu_chocola`. If you're using a different LoRA,
change them:

```yaml
trigger_word:   "your trigger here"        # the unique token the LoRA fires on
character_tags: "1girl, solo, ..."         # visual anchors used in the LoRA's training captions
```

These are **prepended to every prompt** at generation time (see
`scripts/generate.py` → `prompt_build.py`). Mismatched tags = LoRA fires
weakly and outputs drift off-character.

### 3. Replace or keep the outfit dictionary

`outfits:` is a per-character dict for `{outfit:name}` placeholder
substitution in queue prompts. `default` is what `{outfit}` (no name) expands
to. Each value is a comma-separated tag list for that look. The demo
inherits tsu_chocola's wardrobe; replace each entry with tags that match
your character's actual outfits, or your queue prompts will read like one
character wearing another's clothes.

## What the captions teach you

Open one of the `.txt` files next to its `.png`. Captions follow the
[Illustrious / Danbooru tag schema](../../docs/prompting.md): one comma-separated
list, no sentences, ordered loosely by subject → appearance → clothing →
pose → scene. Notice that `tsu chocola` (the trigger token) leads, then
identity anchors, then situational tags. **Every visible detail** that
isn't part of the character's identity should be captioned (lighting, pose,
indoor/outdoor, etc.) — that's what gives the LoRA the flexibility to
generalize.

One thing the captions deliberately do **not** include: the cheek diamond
markings. The character has them visually but they're absent from the
caption tags, so the LoRA ties them to the character's holistic look but
without an explicit anchor — they fire inconsistently. This is a real
trade-off, documented in the comment at the top of `config.yaml`. Add the
appropriate tag (`facial mark, red diamond facial mark`) to your captions
before training if you want that feature reliable.
