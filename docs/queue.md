# Adding Queue Entries (for Claude)

How a Claude session should add entries to the unified queue. Read this
first when the user says "queue these prompts" / "add 50 of X" / "build me
a batch of Y".

For tag schema, prompt ordering, and Illustrious-specific rules, the
canonical reference is **[`docs/prompting.md`](prompting.md)**. This file
covers only the queue-mechanics layer.

---

## 1. Where the queue lives

- **Unified queue file:** `queue.yaml` at the repo root. One queue, every
  character. Each entry has a `character` field naming which LoRA to load.
- **Per-character `characters/<name>/queue.yaml` are legacy** — ignore them.
- **The running web server is the orchestrator.** It reads/writes
  `queue.yaml` through `web/server.py`'s `save_queue()`, which calls
  `_backup_queue()` to keep `queue.yaml.last.bak` and timestamped snapshots
  in `queue.yaml.backups/`.

## 2. Hard rule: do not Edit/Write `queue.yaml` directly

A prior Sonnet sub-agent on an unrelated task wiped ~400 unfinished entries
by overwriting the file. **Always go through the API** so `_backup_queue()`
runs. Two endpoints cover everything:

- `POST /api/queue/import` — bulk add. Body: `{"character": "...", "yaml": "<yaml-list-text>"}`. Appends to the end of the queue.
- `POST /api/queue/update` — modify one entry. Body: `{"character": "...", "label": "...", "fields": {...}}`.
- `POST /api/queue/reorder` — re-sort. Body: `{"character": "...", "labels": [<full-ordered-label-list>]}`. Missing labels get appended at the end.
- `POST /api/queue/delete` — remove. Body: `{"character": "...", "labels": [...]}`.

The **only** legitimate reason to write `queue.yaml` directly is when the
server is down and the user explicitly approved the workaround. In that
case, copy `queue.yaml` to `queue.yaml.last.bak` first by hand.

## 3. Standard recipe — bulk add via Python

Save under `scratch/build_<thing>.py`. The user's `local-only` branch keeps
these out of the public main:

```python
import json, urllib.request, yaml

SERVER    = "http://localhost:8765"
CHARACTER = "tsu_chocola"          # or whichever character

QP = ("masterpiece, best quality, amazing quality, very aesthetic, newest, "
      "absurdres, anime coloring, cel shading")
QS = "very aesthetic, absurdres"

# Build the entry list. Don't include character_tags here — they're
# prepended at generation time from characters/<name>/config.yaml.
entries = []
for i, scenario in enumerate(SCENARIOS, start=1):
    prompt = ", ".join([
        QP,
        f"artist:{scenario.artist}",            # required for tsu_chocola
        "1girl, solo, sensitive",
        scenario.outfit_tags,                    # see §5
        scenario.scene,
        scenario.framing,
        scenario.background,
        QS,
    ])
    entries.append({
        "label":     f"<theme>-{i:02d}",         # unique, kebab-case
        "character": CHARACTER,
        "prompt":    prompt,
        "width":     1024,                       # 1024 / 1216 / 832 only
        "height":    1024,
        # "negative": "...",                     # optional, inherits BASE_NEGATIVE
        # "seed":     12345,                     # optional
    })

yaml_text = yaml.dump(entries, allow_unicode=True, sort_keys=False, default_flow_style=False)
payload = json.dumps({"character": CHARACTER, "yaml": yaml_text}).encode()
req = urllib.request.Request(f"{SERVER}/api/queue/import", data=payload,
    headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=30) as r:
    print(json.loads(r.read()))
```

**To prepend** (run next instead of last): import as above, then re-fetch
the full queue, build a labels list with the new labels first and existing
ones after, and POST `/api/queue/reorder`.

## 4. Anatomy of a queue entry

```yaml
- label: kebab-case-descriptive   # required, unique. Server appends -2 on collision.
  character: tsu_chocola          # required (pick the right LoRA)
  prompt: |
    masterpiece, best quality, amazing quality, ...,
    artist:nardack,               # check the character's config for whether
                                  # an artist tag is required (see §6)
    1girl, solo, sensitive,
    <outfit upper-body tags>,     # see §5 — DO NOT use {outfit:name} placeholders
    <expression / pose / framing>,
    <background / lighting>,
    very aesthetic, absurdres
  width:  1024                    # 1024 / 1216 / 832 — Illustrious is trained on these
  height: 1024
  negative: ""                    # optional. Omit to inherit BASE_NEGATIVE.
```

