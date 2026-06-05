# Quickstart

Goal: from a fresh clone, generate your first image — either with the bundled
demo or with a character a friend trained for you. Assumes [install.md](install.md)
is done (`setup.bat` ran, base SDXL checkpoint downloaded).

State lives in a local SQLite database (`vrfu.db`) that's created automatically
on first launch — there's nothing to initialize by hand. The shipped character
configs (including the demo) are seeded into it the first time you start the
website.

## 1. Launch the website

```cmd
launch_website.bat
```

Browser opens at <http://localhost:8765>. On this first run the app seeds the
demo character into `vrfu.db`, so the character dropdown shows **`_demo_character`**
with three smoke-test prompts already queued. `_demo_character` is a complete,
worked example — the author's `tsu_chocola` config — so you can see what a
fully set-up character looks like.

- **If you have the `tsu_chocola` LoRA:** drop it at
  `loras/tsu_chocola/tsu_chocola.safetensors`, then click **▶️ Start run** — the
  three demo prompts generate (under a minute on a 3090, 2–3 min on lower-tier
  GPUs). Skip to step 4.
- **Otherwise**, set up the character your friend sent you:

## 2. Add your friend's character

Your friend trained a LoRA and sent you one file, e.g. `cocoa_mizu.safetensors`
(a few hundred MB).

1. In the website header click **➕ New** and enter the character's name (lowercase,
   e.g. `cocoa_mizu`). This scaffolds the character **and registers it in the
   database**, so it appears in the dropdown immediately.
2. Drop the LoRA at `loras/<name>/<name>.safetensors`
   (e.g. `loras/cocoa_mizu/cocoa_mizu.safetensors`).

## 3. Tell the project what the LoRA looks like

Open the **Characters** tab, select your character, and fill in:

- **`trigger_word`** — the trigger your friend used (ask them).
- **`character_tags`** — the canonical visual identity, e.g.
  `1girl, solo, fox girl, black hair, red eyes, facial mark`.

Click **Save** — the Characters page writes straight to the database (it does
*not* edit a YAML file). Without these the LoRA fires but the model has no idea
what the character "looks like" beyond the LoRA's blurry approximation.

Then add a couple of prompts: **Generation → ➕ Add prompt**, or copy the demo's
smoke tests.

## 4. Click Start and verify

Click **▶️ Start run**, then switch to **Review → 📥 New**. You should see:

- Images of the character (the demo's tsu_chocola, or your friend's character)
- Identity correct: face, hair color, ears, eyes match
- No "two girls" issue, no garbled outputs

If that checks out, your install is complete and working.

If outputs look wrong (mangled face, multiple subjects, a generic anime girl
that doesn't match), check:

- Did `trigger_word` match what your friend used?
- Is `character_tags` accurate? Ask your friend for the exact string.
- Did the LoRA file actually land at `loras/<name>/<name>.safetensors`?

## 5. Vote and iterate

For each image, click ❤️ / 👍 if you like it, 👎 to dislike. After voting on a
few, click **📦 Organize** — liked images move to `liked/`, the rest to `archive/`.

To make 2K versions of liked images, click **🔼 Upscale liked** on the Liked tab.
Auto-picks 2× scale on ≥18 GB GPUs, 1.5× on lower-tier.

## What's next

- **Add more prompts**: Generation tab → **➕ Add prompt**. The Outfit chips show
  the named outfits defined in the character's config; the Popular chips fill
  with tags from your liked images (refreshes when you click Organize).
- **Receive a whole character bundle from a friend**: see
  [exporting.md](exporting.md) (receiver section) — the 📥 Import button unpacks
  it and registers it in the database for you.
- **Train your own**: see [add-character.md](add-character.md).
