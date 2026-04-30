# Prompting Guide: Illustrious / NoobAI / Pony SDXL Fine-tunes

Practical guide for prompting Danbooru-trained SDXL fine-tunes, with focus on
**waiIllustriousSDXL_v1.7.0** (the model used in this project). Most rules apply
equally to Illustrious-XL, NoobAI-XL, and other Illustrious-family checkpoints.
Pony differs significantly and is called out where relevant.

---

## 1. Prompt Structure and Order

### The canonical Illustrious tag schema

Trained ordering from the Illustrious paper / model cards:

```
[person count] | [character names] | [rating] | [general tags] | [artist] | [score] | [year]
```

### Practical order to write prompts in

Prefer this order in the actual prompt string. The model was trained on tags in
roughly this layout, and putting them in the right place makes each tag stronger:

1. **Quality tags** — `masterpiece, best quality, amazing quality`
2. **Aesthetic tags** — `very aesthetic, newest`
3. **Rating tag** — `safe`, `sensitive`, `nsfw`, or `explicit` (one of)
4. **Artist tag(s)** — `artist:wlop` style; or LoRA trigger words
5. **Subject count** — `1girl`, `1boy`, `2girls`, `solo`, `multiple girls`
6. **Character / series** — `hatsune miku, vocaloid` (character first, copyright after)
7. **Body / appearance** — `long hair, blue eyes, fox ears, tail`
8. **Clothing** — `school uniform, white shirt, pleated skirt`
9. **Pose / action / expression** — `wariza, hands on lap, smile, looking at viewer`
10. **Scene / background** — `engawa, traditional japanese house, cherry blossoms`
11. **Composition / camera** — `from above, dutch angle, cowboy shot`
12. **Lighting / effects** — `volumetric lighting, lens flare, depth of field`
13. **Resolution boosters** — `absurdres, highres`

Order matters but is not absolute. The first ~20 tokens carry the most weight.
Put the things you care about most near the front (after the quality block).

### "Tags first, sentences last" hybrid

Illustrious 1.1+ supports ~50% natural language. Pure sentence prompts work
worse than tags. If you mix, put tags first and a short clarifying sentence
near the end, not the other way around.

---

## 2. Quality Booster Tags

### What actually works on each model

| Tag                | Illustrious / WAI | NoobAI    | Pony v6 |
|--------------------|-------------------|-----------|---------|
| `masterpiece`      | yes               | yes       | weak    |
| `best quality`     | yes               | yes       | weak    |
| `amazing quality`  | yes (WAI-trained) | minor     | no      |
| `very aesthetic`   | yes (strong)      | yes       | no      |
| `aesthetic`        | yes (mid tier)    | yes       | no      |
| `very awa`         | minor             | yes       | no      |
| `absurdres`        | yes (resolution)  | yes       | weak    |
| `highres`          | yes               | yes       | minor   |
| `newest`           | yes               | yes       | no      |
| `year 2024`        | minor             | minor     | no      |
| `score_9, score_8_up, score_7_up` | no  | no        | **required** |
| `8k, 4k, ultra HD` | no — outdated     | no        | no      |

**Key takeaways:**

- For waiIllustriousSDXL_v1.7.0, this canonical stack is correct:
  `masterpiece, best quality, amazing quality, very aesthetic, absurdres`
- Adding `newest` shifts toward modern Danbooru aesthetic (post-2021).
- Adding `year 2024` is mostly redundant with `newest` but doesn't hurt.
- `very awa` is a Noobvrfu-aiifact (from the AestheticAttention dataset). Works
  weakly on Illustrious-derived models.
