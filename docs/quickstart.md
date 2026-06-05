# Quickstart

Goal: from a fresh clone, get your first generated image — by setting up a
character you have a LoRA for (one you trained, or one a friend sent you).
Assumes [install.md](install.md) is done (`setup.bat` ran, base SDXL checkpoint
downloaded).

State lives in a local SQLite database (`vrfu.db`) that's created automatically
the first time you launch — nothing to initialize by hand.

> **Just want the full how-to?** Open the **Docs** tab in the website (or
> [docs/add-character.md](add-character.md)). The repo also ships a hidden
> `characters/_demo_character/` folder — a complete worked example (config +
> captioned training images) you can study to see how a real character is wired
> up. It doesn't show in the dropdown; it's reference material.

## 1. Launch the website

```cmd
launch_website.bat
```

Browser opens at <http://localhost:8765>. On a fresh install the character
dropdown is **empty** — you add your first character next.

## 2. Add your character

In the header, click **➕ New**, enter a name (lowercase, e.g. `cocoa_mizu`).
This scaffolds the character **and registers it in the database**, so it appears
in the dropdown right away. Then put the LoRA file at
`loras/<name>/<name>.safetensors` (e.g. `loras/cocoa_mizu/cocoa_mizu.safetensors`).

*Got a whole character bundle from a friend instead of a bare LoRA?* Use the
**📥 Import** button on the Characters tab — it unpacks the bundle and registers
it for you. See [exporting.md](exporting.md).

## 3. Tell the project what the character looks like

Open the **Characters** tab, select your character, and fill in:

- **`trigger_word`** — the unique token the LoRA fires on (ask your friend).
- **`character_tags`** — the canonical visual identity, e.g.
  `1girl, solo, fox girl, black hair, red eyes, facial mark`. These are
  prepended to every prompt, so they're the LoRA's "always-on" features.
- **`outfits`** (optional) — named outfits you can reference in prompts as
  `{outfit}` / `{outfit:name}`.

Click **Save** — the Characters page writes straight to the database (it does
*not* edit a YAML file). Without `trigger_word` + `character_tags` the LoRA
fires but the model has no idea what the character looks like.

## 4. Add a prompt and Start

Generation tab → **➕ Add prompt** (a couple of simple ones to test). Click
**▶️ Start run**, then switch to **Review → 📥 New**: images appear within a
minute on a 3090, 2–3 min on lower-tier GPUs.

## 5. Verify it worked

In **Review → 📥 New** you should see:

- Images of your character, identity correct (face, hair, ears, eyes match)
- No "two girls" issue, no garbled outputs

If outputs look wrong (mangled face, multiple subjects, a generic anime girl
that doesn't match), check:

- Did `trigger_word` match what the LoRA was trained on?
- Is `character_tags` accurate?
- Did the LoRA land at `loras/<name>/<name>.safetensors`?

## 6. Vote and iterate

For each image click ❤️ / 👍 if you like it, 👎 to dislike. After voting on a
few, click **📦 Organize** — liked images move to `liked/`, the rest to
`archive/`. Click **🔼 Upscale liked** on the Liked tab to make 2K versions.

## What's next

- **Train your own character** (no LoRA yet): see [add-character.md](add-character.md)
  — covers training images, captioning (with a browser tagger), and the LoRA
  training run.
- **Write better prompts**: [prompting.md](prompting.md) and the **➕ Add prompt**
  chips (Outfit chips show your defined outfits; Popular chips fill with tags
  from your liked images).
