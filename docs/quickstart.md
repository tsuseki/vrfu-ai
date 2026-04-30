# Quickstart

Goal: from a fresh clone, generate your first image of a character your friend has trained for you. Assumes [install.md](install.md) is done.

## 1. Get the LoRA from your friend

Your friend trained a character LoRA. They send you one file:

```
<character_name>.safetensors
```

E.g. `tsu_chocola.safetensors`. It's a few hundred MB.

## 2. Put it in the right place

The project ships with a `demo_character` slot pre-configured. Easiest path:

1. Rename the file to `demo_character.safetensors`
2. Move it to `loras/demo_character/demo_character.safetensors`

(Or use a real character name — see step 4 below for that route.)

## 3. Tell the project what the LoRA looks like

Edit `characters/demo_character/config.yaml`. Two fields you need to fill in:

```yaml
trigger_word: "tsu chocola"      # the trigger your friend used (ask them)
character_tags: "1girl, solo, fox girl, black hair, red eyes, facial mark"
                                  # the canonical visual identity
```

Your friend should have told you what trigger word and what character tags to use. If they didn't, ask. Without these the LoRA fires but the model has no idea what the character "looks like" beyond the LoRA's blurry approximation.

## 4. Launch and click Start

```cmd
launch_website.bat
```

Browser opens at <http://localhost:8765>. The character dropdown shows `demo_character`. The queue tab shows three smoke-test prompts.

Click **▶️ Start run**. Within a minute (3090) or 2–3 minutes (lower-tier GPU), three images appear in the **Review** tab.

## 5. Verify it worked

Switch to **Review → 📥 New**. You should see:
- Three images of the character your friend trained
- Identity correct: face, hair color, ears, eyes match
- No "two girls" issue, no garbled outputs

If those check out: your install is complete and working.

If outputs look wrong (mangled face, multiple subjects, generic anime girl that doesn't match), check:
- Did `trigger_word` match what your friend used?
- Is `character_tags` accurate? Try copying it from your friend's `config.yaml` directly
- Did the LoRA file actually land at `loras/demo_character/demo_character.safetensors`?

## 6. Vote and iterate

For each image, click ❤️ / 👍 if you like it, 👎 to dislike. After voting on a few, click **📦 Organize** — liked images move to `liked/`, the rest to `archive/`.

To make 2K versions of liked images, click **🔼 Upscale liked** on the Liked tab. Auto-picks 2× scale on ≥18 GB GPUs, 1.5× on lower-tier.

## What's next

- **Add more prompts**: switch to Generation tab, click **➕ Add prompt**. The Outfit chips show the named outfits your friend defined; the Popular chips fill with tags from your liked images (refreshes when you click Organize).
- **Add another character your friend sent**: click **➕ New** in the header, give it the character's name, then drop the LoRA at `loras/<name>/<name>.safetensors` and edit `characters/<name>/config.yaml` like in step 3.
- **Train your own**: see [add-character.md](add-character.md).