- **Do not** use Pony's `score_9, score_8_up, score_7_up, score_6_up, score_5_up,
  score_4_up` block on Illustrious — it does nothing or actively hurts.
- **Do not** use generic "8k, 4k, ultra HD, photorealistic" — these were never
  Danbooru tags and act as noise.

### Aesthetic tier (Illustrious / NoobAI)

Trained as a percentile ranking. The full ladder, high to low:

```
very aesthetic > aesthetic > displeasing > very displeasing > worst aesthetic
```

Use `very aesthetic` positive, `displeasing, very displeasing` negative.

### Year / recency tier

Maps to Danbooru upload date:

| Tag       | Years      |
|-----------|------------|
| `newest`  | 2021–2024  |
| `recent`  | 2018–2020  |
| `mid`     | 2014–2017  |
| `early`   | 2011–2014  |
| `oldest`  | 2005–2010  |

Use `newest` positive, `oldest, early` negative for modern-anime look.
Drop `newest` if you want a 2010s vibe.

---

## 3. Negative Prompts

### Recommended baseline (waiIllustriousSDXL)

The model card's official short version:

```
bad quality, worst quality, worst detail, sketch, censor
```

### Stronger general-purpose negative

```
lowres, worst quality, low quality, bad quality, normal quality,
displeasing, very displeasing, worst aesthetic, oldest, early,
sketch, jpeg artifacts, signature, watermark, artist name, username, logo,
bad anatomy, bad hands, bad proportions, deformed, mutated,
extra digits, extra fingers, fewer digits, missing fingers,
blurry, chromatic aberration, artistic error, scan, censor
```

### Add for specific issues

- **Hands going wrong:** `bad hands, mutated hands, extra fingers, missing fingers,
  fused fingers, deformed hands`
- **Face going wrong:** `bad face, deformed face, asymmetrical eyes, cross-eyed`
- **Multiple subjects bleeding:** `multiple views, split screen, comic, panels`
- **Furry leaking in:** `furry, anthro, mammal, feral, semi-anthro, ambiguous form`
  (NoobAI especially needs this; Illustrious less so)
- **Style accidents:** `monochrome, greyscale, sepia` (if you want color)

### Don't pile on

Negatives are not free. Each one slightly steers the model and consumes
attention. If you don't have a problem, don't put a fix in. Start minimal,
add tags as you see specific failure modes.

### Pony differs

Pony's negative usually starts with the inverse of its score tags:
`score_6, score_5, score_4, source_pony, source_furry`. Do not transfer this
to Illustrious.

---

## 4. Tag Weighting Syntax

### What's universal across A1111-style UIs

```
(tag)            -> weight 1.1
((tag))          -> weight 1.21  (1.1^2)
(((tag)))        -> weight 1.331
(tag:1.3)        -> explicit weight 1.3
(tag:0.7)        -> de-emphasize to 0.7
[tag]            -> weight 0.9   (A1111 / Forge / ComfyUI native)
[[tag]]          -> 0.81
```

### What works in Diffusers + Compel (your pipeline)

Compel supports two syntaxes:

**A1111-compatible (recommended):**

```python
# Just write your prompt with parentheses and weights — Compel parses it
"masterpiece, best quality, (very aesthetic:1.2), 1girl, (long hair:1.1), [background:0.8]"
```

**Compel-native +/- syntax:**

```
cat+++           # equivalent to (cat:1.331)
cat--            # equivalent to (cat:0.826)
("subject", "style").and(1.0, 0.5)   # blend two segments
```

### BREAK keyword

Splits the prompt into separate 75-token chunks that get encoded independently
and concatenated. Useful when one concept's attention is bleeding into another.

```
1girl, fox ears, white kimono BREAK
engawa, traditional japanese house, cherry blossoms, evening
```

In Compel: use `("...", "...").and()` to achieve the equivalent.

### Practical weighting rules

- Stay in `0.7–1.4`. Outside that range you usually get artifacts before you get
  the effect you wanted.
- For LoRA trigger words, weight `1.0–1.2` is normal. Going `>1.4` on a trigger
  often distorts the character.
- De-emphasize background or style tags (`:0.8`) if they're hijacking the subject.
- Don't weight quality tags. They're already strong; pushing `(masterpiece:1.5)`
  produces over-baked images.

---

## 5. Danbooru Tag Conventions

### Use the actual Danbooru tag, not the English word

The model only knows what was in training captions. If a concept exists on
Danbooru, the model knows the Danbooru tag. The English synonym usually doesn't
work, or works much weaker.

| Concept               | Right (Danbooru)  | Wrong / weak       |
|-----------------------|-------------------|--------------------|
| Japanese porch        | `engawa`          | `veranda`, `porch` |
| Side-sit (legs folded)| `wariza`          | `sitting sideways` |
| Formal kneel          | `seiza`           | `kneeling`         |
| Shrine gate           | `torii`           | `shrine gate`      |
| Tilted camera         | `dutch angle`     | `tilted shot`      |
| Three-quarter view    | `from side`       | `profile shot`     |
| Waist-up framing      | `cowboy shot`     | `medium shot`      |
| Above-the-shoulder    | `from above`      | `bird's eye view`  |
| Hand under chin       | `hand on own chin`| `thinking pose`    |
| Floor-length dress    | `long dress`      | `floor length gown`|

