# Automated Processing & Reporting Automation Suite

A Python automation framework for batch processing images/videos through 23 AI APIs with automated PowerPoint report generation.

## Contents

- [Quick Start](#-quick-start)
- [Installation](#-installation)
- [Testbed Cookie Setup](#-testbed-cookie-setup)
- [Platforms at a Glance](#-platforms-at-a-glance)
- [Folder Conventions](#-folder-conventions)
- [Configuration Reference](#%EF%B8%8F-configuration-reference)
  - [Kling family](#kling-family)
  - [Pixverse family](#pixverse-family)
  - [Vidu family](#vidu-family)
  - [Seedance family](#seedance-family)
  - [Google Veo family](#google-veo-family)
  - [Image generation (Nano Banana, OpenAI Image, GenVideo)](#image-generation-nano-banana-openai-image-genvideo)
  - [Pipelines (FIFA I2I2V, I2I2V)](#pipelines-fifa-i2i2v-i2i2v)
  - [Other (Runway, Wan 2.2, DreamActor)](#other-runway-wan-22-dreamactor)
- [Report Generation](#-report-generation)
- [Desktop GUI](#%EF%B8%8F-desktop-gui)
- [Building the Desktop App](#-building-the-desktop-app)
- [Architecture](#-architecture)
- [Project Structure](#-project-structure)

---

## 🚀 Quick Start

```bash
cd Scripts

# Syntax: python core/runall.py <platform> <action> [options]
python core/runall.py kling auto      # Process + generate report
python core/runall.py nano process    # Process only
python core/runall.py pixverse_i2v report # Report only
python core/runall.py all auto        # All APIs at once

# Options
--parallel       # Run APIs in parallel (with 'all')
--config FILE    # Override the default config path
--verbose        # Debug logging
```

`<action>` is one of `process` (run the API only), `report` (regenerate the PowerPoint from existing outputs), or `auto` (process then report).

## 🔧 Installation

```bash
cd Scripts
pip install -r requirements.txt
brew install ffmpeg   # macOS — required for video processing
```

**Requirements:** Python 3.8+, FFmpeg, 8 GB+ RAM

Key dependencies:

| Package | Purpose |
| --- | --- |
| `gradio_client` | Talks to the testbed APIs |
| `ruamel.yaml` | Round-trip YAML editing that preserves formatting |
| `python-pptx` | PowerPoint report generation |
| `opencv-python` | Video / image processing |
| `pillow-heif` | HEIC / HEIF support |
| `wakepy` | Cross-platform sleep prevention (non-macOS) |
| `tqdm` | Progress bars |

## 🔐 Testbed Cookie Setup

The testbed at `192.168.31.161` requires browser cookie authentication. Each user must provide their own cookie. **Cookies are never committed to Git.**

### Option 1 — `.env` file (recommended for CLI use)

```bash
cd Scripts
cp .env.example .env
```

Edit `.env`:

```env
TESTBED_COOKIE=session_id=abc123; auth_token=xyz789
```

### Option 2 — GUI field

Open the GUI → **Advanced Options** → **Testbed Cookie**. The field auto-loads from `.env` on launch; you can paste a different cookie there to use just for the current run.

### Option 3 — Environment variable

```bash
export TESTBED_COOKIE="session_id=abc123; auth_token=xyz789"
python core/runall.py kling auto
```

### How to get your cookie

1. Open the testbed URL in your browser and log in.
2. Open DevTools (F12) → **Network** tab.
3. Reload the page and click any request to the testbed host.
4. Copy the full **Cookie** header value from the request headers.

## 📋 Platforms at a Glance

### Command short names

| Short name | Full name | Type | Key feature |
| --- | --- | --- | --- |
| `kling` | Kling I2V | I2V | Streaming downloads, negative prompts, v1.6 – v3.0 models |
| `klingfx` | Kling Effects | I2V | 100+ preset effects, custom effects |
| `kling_endframe` | Kling Endframe | I2V | A→B transitions, pairing modes |
| `kling_ttv` | Kling TTV | T2V | Text-to-video, optional sound generation |
| `klingmotion` | Kling Motion | I+V | Image × video motion cross-matching |
| `pixverse_i2v` | Pixverse I2V | I2V | `/submit_3`, v6 model, custom effect IDs, multi-clip, AI audio (not for templates) |
| `pixverse_effect` | Pixverse Effects | I2V | `/submit_5` templates (1–4 images), template-compatible sound (global + per-task), sequential / deterministic-random picking |
| `pixversettv` | Pixverse TTV | T2V | Text-to-video, v6 model, effects |
| `vidu` | Vidu Effects | I2V | Category-organized presets, viduq2-pro |
| `viduref` | Vidu Reference | I2V | Up to 6 references per source |
| `vidu_i2v` | Vidu I2V | I2V | `/submitI2V`, custom prompts, q1 – q3 models, optional audio |
| `seedance_ttv` | Seedance TTV | T2V | Text-to-video, dreamina-seedance-2.0 models |
| `seedance_i2v` | Seedance I2V | I2V | Image-to-video with custom prompts |
| `veo` | Google Veo | T2V | Veo 2.0 – 3.1, audio generation, compression options |
| `veoitv` | Google Veo ITV | I2V | Image-to-video, multi-generation per image |
| `nano` | Nano Banana | I2I | Multi-image (up to 14), random source selection |
| `openai_image` | OpenAI Image | I2I | `gpt-image-1` / `gpt-image-2`, multi-image, reference images |
| `genvideo` | GenVideo | I2I | Gashapon-style image transformation |
| `runway` | Runway Gen4 | V2V | Face swap / motion, `one_to_one` or `all_combinations` pairing |
| `wan` | Wan 2.2 | I+V | Auto-cropping, video × image cross-match |
| `dreamactor` | DreamActor | I+V | Face reenactment via image × video cross-match |
| `motion_swap` | Motion Swap | I+V | Motion transfer via subject image × motion video cross-match |
| `happyhorse_vedit` | HappyHorse Video Edit | V2V | Prompt-driven video edit with up to 5 reference images (append or cross-match) |
| `fifa` | FIFA I2I2V | I2I2V | Per-image start/end-frame generation → video |
| `i2i2v` | I2I2V | I2I2V | Generic image → image → video pipeline (Nano Banana / OpenAI Image + Kling) |
| `all` | All Platforms | — | Run every API in sequence (or `--parallel`) |

### File limits

| API | Max size | Min / max dim | Formats |
| --- | --- | --- | --- |
| Kling | 10 MB | 300 px / — | JPG, PNG, WebP |
| Kling Effects | 30 MB | 300 px / — | JPG, PNG, BMP, TIFF |
| Kling Endframe | 10 MB | 300 px / — | JPG, PNG, BMP, TIFF |
| Kling Motion | image 50 MB / video 500 MB | 128 px / — | image: JPG, PNG, WebP; video: MP4, MOV, AVI, MKV, WebM |
| Pixverse I2V | 20 MB | 128 px / 4000 px | JPG, PNG, BMP, TIFF, WebP |
| Pixverse Effects | 20 MB | 128 px / 10000 px | JPG, PNG, WebP |
| Vidu Effects / I2V | 20 MB | 128 px / 4000 px | JPG, PNG, WebP |
| Vidu Reference | 50 MB | 128 px / — | JPG, PNG, WebP |
| Seedance I2V | 30 MB | 300 px / — | JPG, PNG, WebP |
| Veo ITV | 30 MB | 300 px / — | JPG, PNG, WebP |
| Nano Banana | 32 MB | 300 px / — | JPG, PNG, WebP |
| OpenAI Image | 32 MB | 100 px / — | JPG, PNG, WebP |
| GenVideo | 50 MB | 128 px / — | JPG, PNG, WebP |
| Runway | image 500 MB / video 500 MB | 320 px / — | image: JPG, PNG, BMP; video: MP4, MOV, AVI, MKV, WebM |
| Wan 2.2 | image 50 MB / video 500 MB | 128 px / — | image: JPG, PNG, WebP; video: MP4, MOV, AVI, MKV, WebM |
| DreamActor | image 50 MB / video 500 MB | 128 px / — | image: JPG, PNG, WebP; video: MP4, MOV, AVI, MKV, WebM |
| Motion Swap | image 50 MB / video 500 MB | 128 px / — | image: JPG, PNG, WebP; video: MP4, MOV, AVI, MKV, WebM |
| HappyHorse Video Edit | image 10 MB / video 100 MB | image ≥ 300 px; video shorter ≥ 320 px, longer ≤ 2160 px, 3–60 s, AR 1:2.5–2.5:1 | image: JPG, PNG, WebP; video: MP4, MOV |
| FIFA I2I2V / I2I2V | 30 MB | 256 px / — | JPG, PNG, WebP |

(Text-to-video APIs — Kling TTV, Pixverse TTV, Seedance TTV, Veo — take no source files.)

### Output filenames

| API | Output pattern |
| --- | --- |
| Kling | `{filename}_generated.mp4` |
| Kling Effects / Pixverse I2V / Vidu | `{filename}_{effect}_effect.mp4` |
| Kling Endframe | `{filename}_generated_{n}.mp4` |
| Kling TTV / Pixverse TTV / Seedance TTV | `{style}-{n}_generated.mp4` |
| Kling Motion | `{video}_{image}_motion.mp4` |
| Veo / Veo ITV | `{style}-{n}_generated.mp4` / `{source_image}_{n}.mp4` |
| Pixverse Multi | `iter{NNN}_{img1_stem}_{img2_stem}_..._{Effect}_effect.mp4` |
| Runway | `{filename}_ref_{ref}_runway_generated.mp4` |
| Wan 2.2 / DreamActor | `{video}_{image}_{mode}.mp4` |
| Motion Swap | `{video}_{image}_motion_swap.mp4` |
| HappyHorse Video Edit | `{video}_generated.mp4` (cross-match: `{video}_ref{NN}_{refname}_generated.mp4`) |
| Nano Banana | `{filename}_image_{n}.{ext}` |
| OpenAI Image | `{filename}_image_{n}.{ext}` |
| GenVideo | `{filename}_generated.{ext}` |
| Seedance I2V | `{source_image}_{n}.mp4` |
| FIFA I2I2V | video `{source_image}_{n}.mp4`, frames `{source_image}_{n}_{start\|end}.png` |
| I2I2V | video `{source_image}_{n}.mp4`, frames `{source_image}_{n}.{ext}` |

All metadata is stored alongside the outputs as `{filename}_metadata.json` (includes success, processing time, API params, attempt count).

## 📂 Folder Conventions

Most APIs follow a per-task folder structure with a `Source/` input subfolder. Output and metadata subfolders are auto-created on first run.

```bash
TaskFolder/
├── Source/              # Input images / videos (most APIs)
├── Source Image/        # Wan 2.2, DreamActor, Motion Swap, Kling Motion: source images
├── Source Video/        # Wan 2.2, DreamActor, Motion Swap, Kling Motion: source videos
├── Additional/          # Nano Banana / OpenAI Image: extra images for multi-image mode
├── Reference/           # Runway, Vidu Reference, Nano Banana, OpenAI Image: reference images
├── Generated_Video/     # Auto-created video outputs (video APIs)
├── Generated_Output/    # Auto-created outputs (Nano Banana, OpenAI Image)
├── Generated_Image/     # Auto-created outputs (GenVideo)
├── Generated_Frames/    # Auto-created intermediate frames (FIFA I2I2V, I2I2V)
└── Metadata/            # Auto-created metadata JSONs
```

API-specific input layouts:

- Most APIs → `Source/`
- Wan 2.2 / DreamActor / Motion Swap / Kling Motion → `Source Image/` + `Source Video/` (cross-matched)
- Nano Banana multi-image → `Source/` + `Additional/` (or `Source/` only with random selection) + optional `Reference/`
- OpenAI Image → same as Nano Banana
- Runway → `Source/` (videos) + `Reference/` (images)
- HappyHorse Video Edit → `Source/` (videos) + optional `Reference/` (up to 5 images, append or cross-match)
- Vidu Reference → `Source/` + `Reference/`
- Pixverse Effects → `Source/` (Source pool is consumed in chunks of `image_count`)
- FIFA I2I2V / I2I2V → `Source/` (frames in `Generated_Frames/`, videos in `Generated_Video/`)

## ⚙️ Configuration Reference

All configs live in `Scripts/config/` and follow the `batch_{api}_config.yaml` naming convention.

### Common fields

These apply across most config files (each API will only use the subset relevant to it):

- **`design_link`** — URL to design reference material (used in report titles)
- **`source_video_link`** — URL to source video reference (used in report titles)
- **`reference_folder`** — Path to a reference comparison folder
- **`use_comparison_template`** — Enable the 3-media comparison template
- **`schedule.start_time`** — Delayed start in `HH:MM` 24-hour format; empty = immediate
- **`output.directory`** — Directory for generated PPTX reports
- **`output.group_tasks_by`** — Group N tasks into one combined report (0 = individual)
- **`template_path`** — Path to the PowerPoint template

---

### Kling family

#### Kling I2V (`config/batch_kling_config.yaml`)

```yaml
testbed: http://192.168.31.161/external-testbed/kling/
model_version: v2.5-turbo
group_tasks_by: 4

schedule:
  start_time: ""  # HH:MM or empty for immediate

tasks:
  - mode: std
    folder: /path/to/TaskName1
    prompt: "Transform this portrait into a cinematic video"
    negative_prompt: "blurry, low quality"
```

**Options:** Model (`v1.6` / `v2.1` / `v2.5-turbo` / `v3`), Mode (`std` / `pro`), Duration (`5` / `10`), CFG (`0.0` – `1.0`).

#### Kling Effects (`config/batch_kling_effects_config.yaml`)

Applies premade video effects to images. Supports both preset effects and custom effect names.

```yaml
base_folder: Media Files/Kling Effects/1127 Test
testbed: http://192.168.31.161/external-testbed/kling/
duration: '5'
effect: 3d_cartoon_1       # Preset effect from dropdown
custom_effect: ''           # Custom effect name (takes priority if specified)

tasks:
  - style_name: 3D Cartoon
    effect: 3d_cartoon_1
    custom_effect: ''
  - style_name: Custom Style
    effect: ''
    custom_effect: my_custom_effect
```

Effect selection:

- Use `effect` to pick from 100+ presets (e.g., `3d_cartoon_1`, `anime_figure`, `japanese_anime_1`, `american_comics`, `angel_wing`, `baseball`, `boss_coming`, `car_explosion`, `celebration`, `demon_transform`, `disappear`, `emoji`, `firework`, `gallery_ring`, `halloween_escape`, `jelly_jiggle`, `magic_broom`, `mushroom`, `pixelpixel`, `santa_gifts`, `steampunk`, `vampire_transform`, `zombie_transform`, …).
- Use `custom_effect` to specify a custom name (takes priority over `effect`).

Folder layout:

```bash
BaseFolder/
├── StyleName1/
│   ├── Source/              # Input images
│   ├── Generated_Video/     # auto-created
│   └── Metadata/            # auto-created
├── StyleName2/
│   └── ...
```

#### Kling Endframe (`config/batch_kling_endframe_config.yaml`)

Generates videos from start/end image pairs, producing smooth A→B transitions.

```yaml
testbed: http://192.168.31.161/external-testbed/kling/
model_version: v2.1
generation_count: 1

output:
  directory: /Users/ethanhsu/Desktop/EthanHsu-cl/GAI/Report
  group_tasks_by: 3

tasks:
  - mode: pro
    folder: Media Files/Kling Endframe/1030 3 Styles/Anime Awakening
    prompt: "Smooth transition from start to end frame"
    duration: 5
    cfg: 0.5
    pairing_mode: ab_naming     # 'ab_naming' or 'sequential'
    generation_count: 3
```

Pairing modes:

- `ab_naming` (default) — `Style_A.jpg` ↔ `Style_B.jpg`
- `sequential` — first half = start frames, second half = end frames

**Options:** `mode` (`pro` / `std`), `duration` (`5` / `10`), `cfg` (`0.0` – `1.0`), `model_version` (`v1.6` / `v2.1`).

#### Kling TTV (`config/batch_kling_ttv_config.yaml`)

Text-to-video — no source images needed.

```yaml
testbed: http://192.168.31.161/external-testbed/kling/
model: "v2.5-turbo"
output_folder: Media Files/Kling TTV/Test
generation_count: 1
sound_enabled: true

tasks:
  - style_name: "Dog Running"
    prompt: "A dog is happily running toward its owner"
    neg_prompt: ""
    mode: "pro"
    duration: 5
    ratio: "1:1"
    cfg: 0.5
```

**Options:** Model (`v1.6` / `v2.0-master` / `v2.1-master` / `v2.5-turbo`), Mode (`std` / `pro`), Ratio (`16:9` / `9:16` / `1:1`), `sound_enabled`, `generation_count`.

#### Kling Motion (`config/batch_kling_motion_config.yaml`)

Cross-matches all reference images with all motion source videos.

```yaml
testbed: http://192.168.31.161/external-testbed/kling/

default_params:
  prompt: ''
  model: v3
  character_orientation: video
  mode: pro
  keep_original_sound: true
  element_list_str: ''

tasks:
  - folder: Media Files/Kling Motion/Style1
```

Folder layout:

```bash
TaskFolder/
├── Source Image/        # Reference images (character appearance)
├── Source Video/        # Motion source videos
├── Generated_Video/
└── Metadata/
```

**Options:** Model (`v2.6` / `v3`), Character Orientation (`image` / `video`), Mode (`std` / `pro`), `keep_original_sound`, `element_list_str` (comma-separated IDs).

---

### Pixverse family

#### Pixverse I2V (`config/batch_pixverse_i2v_config.yaml`)

Single-image image-to-video via `/submit_3`. Exposes prompt / negative_prompt, motion_mode, style and the AI-audio toggle. Note: PixVerse rejects AI audio when a template/effect is applied — use Pixverse Effects for template + sound.

```yaml
base_folder: Media Files/Pixverse
testbed: http://192.168.31.161/external-testbed/video_effect/

default_settings:
  model: v6
  duration: 5s
  v6_duration: 5
  motion_mode: normal
  quality: 540p
  style: none
  seed: -1
  generate_audio: false
  generate_multi_clip: false
  thinking_type: auto

tasks:
  - effect: Dynamic Motion
    prompt: "Add dynamic motion"
    custom_effect_id: ""
```

**Defaults:** Model v6, Duration 5 s, Quality 540p, Motion Mode `normal`, Seed `-1`.

#### Pixverse Effects (`config/batch_pixverse_effect_config.yaml`)

PixVerse templates/effects via `/submit_5`. Each task consumes images from `base_folder/<effect>/Source` in groups of `image_count` (1 – 4) per API call. Set `image_count: 1` to run an effect one-image-per-video. Unlike the i2v endpoint, this carries `sound_effect_switch`, the template-compatible sound toggle (global default, overridable per task).

```yaml
base_folder: Media Files/Pixverse Multi/0526 Multi Input
testbed: http://192.168.31.161/external-testbed/video_effect/

default_settings:
  model: v6
  duration: 5
  quality: 1080p
  sound_effect_switch: true
  image_count: 2
  selection_mode: sequential   # 'sequential' or 'random'
  # random_seed: 42            # optional; auto-derived from folder path if omitted
  num_iterations: 0            # 0 = floor(len(source) / image_count), one full pass

tasks:
  - effect: Stands Duo
    custom_effect_id: '402880241531072'   # PixVerse Template ID (required)
    image_count: 2
    selection_mode: sequential
    sound_effect_switch: true             # per-task override of the global default
```

**Defaults:** Model v6, Quality 1080p, Sound effect on, Image count 1, Sequential selection. `sound_effect_switch` is settable globally and per task (per task wins), so one batch can mix sounded and silent effects.

Notes from the PixVerse testbed page:

- A PixVerse Template ID is **required** (enable the template on the PixVerse platform first).
- `image_count` (1 – 4) controls how many images are sent. Multi-image templates require multiple images; single-image templates should use 1.
- Image formats: JPG / JPEG / PNG / WebP. Max 10000 × 10000 px. Size < 20 MB.
- The template controls the actual duration and aspect ratio. PixVerse ignores any prompt, so this config does not expose one.
- `selection_mode: random` shuffles the Source pool with a deterministic seed (auto-derived from the folder path, or set `random_seed` explicitly).

#### Pixverse TTV (`config/batch_pixverse_ttv_config.yaml`)

```yaml
output_folder: Media Files/Pixverse TTV
testbed: http://192.168.31.161/external-testbed/video_effect/
generation_count: 1

default_settings:
  model: v6
  aspect_ratio: "16:9"
  duration: 5s
  v6_duration: 5
  motion_mode: normal
  quality: 540p
  style: none
  seed: -1
  generate_audio: false
  generate_multi_clip: false
  thinking_type: auto

tasks:
  - style_name: "Sample Prompt"
    prompt: "A golden retriever running on a sunny beach"
    negative_prompt: ""
    effect: none
    custom_effect_id: ""
    aspect_ratio: "16:9"
    generation_count: 1
```

**Defaults:** Model v6, Aspect Ratio 16:9, Duration 5 s, Quality 540p, Seed `-1`.

---

### Vidu family

#### Vidu Effects (`config/batch_vidu_effects_config.yaml`)

```yaml
base_folder: Media Files/Vidu/1027 Product
testbed: http://192.168.31.161/external-testbed/video_effect/
model_version: viduq2-pro

tasks:
  - category: Product
    effect: Auto Spin
```

#### Vidu Reference (`config/batch_vidu_reference_config.yaml`)

```yaml
base_folder: Media Files/Vidu_Ref/1201 1 Style
testbed: http://192.168.31.161/external-testbed/video_effect/
model: viduq1
duration: 5
resolution: 1080p
movement: auto

tasks:
  - effect: Style Transfer
    prompt: "Apply artistic style"
```

**Options:** Duration (`4` / `5` / `8` s), Resolution (`720p` / `1080p`), up to 6 reference images per source.

#### Vidu I2V (`config/batch_vidu_i2v_config.yaml`)

```yaml
base_folder: Media Files/Vidu I2V/0518 3 Styles
testbed: http://192.168.31.161/external-testbed/video_effect/
model: viduq2-pro
resolution: 720p
movement: auto
audio: true

tasks:
  - custom_effect_name: Police
    duration: 5
    prompt: |
      Custom prompt describing the desired motion / scene.
```

**Options:** Model (`viduq1`, `viduq1-classic`, `viduq2-pro`, `viduq2-turbo`, `viduq2-pro-fast`, `viduq3-pro`, `viduq3-turbo`), Duration (seconds), Resolution (`360p` / `540p` / `720p` / `1080p` / `2K`), Movement (`auto` / `small` / `medium` / `large`), Audio sync (q3 models only).

---

### Seedance family

#### Seedance TTV (`config/batch_seedance_ttv_config.yaml`)

```yaml
output_folder: Media Files/Seedance TTV
testbed: http://192.168.31.161/external-testbed/video_effect/
generation_count: 1

default_settings:
  model: dreamina-seedance-2-0-260128
  aspect_ratio: adaptive
  duration: 5
  resolution: 720p
  seed: -1
  service_tier: default
  generate_audio: true
  draft: false
  cam_fix: false
  expires: 172800

tasks:
  - style_name: "Sample Prompt"
    prompt: "A golden retriever running on a sunny beach"
    aspect_ratio: adaptive
    generation_count: 1
```

**Defaults:** Model `dreamina-seedance-2-0-260128`, Aspect Ratio `adaptive`, Duration 5 s, Resolution 720p, Seed `-1`, Audio enabled.

#### Seedance I2V (`config/batch_seedance_i2v_config.yaml`)

```yaml
root_folder: Media Files/Seedance I2V
testbed: http://192.168.31.161/external-testbed/video_effect/
generation_count: 1

default_settings:
  model: dreamina-seedance-2-0-260128
  aspect_ratio: adaptive
  duration: 5
  resolution: 720p
  seed: -1
  service_tier: default
  generate_audio: true
  draft: false
  cam_fix: false
  expires: 172800

tasks:
  - style_name: "Sample Style"
    folder: Media Files/Seedance I2V/0416 21 Styles/Sample_Style
    prompt: "A golden retriever running on a sunny beach"
    aspect_ratio: adaptive
```

Each task folder must contain a `Source/` subfolder with input images.

---

### Google Veo family

#### Veo (`config/batch_veo_config.yaml`)

Text-to-video — no source images needed.

```yaml
testbed: http://192.168.31.161/external-testbed/google_veo/
generation_count: 1

tasks:
  - prompt: "A serene landscape with mountains at sunset"
    style_name: Mountain_Sunset
    model_id: veo-3.1-generate-preview
    duration_seconds: 6
    aspect_ratio: "16:9"
    resolution: 1080p
    compression_quality: optimized
    enhance_prompt: true
    generate_audio: true
    person_generation: allow_all
    output_folder: Media Files/Veo/Test1/Generated_Video
```

**Models:** `veo-2.0-generate-001`, `veo-3.0-generate-001`, `veo-3.0-fast-generate-001`, `veo-3.0-generate-preview`, `veo-3.1-generate-preview`, `veo-3.1-fast-generate-preview`, `veo-3.1-generate-001`, `veo-3.1-fast-generate-001`.

**Options:** Ratio (`16:9` / `9:16`), Resolution (`720p` / `1080p`), `compression_quality` (`optimized` / `lossless`), `enhance_prompt`, `generate_audio`, `person_generation` (`allow_all` / `allow_adult` / `dont_allow`).

#### Veo ITV (`config/batch_veo_itv_config.yaml`)

Image-to-video with source images.

```yaml
root_folder: Media Files/Veo_ITV
generation_count: 2   # videos per source image

tasks:
  - style_name: Style 11_Statue Selfie
    folder: Media Files/Veo_ITV/Style 11_Statue Selfie
    prompt: "The statue comes to life in a cinematic motion."
    model_id: veo-3.1-generate-001
    duration_seconds: 8
```

Folder layout:

```bash
root_folder/
├── Style 11_Statue Selfie/
│   ├── Source/
│   ├── Generated_Video/    # {image_name}_{n}.mp4
│   └── Metadata/
```

---

### Image generation (Nano Banana, OpenAI Image, GenVideo)

#### Nano Banana (`config/batch_nano_banana_config.yaml`)

Two modes: **Random Source Selection** (pick N random images from Source folder per call) and **Multi-Image** (Source + Additional folder pairing).

```yaml
testbed: http://192.168.31.161/external-testbed/image_generation/

output:
  group_tasks_by: 2

tasks:
  # Random Source Selection (recommended)
  - folder: /path/to/TaskName1
    model: gemini-3-pro-image-preview
    resolution: "2K"
    aspect_ratio: "3:4"
    prompt: "Your prompt here"
    use_random_source_selection: true
    use_deterministic_random: true
    random_seed: 42
    min_images: 1
    max_images: 4
    num_iterations: 50
    generations_per_source: 1
    use_reference_images: false

  # Multi-Image (Source + Additional folder)
  - folder: /path/to/TaskName2
    model: gemini-2.5-flash-image
    prompt: "Generate variations"
    use_multi_image: true
    multi_image_config:
      mode: sequential   # or 'random_pairing'
      folders: ["/path/to/Additional/"]
```

**Per-task fields:** `model`, `resolution` (`1K` / `2K`), `aspect_ratio` (`1:1` / `2:3` / `3:2` / `3:4` / `4:3` / `4:5` / `5:4` / `9:16` / `16:9` / `21:9` — auto-detected from source if omitted).

Model limits:

- `gemini-2.5-flash-image` — max 3 images
- `gemini-3-pro-image-preview` — max 14 images
- `gemini-3.1-flash-image-preview` — max 14 images

Random Source Selection:

- `use_random_source_selection` — enable selecting N images per call from `Source/`
- `use_deterministic_random` — same seed ⇒ same selections every run (reproducible)
- `random_seed` — explicit seed (auto-generated from folder path if omitted)
- `min_images` / `max_images` — range per call
- `num_iterations` — how many calls (defaults to source file count)
- `generations_per_source` — calls per source group (default 1); e.g., 50 iterations × 5 generations = 250 total calls
- Optimal formula: `sources_needed = num_iterations × (min_images + max_images) / 2`

Reference images:

- `use_reference_images: true` — prepend reference images from `<task_folder>/Reference/` to every call
- Reference images **do not** count toward `min_images` / `max_images`
- E.g., with 1 reference and `min_images=1, max_images=4`, the API receives 2 – 5 images per call

Error 429 retry:

Nano Banana retries `429 RESOURCE_EXHAUSTED` errors across runs. The count persists in each file's `_metadata.json` as `error429_retries`; cap is `max_retries_error429` (default `3`) in `api_definitions.json`.

#### OpenAI Image (`config/batch_openai_image_config.yaml`)

Image generation using OpenAI's `gpt-image-N` family — same multi-image / random-source / reference-image features as Nano Banana.

```yaml
testbed: http://192.168.31.161/external-testbed/image_generation/

output:
  directory: /Users/ethanhsu/Desktop/EthanHsu-cl/GAI/Report
  group_tasks_by: 1

tasks:
  - folder: Media Files/OpenAI Image/0520 Sample
    model: gpt-image-2
    quality: auto
    resolution: "1K"
    aspect_ratio: "16:9"
    prompt: |
      Photorealistic broadcast-style portrait...
    use_random_source_selection: false
    use_deterministic_random: true
    random_seed: 42
    min_images: 1
    max_images: 4
    num_iterations: 0
    generations_per_source: 1
    use_reference_images: false
```

Options:

- **Models:** `gpt-image-1`, `gpt-image-2`
- **Quality:** `auto` / `low` / `medium` / `high`
- **Resolution:** `1K` / `2K`
- **Aspect ratio:** `auto`, `1:1`, `2:3`, `3:2`, `3:4`, `4:3`, `4:5`, `5:4`, `9:16`, `16:9`, `21:9`
- Reuses the **Random Source Selection** and **Reference Images** behavior from Nano Banana.

#### GenVideo (`config/batch_genvideo_config.yaml`)

```yaml
testbed: http://192.168.31.161/external-testbed/genvideo/

tasks:
  - folder: /path/to/TaskName1
    img_prompt: "Generate a gashapon capsule"
    model: gpt-image-1
    quality: low
```

**Models:** `gpt-image-1`, `gemini-2.5-flash-image-preview` | **Quality:** `low` / `medium` / `high`.

---

### Pipelines (FIFA I2I2V, I2I2V)

Two image-to-image-to-video pipelines that chain an image-generation step with a video-generation step.

#### FIFA I2I2V (`config/batch_fifa_i2i2v_config.yaml`)

Per source image, optionally generate a start frame and/or end frame from prompts, then generate the final video from whichever frames were produced. Defaults to Kling 3.0 Pro for the video step.

```yaml
root_folder: Media Files/FIFA_I2I2V
generation_count: 1

default_settings:
  frame_model: gemini-3-pro-image-preview
  generate_start: true
  generate_end: false
  service: kling
  model: v3              # Kling 3.0
  kling_mode: pro
  kling_duration: '5'
  kling_ratio: '16:9'

tasks:
  - style_name: Statue Selfie
    folder: Media Files/FIFA_I2I2V/0518 1 Styles/Statue Selfie
    generate_start: true
    generate_end: false
    start_frame_prompt: "Person standing next to a marble statue in a museum, golden-hour light."
    end_frame_prompt: ""
    video_prompt: "Cinematic slow push-in; statue subtly comes alive."
    video_negative_prompt: ""
```

**Pipeline:** `/on_generate_frame` (if `generate_start`) → `/on_generate_frame_1` (if `generate_end`) → `/on_generate_video`. At least one of `generate_start` / `generate_end` must be true.

**Supported video services:** `kling`, `wan`, `pixverse`, `google_veo`, `seedance`.

Folder layout:

```bash
root_folder/
├── {style_name}/
│   ├── Source/             # input images
│   ├── Generated_Frames/   # {name}_{n}_start.png / {name}_{n}_end.png
│   ├── Generated_Video/    # {name}_{n}.mp4
│   └── Metadata/
```

#### I2I2V (`config/batch_i2i2v_config.yaml`)

Generic two-step pipeline: **image generation** (Nano Banana **or** OpenAI Image) **→ video generation** (Kling). Each task chooses its image service and video model.

```yaml
testbed: http://192.168.31.161/external-testbed/image_generation/

output:
  directory: /Users/ethanhsu/Desktop/EthanHsu-cl/GAI/Report
  group_tasks_by: 2

tasks:
  - style_name: 滑草V10
    folder: Media Files/I2I2V/0522 滑草V10
    # ---- Image generation step ----
    image_service: nano_banana             # 'nano_banana' or 'openai_image'
    image_model: gemini-3.1-flash-image-preview
    image_quality: auto                    # openai_image only: auto / low / medium / high
    image_resolution: '1K'
    image_aspect_ratio: '9:16'
    image_prompt: |
      ...
    # ---- Video generation step (Kling) ----
    video_model: v3
    video_mode: pro
    video_duration: 5
    video_ratio: '9:16'
    video_prompt: |
      ...
    video_negative_prompt: ''
```

Image-step models:

- `nano_banana`: `gemini-3.1-flash-image-preview`, `gemini-3-pro-image-preview`, `gemini-2.5-flash-image`
- `openai_image`: `gpt-image-1`, `gpt-image-2`

**Video-step models:** Kling `v1.6`, `v1.5`, `v2.0-master`, `v2.1`, `v2.1-master`, `v2.5-turbo`, `v2.6`, `v3`.

Folder layout:

```bash
{folder}/
├── Source/              # input reference images
├── Generated_Frames/    # intermediate generated images (reused on resume)
├── Generated_Video/     # final mp4s
└── Metadata/
```

---

### Other (Runway, Wan 2.2, DreamActor)

#### Runway (`config/batch_runway_config.yaml`)

```yaml
testbed: http://192.168.31.161/external-testbed/runway/
model: gen4_aleph
ratio: 1280:720
public_figure_moderation: low   # low / medium / high

tasks:
  - folder: /path/to/TaskName1
    prompt: "Face swap effect"
    pairing_strategy: all_combinations   # or 'one_to_one'
```

**Pairing:** `one_to_one` (1:1 mapping) or `all_combinations` (N × M outputs).
**Ratios:** `1280:720`, `720:1280`, `1104:832`, `960:960`, `832:1104`, `1584:672`, `848:480`, `640:480`.

#### Wan 2.2 (`config/batch_wan_config.yaml`)

```yaml
testbed: http://210.244.31.18:7007/

tasks:
  - folder: Media Files/Wan 2.2/Test
    prompt: "The person is dancing"
    animation_mode: move   # or 'mix'
```

**Cross-matching:** all videos × all images (e.g., 5 videos × 4 images = 20 outputs). Requires `Source Image/` and `Source Video/` folders.

#### DreamActor (`config/batch_dreamactor_config.yaml`)

Same `Source Image/` + `Source Video/` cross-match pattern as Wan 2.2; targets face reenactment.

```yaml
testbed: http://192.168.31.161/external-testbed/video_effect/

tasks:
  - folder: Media Files/DreamActor/Style1
    use_base64: true
    cut_switch: true
```

**Options:** `use_base64`, `cut_switch`, `video_url_direct`.

#### Motion Swap (`config/batch_motion_swap_config.yaml`)

Same `Source Image/` + `Source Video/` cross-match pattern as DreamActor; transfers the motion of each reference video onto each subject image. Takes no extra API parameters.

```yaml
testbed: http://192.168.31.161/external-testbed/video_effect/

tasks:
  - folder: Media Files/Motion Swap/0529 9 Style
    use_comparison_template: false
```

**Options:** none beyond the standard task fields (`folder`, `design_link`, `source_video_link`, `reference_folder`, `use_comparison_template`).

#### HappyHorse Video Edit (`config/batch_happyhorse_vedit_config.yaml`)

Edits a source video guided by a prompt and up to 5 optional reference images. Each task folder holds source videos in `Source/` and (optionally) reference images in `Reference/`. Reference behavior mirrors Nano Banana: by default all references are appended after the source video (sent as `i1..i5`), or set `reference_cross_match: true` to pair each source video with each reference image individually.

```yaml
testbed: http://192.168.31.161/external-testbed/video_effect/

default_settings:
  model: happyhorse-1.0-video-edit
  resolution: "720P"        # "1080P" | "720P"
  audio_setting: origin     # "auto" | "origin"
  seed: -1                  # -1 for random

tasks:
  - folder: Media Files/HappyHorse Video Edit/0602 Video Edit
    prompt: |
      Describe the edit to apply to the source video here.
    use_reference_images: false   # send Reference/ images as i1..i5
    reference_cross_match: false  # true → each video × each reference individually
```

Defaults: `happyhorse-1.0-video-edit` model, `720P`, `origin` audio, random seed; one generation per source video (references appended) unless `reference_cross_match` is enabled.

**Options:** `model`, `resolution`, `audio_setting`, `seed`, `use_reference_images`, `reference_cross_match` (all overridable per task).

---

## 📊 Report Generation

PowerPoint reports are generated automatically with title slides, side-by-side comparisons, per-slide metadata boxes, and hyperlinks.

- **Templates:** `Scripts/templates/I2V templates.pptx`, `I2V Comparison Template.pptx`
- **Output:** `Report/[MMDD] API Name Task Name.pptx`

Run `python core/runall.py <platform> report` to regenerate the report from existing media (no re-processing).

### Cross-API Comparison Reports

Compare the same source against multiple APIs in a single report. Add a `comparison_folders` list to any config (e.g. `batch_motion_swap_config.yaml`). The primary task folder (`tasks[0].folder`) plus each listed folder become **labeled columns** sharing the same source media, so you can see each API's result side-by-side.

```yaml
comparison:
  primary_label: ''          # optional label for the primary folder's column
comparison_folders:
  - folder: Media Files/DreamActor/0529 9 Style
    label: ''                # optional; defaults to the folder's api_name
  - folder: Media Files/Wan 2.2/0529 9 Style
```

Then run `python core/runall.py motion_swap report` — the presence of `comparison_folders` switches the run into comparison mode and writes `Report/[MMDD] Comparison A vs B vs C.pptx`.

Rules:

- **Same family only.** Folders must be the same structural kind — image+video (`motion_swap`, `dreamactor`, `wan`, `kling_motion`) compare together; image-to-video (`kling`, `vidu_i2v`, `veo_itv`, `seedance_i2v`) compare together. Mixing families (e.g. image+video with text-to-video) **stops the run with an error**.
- **Auto-labeled.** Each column's label is read from that folder's metadata `api_name`; override per folder with `label`.
- **Matching.** Entries are matched across folders by their shared source — image+video matches on `(source_image, source_video)`; image-to-video matches on `source_image`. A folder missing a given combination shows a "Missing / failed" box for that cell.
- Currently supported families for rendering: **image+video** and **image-to-video**.

## 🖥️ Desktop GUI

A graphical desktop app provides the same functionality without using the command line.

```bash
cd Scripts
python gui_app.py
```

Or run the packaged executable — see [build_executable.md](build_executable.md).

### GUI controls

| Control | Description |
| --- | --- |
| **Platform** | Select which AI API to use |
| **Action** | Process + Report (Auto) / Process Only / Report Only |
| **Configuration File** | The YAML file with settings; click **Use Default** to auto-select the standard one for the chosen platform |
| **Task Folder** | (Optional) override the folder path in the config for this run |
| **Run in Parallel** | When running "All Platforms", process multiple APIs simultaneously |
| **Verbose Logging** | Show debug messages in the log console |

### Advanced Options

Click **▶ Advanced Options** to expand the override section. You can temporarily change config values **without editing the YAML file on disk**.

Format:

```text
key = value
key: value
tasks.0.prompt = Override the first task's prompt
```

### Important notes

- Runtime overrides are temporary — they apply to the current run only.
- FFmpeg must be installed locally for video processing.
- Reports are saved to the `Report/` folder with date-prefixed filenames.
- For the bundled `.app`, the working directory defaults to your home folder; use absolute paths or the folder picker.

## 📦 Building the Desktop App

```bash
cd Scripts
pip install pyinstaller
pyinstaller --name "AI Video Suite" --onedir --windowed \
    --add-data "config:config" --add-data "templates:templates" \
    --add-data "core:core" --add-data "handlers:handlers" \
    --hidden-import ruamel.yaml --collect-data gradio_client gui_app.py
```

The app bundle is created at `Scripts/dist/AI Video Suite.app` (macOS) or `Scripts/dist/AI Video Suite.exe` (Windows).

For detailed instructions including troubleshooting, distribution, and platform-specific options, see [build_executable.md](build_executable.md).

## 🔧 Architecture

The framework uses an auto-discovery handler system.

- **`HandlerRegistry`** — auto-discovers and registers API handlers by scanning `handlers/*_handler.py`
- **`BaseAPIHandler`** — common processing logic (validation, metadata, retries, connection backoff, 429/timeout handling)
- **`UnifiedAPIProcessor`** — image conversion, video extraction, optimal ratio matching, file downloads
  - **Sleep prevention** — on macOS uses native `caffeinate -di` subprocess tracked by PID; on other platforms uses `wakepy`. Cleanup is guaranteed via `finally`, `atexit`, and `SIGINT` / `SIGTERM` handlers so orphaned processes can't block sleep. Multiple concurrent script instances are safe.
- **`UnifiedReportGenerator`** — PowerPoint generation with parallel metadata loading

**23 API handlers:** Kling, KlingEffects, KlingEndframe, KlingTTV, KlingMotion, PixverseI2v, PixverseEffect, PixverseTTV, ViduEffects, ViduReference, ViduI2v, SeedanceTtv, SeedanceI2v, Veo, VeoItv, NanoBanana, OpenaiImage, Genvideo, Runway, Wan, DreamActor, FifaI2i2v, I2i2v.

All APIs use deterministic file sorting for reproducible results.

## 📁 Project Structure

```bash
GAI/
└── Scripts/
    ├── config/                              # YAML configs (one per API)
    │   ├── batch_kling_config.yaml
    │   ├── batch_kling_effects_config.yaml
    │   ├── batch_kling_endframe_config.yaml
    │   ├── batch_kling_ttv_config.yaml
    │   ├── batch_kling_motion_config.yaml
    │   ├── batch_pixverse_i2v_config.yaml
    │   ├── batch_pixverse_effect_config.yaml
    │   ├── batch_pixverse_ttv_config.yaml
    │   ├── batch_vidu_effects_config.yaml
    │   ├── batch_vidu_reference_config.yaml
    │   ├── batch_vidu_i2v_config.yaml
    │   ├── batch_seedance_ttv_config.yaml
    │   ├── batch_seedance_i2v_config.yaml
    │   ├── batch_veo_config.yaml
    │   ├── batch_veo_itv_config.yaml
    │   ├── batch_nano_banana_config.yaml
    │   ├── batch_openai_image_config.yaml
    │   ├── batch_genvideo_config.yaml
    │   ├── batch_runway_config.yaml
    │   ├── batch_wan_config.yaml
    │   ├── batch_dreamactor_config.yaml
    │   ├── batch_fifa_i2i2v_config.yaml
    │   └── batch_i2i2v_config.yaml
    ├── core/
    │   ├── api_definitions.json            # API specifications (endpoints, params, defaults)
    │   ├── runall.py                       # Main CLI entry point
    │   ├── unified_api_processor.py        # Processing engine
    │   └── unified_report_generator.py     # Report generation engine
    ├── handlers/                            # One handler per API (auto-discovered)
    │   ├── base_handler.py
    │   ├── handler_registry.py
    │   ├── kling_handler.py
    │   ├── kling_effects_handler.py
    │   ├── kling_endframe_handler.py
    │   ├── kling_ttv_handler.py
    │   ├── kling_motion_handler.py
    │   ├── pixverse_i2v_handler.py
    │   ├── pixverse_effect_handler.py
    │   ├── pixverse_ttv_handler.py
    │   ├── vidu_effects_handler.py
    │   ├── vidu_reference_handler.py
    │   ├── vidu_i2v_handler.py
    │   ├── seedance_ttv_handler.py
    │   ├── seedance_i2v_handler.py
    │   ├── veo_handler.py
    │   ├── veo_itv_handler.py
    │   ├── nano_banana_handler.py
    │   ├── openai_image_handler.py
    │   ├── genvideo_handler.py
    │   ├── runway_handler.py
    │   ├── wan_handler.py
    │   ├── dreamactor_handler.py
    │   ├── fifa_i2i2v_handler.py
    │   └── i2i2v_handler.py
    ├── templates/                           # PowerPoint templates
    │   ├── I2V templates.pptx
    │   ├── I2V templates 3rd party.pptx
    │   └── I2V Comparison Template.pptx
    ├── gui_app.py                           # Tk-based GUI
    └── requirements.txt
```

---

> **Tip:** Download videos with: `yt-dlp -f "bv*[vcodec~='^(h264|avc)']+ba[acodec~='^(mp?4a|aac)']" "URL" -o "%(title)s.%(ext)s"`