**Resolution constraint:** stick to **1024×1024**, **1216×832** (landscape),
or **832×1216** (portrait). Off-list ratios degrade the model.

**`character` field** picks the LoRA. The runner looks up
`characters/<character>/config.yaml`, reads `character_tags` and
`negative_tags`, and prepends/merges them with the entry's prompt at
generation time. **Do not repeat `character_tags` in your prompt** — that
just dilutes the leading tokens.

## 5. The close-up rule (lower-body cleanup)

If the entry's framing is **`close-up`**, **`face focus`**, **`bust shot`**,
**`upper body`**, **`head shot`**, or **`portrait`**, strip every
lower-body tag from the prompt. Otherwise the model wedges miniature feet
or shoes into the corner of the frame.

Tags to **remove** when framing is above-waist:

- footwear / toes: `barefoot`, `shoes`, `sneakers`, `boots`, `sandals`, `heels`, `socks`, `thigh highs`, `red toenails`, `feet`, `toes`
- bottoms: `pants`, `shorts`, `jeans`, `denim shorts`, `drawstring shorts`, `skirt`, `pleated skirt`, `panties`, `tights`, `leggings`
- lower body: `legs`, `thighs`, `crotch`, `groin`, `ass`, `hip focus`

If you mention `midriff` or `navel`, that's the floor — anything
geographically below it should not appear.

For wider framings (`cowboy shot`, `full body`), the rule inverts: include
lower-body tags so the model has a target.

## 6. Reading the user's preferences before writing prompts

The user votes on every generated image (super_like / love / like / style
/ location / pose / outfit / dislike / anatomy_issue, plus free-form
comments). **These signals are how you learn what they actually want.**
When asked to "queue more like the liked ones" or "more X but better",
read the signals first.

Pulling liked images for a character:

```python
import json, urllib.request, urllib.parse
char = "tsu_chocola"
url = f"http://localhost:8765/api/images?view=liked&character={urllib.parse.quote(char)}&limit=200"
with urllib.request.urlopen(url, timeout=15) as r:
    images = json.loads(r.read())["images"]

# Each image has: filename, stem, prompt, negative, votes (dict), comment,
# artists (list parsed from prompt), character, generated_at, etc.
```

What to extract:

- **`artists`** field per image: which `artist:NAME` tags fire well for
  this character? Frequency across liked vs archive is a clean signal.
- **Framing tokens in `prompt`**: count occurrences of `close-up`,
  `bust shot`, `upper body`, `cowboy shot`, `full body` across liked.
  If `bust shot` shows up 3× more in liked than archive, bias new
  prompts toward bust shots.
- **Outfit tags**: which named outfits or specific clothing items
  recur in liked? Drop the ones that only show up in archive.
- **Vote-type breakdown**: `votes.style: True` means "I liked the style
  specifically" — that's a stronger artist signal than a generic
  `votes.like`. `votes.pose: True` means the pose was the win.