When in doubt, search the tag at <https://danbooru.donmai.us/tags?search[name_matches]=...>
and check the post count. >1k posts = the model knows it. <100 posts = unreliable.

### Underscores: drop them

Danbooru stores tags as `long_hair`, `from_above`. In prompts, use spaces:
`long hair, from above`. Both work in most pipelines (the tokenizer treats them
similarly), but **spaces are the convention** on Civitai and what guides
recommend. Do not invent your own spelling.

### Compound vs separate tags

The model has both `school uniform` (compound) and `pleated skirt, white shirt`
(components). Use the compound when it exists — it's cleaner training signal.
Add component tags only to specify variations:

```
good:  school uniform, red ribbon, black thighhighs
bad:   white shirt, dark blazer, red bowtie, pleated skirt, knee-high socks
```

### Tag namespaces

Danbooru namespaces (`artist:`, `character:`, `copyright:`, `meta:`) are NOT
typically used in prompts. Just write the bare name:

```
good:  hatsune miku, vocaloid, wlop
bad:   character:hatsune_miku, copyright:vocaloid, artist:wlop
```

Exceptions: a few NoobAI variants accept `artist:name` formatting. Check the
specific model card. For waiIllustrious, plain names.

### Pose / composition cheat sheet

**Sitting:** `sitting`, `seiza`, `wariza`, `indian style`, `crossed legs`,
`kneeling`, `on stomach`, `on back`, `lying`, `all fours`, `squatting`

**Standing / action:** `standing`, `walking`, `running`, `jumping`,
`leaning forward`, `leaning back`, `arms up`, `arms behind back`,
`hand on hip`, `hands on hips`

**Camera angle:** `from above`, `from below`, `from side`, `from behind`,
`dutch angle`, `pov`, `straight-on`

**Framing:** `portrait`, `upper body`, `cowboy shot` (mid-thigh up),
`full body`, `wide shot`, `close-up`, `face focus`

**Subject focus:** `looking at viewer`, `looking away`, `looking down`,
`looking back`, `eye contact`

---

## 6. Tools and Databases for Finding Tags

- **Danbooru tag search** — <https://danbooru.donmai.us/tags>
  Search by prefix, see post counts, sort by popularity. The ground truth.
- **Danbooru wiki** — <https://danbooru.donmai.us/wiki_pages>
  Definitions and disambiguations. Great for "what's the difference between
  X and Y" questions.
- **a1111-sd-webui-tagcomplete** — <https://github.com/DominikDoom/a1111-sd-webui-tagcomplete>
  Browser-side autocomplete. Ships `danbooru.csv` and `e621.csv`. The CSVs
  themselves are useful as a standalone reference even outside A1111. Updated
  CSVs on Civitai (search "updated danbooru.csv").
- **e621 tags** — <https://e621.net/tags> — for furry/animal content tag
  conventions. NoobAI was trained on e621 data so e621 tags work there.
- **Civitai prompt galleries** — every model page has user-submitted
  generations with full prompts. The fastest way to learn what works on a
  specific checkpoint: copy three good examples, diff their prompts, keep the
  shared tags.
- **rule34.xxx / gelbooru** — share tag conventions with Danbooru, useful as
  cross-reference if a tag is missing from Danbooru's wiki.
