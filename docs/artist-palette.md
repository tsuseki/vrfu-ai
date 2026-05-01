# Illustrious / waiIllustrious Artist Palette

A curated reference of Danbooru artist tags known to work well with Illustrious-family checkpoints (waiIllustriousSDXL, NoobAI, etc.). Use this to plan next batches.

> ⚠️ **This is the personal taste of tsuseki**, not an authoritative ranking. Tiers reflect what tsuseki votes ❤️/👍 on for his own characters and aesthetic preferences (cozy/casual/feet-focused, anime coloring, soft cute). Your taste will differ — treat the lists as a starting point, vote on your own outputs, and re-tier from your own data. The website's Stats panel surfaces your per-artist hit rate.

> Format used in prompts: `artist:NAME` — e.g. `artist:hiten`, `artist:wlop`. Going forward we use **one artist per prompt** so each like/dislike maps cleanly to one artist.

---

## ✅ Tier S — confirmed winners (batch 1 final scores after dislikes)

| Artist | Score | Voted / In batch | Notes |
|---|---:|---|---|
| **hiten** | +26 | 20 / 48 | Top performer. Great for cozy, expressive, casual + feet scenes |
| **atdan** | +24 | 13 / 35 | Excellent for fashion, urban, vibrant, feet |
| **beko** | +14 | 8 / 14 | Round soft cute, slice-of-life, feet — strong hit rate |
| **ningen mame** | +11 | 5 / 24 | Painterly NSFW, bath/bedroom — good intimate scenes |

## ✅ Tier A — solid performers

| Artist | Score | Voted / In batch | Notes |
|---|---:|---|---|
| **ke-ta** | +8 | 6 / 32 | Dreamy pastel, atmospheric. Works for feet/mood |
| **ningen** | +5 | 3 / 31 | Clean cute lines, good general-purpose |

## ❓ Tier B — weak or thin signal, retest with single-artist prompts

| Artist | Score | Voted / In batch | Notes |
|---|---:|---|---|
| wakaba | +2 | 1 / 2 | Only 2 prompts — not enough data |
| mika pikazo | +1 | 2 / 7 | Distinctive bright style, may not fit her vibe at scale |
| ciloranko | 0 | 0 / 18 | 18 prompts, zero positive votes (but also zero dislikes — just neutral?) |

## ❌ Tier D/F — drop from regular rotation

| Artist | Score | Voted / In batch | Why dropping |
|---|---:|---|---|
| carnelian | −2 | 2 / 19 | More dislikes than likes |
| asanagi | −3 | 12 / 49 | Strong NSFW artist but 5 anatomy issues — fights the LoRA |
| sciamano240 | −5 | 7 / 25 | 3 anatomy issues, net negative |
| redum4 | −11 | 9 / 37 | Dynamic but 5 anatomy issues — doesn't fit her |
| as109 | −15 | 13 / 42 | 7 anatomy issues — neon/cyberpunk clashes badly |
| **wlop** | **−25** | 11 / 28 | Worst performer — dramatic style doesn't fit Tsu Chocola |

---

## 🆕 Untried artists worth exploring (Illustrious-compatible)

Grouped by aesthetic. All known to fire reliably on waiIllustrious.

### Cozy / cute (similar to hiten/beko/atdan family)

- **kantoku** — signature kantoku style, very kawaii, wide-eye anime
- **daye_bie_qia_lian** — clean cute, soft outline
- **sho_(sho_lwlw)** — clean cute, school-life vibe
- **sazanami_mio** — cute soft, anime
- **akairiot** — kawaii, cheerful
- **yumeichigo_alice** — sweet pastel
- **piromizu** — dreamy cute
- **misaki_kurehito** — cute soft, classic anime feel
- **tinkerbell_(artist)** — kawaii classic
- **shilin** — clean cute, popular on Illustrious
- **nardack** — clean line art, cute
- **onineko** — dreamy soft anime

### Atmospheric / painterly (similar to ke-ta)

- **guweiz** — dramatic painterly, strong lighting
- **yoneyama_mai** — traditional anime, serious tone
- **modare** — ethereal, otherworldly
- **kazenokaze** — atmospheric soft

### NSFW alternatives (untried, similar to ningen mame)

- **bara_(rism)** — lewd anime
- **chen_bin** — lewd painterly
- **cheesecake_(artist)** — lewd cute
- **ikuyoan** — lewd dynamic
- **kase_daiki** — lewd painterly
- **asakuraf** — lewd anime
- **suien** — lewd alternative

### Stylized / distinctive

- **omutatsu** — vibrant stylized, idol
- **akamatsu_ken** — classic anime style
- **tsubasa_tsubasa** — flowing soft

---

## How tags work syntax-wise

**Always check `_` vs space.** Some artists are tagged with underscores in Danbooru.

```
artist:hiten              # works
artist:daye_bie_qia_lian  # works (underscore form)
```

## Recommended batch 2 artist composition

Single artist per prompt, weighted distribution roughly:

- ~45% Tier S (hiten, atdan, beko, ningen mame) → most reliable hits
- ~20% Tier A (ke-ta, ningen) → keep momentum
- ~30% New artists from untried sections → expand palette, find new winners
- ~5% Tier B retest (wakaba, mika pikazo) → final confirmation with clean single-artist signal

Drop entirely: ciloranko, wlop, redum4, as109, asanagi, sciamano240, carnelian.
