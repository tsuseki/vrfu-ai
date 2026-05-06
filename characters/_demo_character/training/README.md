# Demo training set — reference, not yours

These three image+caption pairs are **examples** copied verbatim from the
project author's `tsu_chocola` training set. They're here so you can see
what a real, working LoRA training pair looks like before assembling your
own.

| Pair | What it shows |
|---|---|
| `04-29-26-133739.{png,txt}` | Black bodysuit, sitting on a couch (full body, indoor, dim) |
| `04-29-26-133755.{png,txt}` | Default outfit (camisole + cardigan + shorts + thigh-highs), standing, V-sign (full body, the iconic look) |
| `04-29-26-133826.{png,txt}` | Outdoor terrace, casual cardigan + skirt, evening lighting (full body) |

Open any `.png` and its sibling `.txt` side-by-side — every visible detail
that isn't part of the character's identity is captioned (lighting,
indoor/outdoor, pose, V-sign, clothing items, footwear). The character
identity prefix (`tsu chocola, fox girl, black fox ears, …`) repeats
across all three; only the per-image situational tags vary. That's how the
LoRA learns to generalize: shared anchors fire reliably, varying tags
don't get baked into the character.

## To train your own character from this folder

1. **Delete these three demo pairs** — they're tsu_chocola, not your character.
2. Drop **30–60** images of your character here as `.png` (or `.jpg`).
3. Caption each one with a `.txt` file of the same stem.

Detailed guidance on capture variety, captioning style, and the 77-token
budget lives in **[`characters/_template/training/README.md`](../../_template/training/README.md)**.
For the project-wide tag schema, see [`docs/prompting.md`](../../../docs/prompting.md).

When the captions are done, edit `characters/_demo_character/config.yaml`
to match your character (`trigger_word`, `character_tags`, `outfits`),
then click **🎓 Train LoRA** in the web UI.