- **ComfyUI-EasyNoobai** — <https://github.com/regiellis/ComfyUI-EasyNoobai>
  Node that builds canonical NoobAI/Illustrious prompts with preset
  quality/year/aesthetic stacks. Useful even just to read its source for the
  preset strings.

---

## 7. Common Mistakes

- **Long descriptive sentences instead of tags.**
  `"a beautiful young woman with long flowing silver hair standing in a peaceful
  forest at sunset"` is much weaker than
  `"1girl, long hair, silver hair, standing, forest, sunset, dappled sunlight"`.

- **Mixing model conventions.**
  Don't put `score_9, score_8_up` on Illustrious. Don't put `masterpiece, best
  quality` first on Pony if you've already given it the score block.

- **Quality tags everywhere.**
  Repeating `masterpiece, best quality, masterpiece` does not stack. Once is
  enough.

- **Using English synonyms over Danbooru tags.**
  See section 5. `kneeling` and `seiza` are not the same thing to this model.

- **Conflicting tags.**
  `short hair, long hair` — model averages, you get medium. `smile, sad` —
  ambiguous expression. Pick one.

- **Wrong tag namespace.**
  `artist:greg_rutkowski` — Greg isn't a Danbooru artist tag. Illustrious knows
  Pixiv-active anime illustrators (`wlop`, `as109`, `mika pikazo`, etc.).

- **Underscores in artist tag separators inconsistently.**
  Pick a style and stick with it. `mika pikazo` works; `mika_pikazo` works;
  `mika-pikazo` doesn't.

- **Negative prompt bloat.**
  Copying a 200-token "ultimate negative" from a Civitai post can hurt more
  than it helps. Start with the short list in section 3, add per-issue.

- **Stacking too many LoRAs / characters.**
  Two LoRAs at 1.0 each often produces mush. Use `0.7–0.85` per LoRA when
  combining; more than three concurrent LoRAs is rarely good.

- **Trusting tags with low post counts.**
  If a Danbooru tag has <100 posts, the model probably has not learned it.
  Use a more common synonym or describe with components.

---

## 8. Illustrious-Specific Gotchas

- **CFG should be lower than you think.** Sweet spot is 4.5–6.0 for v1.x.
  Above 7.5 you start getting saturation and artifacts. WAI v1.7 recommends
  CFG 7 — that's the upper limit, not a default. Try 5.5 first.

- **Steps:** 24–30 is plenty. Beyond ~35 you're wasting compute.

- **Sampler:** Euler A is the safest default. DPM++ 2M Karras and DPM++ SDE
  Karras also work. Avoid DDIM.

- **Resolution:** Native is 1024×1024 area. Stick to the SDXL bucket sizes:
  `1024×1024, 832×1216, 1216×832, 896×1152, 1152×896, 768×1344, 1344×768`.
  Off-bucket sizes (e.g., 1024×1280) cause anatomy issues.

- **Illustrious 2.0** stabilizes 1536px generation. **1.x and WAI 1.7 do not** —
  generating directly at 1536² produces duplicated bodies. Generate at 1024
  area, then upscale with hires-fix or a separate upscaler pass.

- **Natural-language input is partial.** v1.0/WAI handles tags only well; v1.1+
  understands ~50% NLP. Don't write paragraphs.

- **Artist tag strength is high.** A single well-known artist tag dominates the
  style. Use `(artist:0.7)` if you want the artist's style as a flavor rather
  than the dominant aesthetic. Combine 2–3 artists to dilute any one.

- **Character tag bleeds appearance.** Putting `hatsune miku` in your prompt
  pulls in twintails + cyan hair even if you wrote `red hair`. To override,
  weight your override up: `(red hair:1.3), (short hair:1.2)`, or drop the
  character tag and describe components instead.

- **`safe` rating tag matters.** If your dataset / LoRA is SFW, explicitly
  including `safe` reduces drift toward NSFW outputs from artist tags whose
  Danbooru work is mixed.

- **`absurdres` is a resolution tag, not a quality tag.** It's tied to
  >3000px source images on Danbooru. It does add detail but on Illustrious it
  also slightly biases composition. Drop it if you're getting busy backgrounds
  you don't want.

