# Queue Building Guide

How to add entries to the **unified queue** (`queue.yaml` at project root) so
they generate the way you want and don't fight the LoRA.

> **Companion doc:** [`prompting.md`](prompting.md) is the canonical reference
> for tag schema, ordering, and prompt structure. This guide layers
> queue-specific conventions on top of it.

---

## 1. The non-negotiable rules

These come from prior burn-in (corrections that were saved to memory after the
output went sideways). Break them and you'll lose generations.

1. **`1girl, solo` goes near the front** of every entry. `2girls`, `multiple
   girls`, `multiple views`, `split screen` go in the **negative** prompt — even
   if you'd think "1girl" is enough. The model produces stray pairs without it.
2. **`{outfit}` is a placeholder** that the prompt builder substitutes from the
   character's outfit dictionary. Use `{outfit:cozy}`, `{outfit:school}`,
   `{outfit:swimsuit}`, etc. *Never* hard-code outfit tags inline if the
   character has a dictionary entry for that mood.
3. **Default to `noart` (no `artist:` tag).** Adding `artist:NAME` pulls the
   character away from its LoRA and trades fidelity for style. Only add an
   artist tag when you specifically want that style transfer and accept the
   fidelity hit.
4. **Labels** must be unique, kebab-case, descriptive of the *concept* not the
   index. `cozy-couch-mug-noart` is good; `entry-42` is not. The runner appends
   `-2`, `-3`, … on collision but readable labels still beat collision-fixed
   numbers.
5. **Resolution sticks to the trained list.** `1024×1024`, `1216×832` (landscape),
   `832×1216` (portrait). Don't invent dimensions — wai/Illustrious was trained
   on these and degrades off-list.

## 2. The close-up rule (lower-body cleanup)

**If the entry has `close-up`, `face focus`, `bust shot`, `upper body`, `head
shot`, or `portrait` framing, strip ALL lower-body tags.** The model will try
to fit everything you mention into the frame and you'll get phantom feet stuck
to the side of the head, miniature shoes in the corner, etc.

Tags to **remove** when framing is close-up / above-waist:

- Footwear: `barefoot`, `shoes`, `sneakers`, `boots`, `sandals`, `heels`,
  `socks`, `thigh highs`, `stockings`
- Toes / feet: `red toenails`, `painted toenails`, `feet`, `toes`, `foot focus`
- Bottoms: `pants`, `shorts`, `jeans`, `denim shorts`, `drawstring shorts`,
  `skirt`, `pleated skirt`, `panties`, `tights`, `leggings`
- Lower body in general: `legs`, `thighs`, `crotch`, `groin`, `ass`, `hip
  focus`, `wide hips`, `spread legs`

What's safe to keep above-waist: shirt/top, jacket/cardigan, accessories,
hair, expression, hand gestures, background, lighting.

**Mnemonic:** *"close-up = above the navel; everything below the navel is
gone."* If your prompt mentions `midriff` or `navel`, that's the floor.

## 3. Anatomy of a queue entry

```yaml
- label: kebab-case-descriptive-label   # required, unique
  prompt: |
    masterpiece, best quality, amazing quality, very aesthetic, newest, absurdres,
    anime coloring, cel shading,
    1girl, solo, sensitive,
    {outfit:cozy},
    upper body, looking at viewer, soft smile,
    living room, dim lamp light, cozy atmosphere,
    very aesthetic, absurdres
  width: 1024                            # 1024 / 1216 / 832 only
  height: 1024
  negative: |                            # optional — omit to use BASE_NEGATIVE
    2girls, multiple girls, multiple views, split screen,
    bad anatomy, bad hands, extra digits
  character: tsu_chocola                 # optional — inherits run target if absent
  seed: 12345                            # optional — random if absent
  steps: 28                              # optional — defaults from run config
  guidance: 5.5                          # optional — defaults from run config
```

**Fields:**

- `label` (required): unique, kebab-case
- `prompt` (required): full prompt string (the runner does NOT auto-prepend
  quality / character tags — write everything you want generated)
- `width`, `height` (required): one of the 3 trained resolutions
- `negative` (optional): leave off to inherit `BASE_NEGATIVE` from
  `generate.py`. Add only when you need *extra* exclusions on top of the base.
- `character` (optional): targets a specific LoRA. Omit when the run is for
  one character and you want the entry to inherit.
- `seed`, `steps`, `guidance` (optional): runtime overrides

## 4. Building entries from existing liked images (remix flow)

The Review tab's **Remix** button builds a queue entry from a liked image's
prompt. When remixing:

1. The remix copies the prompt **but not the seed** — it's a fresh roll on the
   same concept.
2. The label gets `-remix` suffixed; rename it to something more specific if
   you're going to make several variants.
3. **Re-check section 2** after remixing — if you change framing from full-body
   to close-up, rip out the lower-body tags the original had.

## 5. Pitfalls that cost generations

| Symptom | Cause | Fix |
|---|---|---|
| Two characters appear | `2girls`/`multiple girls` not in negative | Always add to negative |
| Phantom feet/shoes in close-up | Lower-body tags + close-up framing | See section 2 |
| Character looks generic / off-model | Strong `artist:` tag swamping the LoRA | Drop the artist tag, or weight it down `(artist:NAME:0.8)` |
| White / two-tone tail when the char has a solid tail | Missing `white tail tip, two-tone tail, multicolored tail` in negative | Add those to negative |
| Cropped head | Composition tags fighting framing | Add `(cropped head:1.4)` to negative |
| Off resolution | Non-standard width/height | Stick to 1024² / 1216×832 / 832×1216 |
| Kemonomimi ears stay upright when emotion calls for droop | LoRA default is upright; no ear tag = no change | Add `flattened ears, drooping ears` for sad/crying/scared/embarrassed; the ears mirror mood in anime convention |

## 6. Safety: don't let agents touch the queue file directly

`queue.yaml` is **gitignored** and lives only on disk. It has been wiped by
agents before. Two safeguards are in place:

1. **`save_queue()` writes a backup before every overwrite** (see
   `web/server.py` → `_backup_queue`). The previous version is at
   `queue.yaml.last.bak`. Shrink-trigger snapshots land in
   `queue.yaml.backups/queue.YYYYMMDD-HHMMSS.yaml` (rolling 20).
2. **Sub-agents and one-off scripts should add entries via the API**
   (`POST /api/queue/add`) rather than rewriting `queue.yaml` directly, so the
   server-side backup runs.

When recovering from a wipe:

```bash
# 1-step undo:
cp queue.yaml.last.bak queue.yaml

# Pick a specific snapshot:
ls queue.yaml.backups/
cp queue.yaml.backups/queue.20260505-090700.yaml queue.yaml

# Restart the server so the new file is read.
```

## 7. When you build entries with Claude

Read this guide first, then `prompting.md`, then check the character's
`config.yaml` for the outfit dictionary and any character-specific quirks.
Always preview a small batch (2–3 entries) before queueing 50+ to catch
prompt-template issues early.