- **Comments**: `comment` field is the user's own free-form notes.
  Read them; they often contain explicit guidance ("the eyes are
  off-model" / "love this lighting" / "do more like this").

Pulling negative signals:

```python
url = f"http://localhost:8765/api/images?view=archive&character={urllib.parse.quote(char)}&limit=200"
```

Patterns frequent in archive but absent in liked = patterns to **avoid**
in new prompts. Same goes for `anatomy_issue` votes — if many archived
images have `artist:X` and `anatomy_issue=True`, downweight or skip
artist X.

When you propose a new batch back to the user, **say which liked
patterns informed it.** Something like *"Pulling from your 50 liked
affection-set images: 32 have artist:nardack, 28 are bust-shot framing,
12 have heart-shaped pupils with high blush — biasing the new batch
that direction."* That makes your proposal auditable and the user can
correct your reading before you queue 50 entries.

## 7. Per-character context to load before writing prompts

Always read `characters/<name>/config.yaml` before queueing for a
character. Important fields:

- **`character_tags`** — auto-prepended; do not repeat.
- **`negative_tags`** — auto-merged into negatives; usually safe to leave alone.
- **`outfits`** — named outfit dictionary. Queue entries can use
  `{outfit:name}` placeholders (the runner expands them) **OR** write the
  outfit tags inline. Inline is required when the close-up rule applies —
  the placeholder expands to the FULL outfit (with shorts/shoes/etc.) and
  you can't strip the lower-body half from a placeholder. When inlining,
  copy only the upper-body subset of the outfit's tag string.
- **Top-of-file comments** — read them. Per-character quirks live there
  (e.g. tsu_chocola needs an `artist:NAME` tag on every prompt because the
  v2 LoRA was trained on grey-bg VRChat shots and renders plasticky-3D
  without one).

## 8. Things that bite

- **`1girl, solo`** must be near the front of every prompt; **`2girls,
  multiple girls, multiple views, split screen`** belong in the negative
  (or trust BASE_NEGATIVE to provide them — it does, but verify if you're
  customizing).
- **Labels must be unique.** The server appends `-2`, `-3`, ... on
  collision but readable per-theme labels (`crying-04` not `entry-237`)
  are still better.
- **Kemonomimi ear position** for fox/cat/etc. characters: add `flattened
  ears` for fear/anger/shyness, `drooping ears` for sad/sleepy. Default
  upright ears suit happy/neutral. The LoRA's training caption usually
  doesn't anchor ear position, so the tag is the only handle.
- **Artist tag fidelity tradeoff:** `artist:NAME` pulls the character
  toward that artist's style and away from the LoRA. Default to no artist
  tag *unless* the character config specifically requires one (see §6).
- **Resolution-dependent generation cost:** 1216×832 ≈ 25% slower than 1024².
  When queueing 50+ entries, default to 1024² unless the user wants
  landscape/portrait specifically.

## 9. Pitfalls that cost generations

| Symptom | Cause | Fix |
|---|---|---|
| Two characters appear | `2girls`/`multiple girls` not in negative | Always add to negative (BASE_NEGATIVE usually has it; verify if customizing) |
| Phantom feet/shoes in close-up | Lower-body tags + close-up framing | See §5 |
| Character looks generic / off-model | Strong `artist:` tag swamping the LoRA | Drop the artist tag, or weight it down `(artist:NAME:0.8)` |
| White / two-tone tail on a solid-tail char | Missing tags in negative | Add `white tail tip, two-tone tail, multicolored tail` to negative — or rely on the character's `negative_tags` in config.yaml |
| Cropped head | Composition tags fighting framing | Add `(cropped head:1.4)` to negative |
| Kemonomimi ears stay upright when mood calls for droop | LoRA default is upright; no ear tag = no change | Add `drooping ears` (sad/sleepy) or `flattened ears` (scared/angry/shy) per anime convention |
| Off resolution | Non-standard width/height | Stick to 1024² / 1216×832 / 832×1216 |

### Remix flow (Review tab → Remix button)

The UI's **Remix** button copies a liked image's prompt into a new queue
entry. When remixing programmatically or guiding the user:

1. Copy the prompt **but drop the seed** — remix = fresh roll on the same concept.
2. Append a meaningful suffix to the label (`-v2`, `-cozy`, etc.) instead of the default `-remix`.
3. Re-check §5 (close-up rule). If the user is changing framing from full-body to close-up, strip lower-body tags the original had.

## 10. After building — verify and report

```python
# After import
import json, urllib.request
with urllib.request.urlopen(f"{SERVER}/api/queue", timeout=10) as r:
    q = json.loads(r.read())["queue"]
from collections import Counter
print(f"queue size: {len(q)}")
print("by prefix:", Counter(e["label"].rpartition("-")[0] for e in q))
print("first 5:", [e["label"] for e in q[:5]])
```

Tell the user what's queued, in what order, and what the first 3-5 labels
are so they know what they'll see first when generation starts.

## 11. Cross-references

- **Tag schema and prompt-ordering:** [`docs/prompting.md`](prompting.md) — read this before introducing tags you haven't used here before
- **Curated artist tags that work well:** [`docs/artist-palette.md`](artist-palette.md)
- **Folder layout, full API reference:** [`docs/reference.md`](reference.md)
- **Persistent project memory** (per-character quirks, prompt corrections from prior sessions):
  `~/.claude/projects/F--AI-Art/memory/MEMORY.md`. Skim this before any
  prompt work — it's where prior corrections live.