- **No CLIP skip needed.** Unlike NAI/AnythingV3 era, Illustrious is trained
  flat. Set CLIP skip to 1 (or just leave default). CLIP skip 2 is a Pony habit.

- **VAE is baked in.** Don't load a separate `sdxl_vae.safetensors` unless your
  particular checkpoint says to. WAI v1.7 ships its VAE.

---

## Quick reference: a known-good prompt

```
masterpiece, best quality, amazing quality, very aesthetic, newest,
safe, 1girl, solo, fox girl, fox ears, fox tail, long hair, white hair,
amber eyes, white kimono, red hakama, miko,
wariza, hands on lap, gentle smile, looking at viewer,
engawa, traditional japanese house, cherry blossoms, evening,
soft lighting, depth of field, from side,
absurdres
```

Negative:

```
lowres, worst quality, low quality, bad quality, displeasing, oldest, early,
sketch, jpeg artifacts, signature, watermark, artist name,
bad anatomy, bad hands, extra digits, fewer digits, deformed, blurry, censor
```

Settings: Euler A, 28 steps, CFG 5.5, 832×1216 (portrait) or 1024×1024.

---

## Sources

- [Tips for Illustrious XL Prompting (Civitai)](https://civitai.com/articles/8380/tips-for-illustrious-xl-prompting-updates)
- [Illustrious XL v1.0/v1.1 Guide (SeaArt)](https://www.seaart.ai/articleDetail/cvcdnn5e878c73fqe0s0)
- [Illustrious XL 2.0 Ultimate Guide (SeaArt)](https://www.seaart.ai/articleDetail/cvdosb5e878c73c7ipig)
- [WAI-Illustrious-SDXL model page (Civitai)](https://civitai.com/models/827184/wai-illustrious-sdxl)
- [WAI Illustrious anifusion docs](https://anifusion.ai/models/wai-illustrious/)
- [NoobAI XL 1.1 README (HuggingFace)](https://huggingface.co/Laxhar/noobai-XL-1.1/blob/main/README.md)
- [NoobAI XL Quick Guide (Civitai)](https://civitai.com/articles/8962/noobai-xl-quick-guide)
- [NoobAI XL SeaArt docs](https://docs.seaart.ai/guide-1/6-permanent-events/high-quality-models-recommendation/noobai-xl)
- [Best Negative Prompt for NoobAI-XL (Civitai)](https://civitai.com/articles/9695/f-best-negative-prompt-for-noobai-xl)
- [Illustrious paper (arXiv)](https://arxiv.org/html/2409.19946v1)
- [Pony Diffusion score tags explained (Civitai)](https://civitai.com/articles/4248/what-is-score9-and-how-to-use-it-in-pony-diffusion)
- [Pony Diffusion v6 XL guide (stable-diffusion-art.com)](https://stable-diffusion-art.com/pony-diffusion-v6-xl/)
- [Diffusers prompt weighting docs](https://huggingface.co/docs/diffusers/main/using-diffusers/weighted_prompts)
- [Compel library (GitHub)](https://github.com/damian0815/compel)
- [a1111-sd-webui-tagcomplete (GitHub)](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete)
- [Updated danbooru.csv 2024-10-16 (Civitai)](https://civitai.com/models/862893/updated-danboorucsv2024-10-16-for-webui-tag-autocomplete)
- [ComfyUI-EasyNoobai (GitHub)](https://github.com/regiellis/ComfyUI-EasyNoobai)
- [Danbooru tag search](https://danbooru.donmai.us/tags)
- [Danbooru wiki pages](https://danbooru.donmai.us/wiki_pages)
- [Danbooru Pose & Camera Tags (Moescape)](https://moescape.ai/posts/danbooru-pose-and-camera-tags)
- [Posture Tag Study (Tensor.Art)](https://tensor.art/articles/868180140037812339)
- [Image Composition Tag Study (Tensor.Art)](https://tensor.art/articles/863879940397915131)
- [What Are Booru Tags 2025 (Apatero)](https://apatero.com/blog/what-are-booru-tags-complete-guide-2025)
