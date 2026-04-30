# VRChat Avatar — Anime & Digital Art Style Guide

**Goal:** Train a character LoRA per avatar using Illustrious XL + ai-toolkit, then generate digital art and NSFW anime art in ComfyUI. Character LoRA = identity, checkpoint + style LoRA = art style.

**Your stack:** ai-toolkit (training) → Illustrious XL (base model) → ComfyUI (generation)

---

## Table of Contents

1. [Picture Preparation Guide](#picture-preparation-guide)
2. [Folder Structure](#folder-structure)
3. [Download Illustrious XL](#download-illustrious-xl)
4. [Train Your Character LoRA](#train-your-character-lora)
5. [Pick a Style from CivitAI](#pick-a-style-from-civitai)
6. [Generate Art in ComfyUI](#generate-art-in-comfyui)
7. [Multi-Character Scenes](#multi-character-scenes)
8. [Advanced Tips](#advanced-tips)
9. [Quick Reference Stack](#quick-reference-stack)
10. [Useful Links](#useful-links)

---

## Picture Preparation Guide

This is what you need to shoot for **each character** before training begins.

### How Many Images

- **Minimum:** 15 images
- **Sweet spot:** 25–35 images
- **More is not always better** — quality and variety beat quantity

### Required Shot Types

| Shot Type                  | Count | Notes                              |
| -------------------------- | ----- | ---------------------------------- |
| **Front, full body**       | 3–4   | Neutral pose, arms visible         |
| **Front, upper body**      | 3–4   | Waist up, face clearly visible     |
| **3/4 left, upper body**   | 3–4   | Most important angle for anime art |
| **3/4 right, upper body**  | 3–4   |                                    |
| **Side profile**           | 2–3   | Left and right                     |
| **Close-up face**          | 3–4   | Fill the frame with the face       |
| **Back view**              | 1–2   | Shows hair/outfit details          |
| **Full body varied poses** | 3–4   | T-pose, A-pose, casual stand       |

### Background Rules

- **Use a plain solid-color background** — white, grey, or any flat color
- In VRChat: use a world with a clean backdrop, or the **VRChat camera** with background blur
- Remove busy backgrounds after the fact if needed (use Remove.bg or Photoshop)
- **Never include other characters in the same frame**

### Technical Requirements

- Resolution: **1024x1024 minimum** (square crop preferred)
- Sharp focus — no motion blur
- Consistent lighting — avoid super dark or blown-out shots
- Same outfit per training set — if you want multiple outfits, train separate LoRAs

### What to Avoid

- Blurry or low-res images
- Extreme angles that hide the character's features
- Accessories that change between shots (hats, glasses etc.) unless they're permanent
- Screenshots with UI overlays or HUD elements

### For Friends' Avatars

Same rules apply. Each friend = their own folder, their own training run, their own trigger word.

---

## Folder Structure

Your files should be organized like this:

```
<repo>\                            ← everything big lives here (C drive is small)
  characters\
    [character name]\                 ← drop their images here
      image001.png
      image001.txt                    ← caption file (I'll write these)
      ...
  checkpoints\
    illustriousXL_v01.safetensors    ← download Illustrious XL here
  loras\
    characters\                       ← trained character LoRAs go here automatically
    styles\                           ← style LoRAs you download from CivitAI go here

C:\Programs\ai-toolkit\              ← just the app, no big files
  config\
    character_lora_illustrious_template.yaml   ← template (already created)
    [character name]_v1.yaml                   ← per-character config (I'll write these)

C:\Programs\ComfyUI\                 ← just the app, points to F drive for models
  extra_model_paths.yaml             ← tells ComfyUI to look in <repo>\ (already set up)
```

---

## Download Illustrious XL

I can't log in to CivitAI for you, but here's exactly what to do:

1. Go to **civitai.com** and search `Illustrious XL`
2. Download the **v0.1** checkpoint (`.safetensors`, ~7GB)
3. Drop it in: `<repo>\checkpoints\`
4. Name it `illustriousXL_v01.safetensors` (or update the path in the config)

> If you want NoobAI XL instead (also great, more stylistic), same process — search `NoobAI XL` on CivitAI.

---

## Train Your Character LoRA

### One-Time Setup (already done for you)

- ai-toolkit is installed at `C:\Programs\ai-toolkit`
- Template config is at `config\character_lora_illustrious_template.yaml`
- Output folders are created in ComfyUI

### Per-Character Process

1. **You:** Drop images into `training_images\characters\[name]\`
2. **Me:** Write captions (`.txt` file per image) and generate a config file
3. **You:** Run `train.bat` and select the config
4. Wait ~30–60 min depending on your GPU
5. LoRA appears automatically in `ComfyUI\models\loras\characters\`

### Training Config Location

`c:\Programs\ai-toolkit\config\character_lora_illustrious_template.yaml`

Copy this template for each new character and update:

- `name` — character name
- `trigger_word` — short unique word (e.g. character's name)
- `folder_path` — point to their image folder
- `prompts` — describe their appearance for sample images

---

## Pick a Style from CivitAI

### Style via Checkpoint (already chosen: Illustrious XL)

Illustrious XL is your base — it gives you clean anime linework and handles explicit content well.

### Style LoRAs to Stack on Top

Download these from CivitAI and drop in `ComfyUI\models\loras\styles\`:

| Style LoRA                | Look                        | Use Weight |
| ------------------------- | --------------------------- | ---------- |
| **Anime Screencap Style** | Anime TV episode look       | 0.4–0.6    |
| **Flat Colour Anime**     | Flat cel-shaded digital art | 0.4–0.6    |
| **Anime High Contrast**   | Bold vivid two-tone         | 0.3–0.5    |
| **Real Life Anime Style** | Realism + anime blend       | 0.4–0.6    |

Browse CivitAI: filter by **LoRA** + **Base Model: Illustrious** + tag `anime` or `digital art`. Sort by Most Downloaded.

---

## Generate Art in ComfyUI

### Basic Single Character Workflow

1. Load **Illustrious XL** checkpoint in ComfyUI
2. Add your **character LoRA** — weight `0.7–0.9`
3. Add a **style LoRA** (optional) — weight `0.4–0.6`
4. Positive prompt: `[trigger_word], anime girl, [scene description], masterpiece, best quality`
5. Negative prompt: `worst quality, low quality, bad anatomy, deformed, blurry, extra limbs`
6. Resolution: `1024x1024`
7. CFG scale: `7`

### For NSFW / Explicit Content

- Illustrious XL handles explicit content — no extra model needed
- Add explicit tags to your prompt naturally after the character description
- Use a negative prompt to control anatomy: `bad hands, extra fingers, malformed genitals`
- Inpaint any anatomy issues after the fact

---

## Multi-Character Scenes

### Feasibility

- **2 characters:** Doable, expect some iteration
- **3+ characters:** Very difficult, not recommended to start with

### How to Do It (2 characters)

1. Load **both** character LoRAs simultaneously
2. Set each to weight **0.5–0.65** (lower than single-character)
3. Prompt both trigger words: `[char1_trigger], [char2_trigger], two girls, ...`
4. Install **Attention Couple** or **Regional Prompter** node in ComfyUI to assign each character to a region of the image
5. Generate at wider aspect ratio: `1216x832` or `1344x768`

### For Explicit Multi-Character Scenes

- The AI naturally tangles bodies — lean into it, the composition often works
- Specify who is doing what clearly in the prompt
- Inpaint faces separately if one character's features bleed into the other
- Expect to generate 10–20 images and cherry-pick the best

---

## Advanced Tips

- More dataset variety = better generalization across poses
- Avoid blurry or low-contrast training images
- If the character looks "stiff" or over-fitted, lower LoRA weight or reduce training steps
- Train on the same base model you generate with (Illustrious XL → Illustrious XL)
- Train separate LoRAs per outfit if you want costume variety

---

## Step 6: Advanced Tips

- More dataset variety = better generalization across poses and scenes
- Avoid blurry or low-contrast training images
- If results look stiff or over-fitted, reduce training steps or lower LoRA weight at generation
- Train on the same base model you plan to generate with
- Consider separate LoRAs for different styles (anime vs. realistic) if you want both

---

## Quick Reference Stack

| Component                 | Recommendation                              |
| ------------------------- | ------------------------------------------- |
| **Base Model**            | Illustrious XL or NoobAI XL                 |
| **Character LoRA**        | Trained on your VRChat avatar images        |
| **Style LoRA** (optional) | Pick from CivitAI based on preferred look   |
| **Generation UI**         | A1111 or ComfyUI                            |
| **Training Tool**         | Kohya SS (local) or CivitAI Trainer (cloud) |
| **Target Resolution**     | 1024x1024                                   |
| **Character LoRA Weight** | 0.7–1.0                                     |
| **Style LoRA Weight**     | 0.4–0.6                                     |

---

## Useful Links

- [CivitAI — Models, LoRAs, Styles](https://civitai.com)
- [CivitAI LoRA Guide](https://civitai.com/articles/2099)
- [Kohya SS Trainer (GitHub)](https://github.com/bmaltais/kohya_ss)
- [Automatic1111 WebUI (GitHub)](https://github.com/AUTOMATIC1111/stable-diffusion-webui)
- [ComfyUI (GitHub)](https://github.com/comfyanonymous/ComfyUI)
- [ControlNet Guide](https://stable-diffusion-art.com/controlnet/)
- [Stable Diffusion Art Tutorials](https://stable-diffusion-art.com)
- [Anime Image Transformation Workflow (ComfyUI)](https://comfyui.org/en/anime-image-transformation-workflow)
