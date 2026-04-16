# Automated Processing & Reporting Automation Suite

A Python automation framework for batch processing images/videos through 15 AI APIs with automated PowerPoint report generation.

## 🚀 Quick Start (Command Line)

### **Basic Usage**

```bash
cd Scripts

# Syntax: python core/runall.py <platform> <action> [options]
python core/runall.py kling auto      # Process + generate report
python core/runall.py nano process    # Process only
python core/runall.py pixverse report # Report only
python core/runall.py all auto        # All APIs at once

# Options
--parallel    # Run APIs in parallel
--config FILE # Custom config file
--verbose     # Debug logging
```

## 🖥️ Desktop GUI Usage

For non-technical users, a graphical desktop application is available that provides all the same functionality without using the command line.

### **Launching the GUI**

```bash
cd Scripts
python gui_app.py
```

Or run the packaged executable (see [build_executable.md](build_executable.md) for packaging instructions).

### **GUI Controls**

| Control | Description |
| :-- | :-- |
| **Platform** | Select which AI API to use (Kling, Nano Banana, Veo, etc.) |
| **Action** | Choose what to do: Process + Report (Auto), Process Only, or Report Only |
| **Configuration File** | The YAML file containing settings for this job. Click "Use Default" to auto-select the standard config for the chosen platform |
| **Task Folder** | (Optional) Override the folder path in the config file for this run |
| **Run in Parallel** | When running "All Platforms", process multiple APIs simultaneously |
| **Verbose Logging** | Show detailed debug messages in the log console |

### **Advanced Options**

Click "▶ Advanced Options" to expand the override section. Here you can temporarily change config values **without editing the YAML file on disk**.

**Override Format:**

```bash
key = value
key: value
```

**Examples:**

```bash
prompt = A cat dancing in the rain
duration = 10
model_version = v2.5-turbo
tasks.0.prompt = Override the first task's prompt
```

### **Workflow Examples**

#### Example 1: Kling Image-to-Video

1. Select **Platform**: "kling" (Kling 2.1)
2. Select **Action**: "Auto (Process + Report)"
3. Click **"Use Default"** for config (loads `batch_kling_config.yaml`)
4. (Optional) Enter a **Task Folder** to override the folder in config
5. Click **"▶ Run"**
6. Watch progress in the log console
7. When complete, click **"📂 Open Report Folder"** to view the generated PowerPoint

#### Example 2: Nano Banana Multi-Image

1. Select **Platform**: "nano" (Nano Banana / Google Flash)
2. Select **Action**: "Auto"
3. The default config `batch_nano_banana_config.yaml` is auto-selected
4. Expand **Advanced Options** and enter:

   ```bash
   prompt = Generate a magical forest scene
   ```

5. Click **"▶ Run"**

#### Example 3: Veo ITV (Image-to-Video)

1. Select **Platform**: "veoitv" (Veo ITV)
2. Select **Action**: "Process Only" (generate videos without report)
3. Click **Browse...** and select your custom YAML config
4. Click **"▶ Run"**
5. Videos will be saved to `Generated_Video/` in each style folder

### **API-Specific Advanced Options**

When you select a platform, the Advanced Options section shows API-specific fields that can be configured:

| API | Available Options |
| :-- | :-- |
| **Kling** | Mode, Duration (5/10s), CFG Scale (0.0-1.0) |
| **Kling Effects** | Duration, Effect Name, Preset Effect |
| **Kling Endframe** | Duration, CFG, Generation Count, Pairing Mode |
| **Kling TTV** | Mode, Duration, Ratio, CFG Scale, Generation Count, Sound |
| **Kling Motion** | Model, Character Orientation, Mode, Keep Original Sound, Element IDs |
| **Nano Banana** | Model, Resolution, Aspect Ratio, Random Source Selection, Deterministic Random, Seed, Min/Max Images, Iterations, Generations per Source, Reference Images |
| **Veo / Veo ITV** | Model, Duration, Aspect Ratio, Resolution, Person Generation, Enhance Prompt, Generate Audio |
| **Pixverse** | Model, Duration, V6 Duration, Quality, Motion Mode, Style, Seed, Generate Audio, Multi Clip, Thinking Type |
| **Pixverse TTV** | Model, Aspect Ratio, Duration, V6 Duration, Quality, Motion Mode, Style, Seed, Generate Audio, Multi Clip, Thinking Type |
| **Runway** | Model, Aspect Ratio, Pairing Strategy, Public Figure Moderation |
| **Wan** | Animation Mode, Num Outputs, Seed, Embed |
| **DreamActor** | Use Base64, Cut Switch, Video URL |
| **Vidu Effects** | Category, Effect, Model |
| **Vidu Reference** | Model, Duration, Resolution, Movement |

These options override the corresponding values in the config file for the current run.

### **Important Notes**

- **Runtime overrides are temporary** — they only apply to the current run and do NOT modify your YAML config files
- **FFmpeg required** — video processing requires FFmpeg to be installed on your system
- **Network required** — the app connects to API servers defined in your config files
- **Reports saved to** `Report/` folder with date-prefixed filenames
- **Bundled app working directory** — when running the packaged `.app`, the working directory defaults to your home folder; use absolute paths or the folder picker for config paths

## 📋 Platform Commands

| Short Name | Full Name | Description |
| :-- | :-- | :-- |
| `kling` | Kling 2.5 | Image-to-video generation with v2.5-turbo model |
| `klingfx` | Kling Effects | Apply premade video effects to images |
| `kling_endframe` | Kling Endframe | Start/end frame video generation (A→B transitions) |
| `kling_ttv` | Kling TTV | Text-to-video generation (no input images) |
| `klingmotion` | Kling Motion | Image + video motion control via cross-matching |
| `pixverse` | Pixverse v6 | Effect-based video generation with custom effects |
| `pixversettv` | Pixverse TTV | Text-to-video generation (no input images) |
| `genvideo` | GenVideo | Image-to-image transformation (Gashapon style) |
| `nano` | Nano Banana/Google Flash | Multi-image generation with AI models |
| `vidu` | Vidu Effects | Effect-based video generation with categories |
| `viduref` | Vidu Reference | Multi-reference guided video generation |
| `runway` | Runway Gen4 | Video processing with face swap and effects |
| `wan` | Wan 2.2 | Image + video cross-matching with motion animation |
| `dreamactor` | DreamActor | Image + video face reenactment via cross-matching |
| `veo` | Google Veo | Text-to-video generation with AI models |
| `veoitv` | Google Veo ITV | Image-to-video generation with AI models |
| `all` | All Platforms | Process all APIs sequentially or in parallel |

## 📁 Project Structure

```bash
GAI/                                    # Project root
└── Scripts/                           # Main scripts directory
    ├── config/                        # Configuration files (YAML format)
    │   ├── batch_kling_config.yaml        # Kling I2V configuration
    │   ├── batch_kling_effects_config.yaml # Kling Effects configuration
    │   ├── batch_kling_endframe_config.yaml # Kling Endframe configuration
    │   ├── batch_kling_ttv_config.yaml    # Kling TTV configuration
    │   ├── batch_kling_motion_config.yaml  # Kling Motion configuration
    │   ├── batch_pixverse_config.yaml     # Pixverse configuration
    │   ├── batch_pixverse_ttv_config.yaml  # Pixverse TTV configuration
    │   ├── batch_genvideo_config.yaml     # GenVideo configuration
    │   ├── batch_nano_banana_config.yaml  # Nano Banana configuration
    │   ├── batch_runway_config.yaml       # Runway configuration
    │   ├── batch_vidu_effects_config.yaml # Vidu Effects configuration
    │   ├── batch_vidu_reference_config.yaml # Vidu Reference configuration
    │   ├── batch_wan_config.yaml          # Wan 2.2 configuration
    │   ├── batch_dreamactor_config.yaml    # DreamActor configuration
    │   ├── batch_veo_config.yaml          # Google Veo configuration
    │   └── batch_veo_itv_config.yaml      # Google Veo ITV configuration
    ├── core/                          # Core automation framework
    │   ├── api_definitions.json      # API specifications
    │   ├── runall.py                 # Main execution script
    │   ├── unified_api_processor.py  # API processing engine
    │   └── unified_report_generator.py # Report generation engine
    ├── handlers/                      # API-specific handlers
    │   ├── base_handler.py           # Base handler class
    │   ├── handler_registry.py       # Auto-discovery registry
    │   ├── kling_handler.py          # Kling I2V handler
    │   ├── kling_effects_handler.py  # Kling Effects handler
    │   ├── kling_endframe_handler.py # Kling Endframe handler
    │   ├── kling_ttv_handler.py      # Kling TTV handler
    │   ├── kling_motion_handler.py   # Kling Motion handler
    │   └── ...                       # Other API handlers
    ├── processors/                    # Legacy individual processors
    ├── reports/                       # Legacy individual report generators
    ├── templates/                     # PowerPoint templates
    │   ├── I2V Comparison Template.pptx
    │   └── I2V templates.pptx
    └── requirements.txt
```

### **Folder Structure**

```bash
TaskFolder/
├── Source/              # Input images/videos (most APIs)
├── Source Image/        # Wan 2.2: source images
├── Source Video/        # Wan 2.2: source videos  
├── Additional/          # Nano Banana: extra images
├── Reference/           # Runway, Vidu Reference, Nano Banana (with use_reference_images): reference images
├── Generated_Video/     # Auto-created video outputs
├── Generated_Output/    # Auto-created outputs (Nano Banana)
├── Generated_Image/     # Auto-created outputs (GenVideo)
└── Metadata/            # Auto-created metadata
```

**API-specific input folders:**

- Most APIs: `Source/`
- Wan 2.2: `Source Image/` + `Source Video/` (cross-matched)
- DreamActor: `Source Image/` + `Source Video/` (cross-matched)
- Kling Motion: `Source Image/` + `Source Video/` (cross-matched)
- Nano Banana multi-image: `Source/` + `Additional/` (or `Source/` only with random selection mode) + optional `Reference/`
- Runway/Vidu Reference: `Source/` + `Reference/`

## ⚙️ Configuration Files

All configuration files are located in the `Scripts/config/` directory and follow API-specific naming conventions.

**Common Configuration Fields** (applicable to most APIs):

- **`design_link`**: URL to design reference materials (optional)
- **`source_video_link`**: URL to source video reference (optional)
- **`reference_folder`**: Path to reference comparison folder (optional)
- **`use_comparison_template`**: Enable comparison template for reports (boolean)
- **`schedule.start_time`**: Delayed start in `HH:MM` 24-hour format (leave empty for immediate)
- **`output.group_tasks_by`**: Group N tasks into one combined report (0 = individual reports)
- **`template_path`**: Path to the PowerPoint template file
- **`output_directory`**: Directory for generated PPTX report files

### **Kling Configuration** (`config/batch_kling_config.yaml`)

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

**Options:** Model (`v1.6`/`v2.1`/`v2.5-turbo`), Mode (`std`/`pro`), Duration (`5`/`10`), CFG (`0.0`-`1.0`)

### **Kling Effects Configuration** (`config/batch_kling_effects_config.yaml`)

Applies premade video effects to images. Supports both preset effects and custom effect names.

```yaml
base_folder: Media Files/Kling Effects/1127 Test
testbed: http://192.168.31.161/external-testbed/kling/

# Global settings
duration: '5'

# Effect selection (custom_effect has priority over effect)
effect: 3d_cartoon_1      # Preset effect from dropdown
custom_effect: ''          # Custom effect name (priority if specified)

tasks:
  - style_name: 3D Cartoon
    effect: 3d_cartoon_1
    custom_effect: ''       # Leave empty to use preset 'effect'
  
  - style_name: Custom Style
    effect: ''
    custom_effect: my_custom_effect  # Custom effect takes priority
```

**Effect Selection:**

- Use `effect` to select from 100+ preset effects (e.g., `3d_cartoon_1`, `anime_figure`, `japanese_anime_1`)
- Use `custom_effect` to specify a custom effect name (takes priority over `effect`)

**Available Preset Effects (partial list):**
`3d_cartoon_1`, `3d_cartoon_2`, `anime_figure`, `japanese_anime_1`, `american_comics`, `angel_wing`, `baseball`, `boss_coming`, `car_explosion`, `celebration`, `demon_transform`, `disappear`, `emoji`, `firework`, `gallery_ring`, `halloween_escape`, `jelly_jiggle`, `magic_broom`, `mushroom`, `pixelpixel`, `santa_gifts`, `steampunk`, `vampire_transform`, `zombie_transform`, and many more.

**Folder Structure:**

```bash
BaseFolder/
├── StyleName1/
│   ├── Source/              # Input images
│   ├── Generated_Video/     # Auto-created output folder
│   └── Metadata/            # Auto-created metadata folder
├── StyleName2/
│   └── ...
```

### **Kling Endframe Configuration** (`config/batch_kling_endframe_config.yaml`)

Generates videos from start and end frame image pairs, creating smooth A→B transitions.

```yaml
testbed: http://192.168.31.161/external-testbed/kling/
model_version: v2.1
generation_count: 1  # Global default, can override per task

output:
  directory: /Users/ethanhsu/Desktop/EthanHsu-cl/GAI/Report
  group_tasks_by: 3  # Combine N tasks into one report (0 = individual)

tasks:
  - mode: pro
    folder: Media Files/Kling Endframe/1030 3 Styles/Anime Awakening
    prompt: "Smooth transition from start to end frame"
    negative_prompt: ""
    duration: 5
    cfg: 0.5
    pairing_mode: ab_naming  # or 'sequential'
    generation_count: 3      # Override global setting
```

**Pairing Modes:**

- **`ab_naming`** (default): Pairs `Style_A.jpg` with `Style_B.jpg`
- **`sequential`**: First half = start frames, second half = end frames

**Parameters:** `mode` (pro/std), `duration` (5/10), `cfg` (0.0-1.0), `model_version` (v1.6/v2.1), `generation_count`

### **Kling TTV Configuration** (`config/batch_kling_ttv_config.yaml`)

Text-to-video generation (no input images required).

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
    generation_count: 1
    sound_enabled: true
```

**Options:** Model (`v1.6`/`v2.0-master`/`v2.1-master`/`v2.5-turbo`), Mode (`std`/`pro`), Ratio (`16:9`/`9:16`/`1:1`), `sound_enabled` (true/false), `generation_count`

### **Kling Motion Configuration** (`config/batch_kling_motion_config.yaml`)

Image + video motion control generation. Cross-matches all reference images with all motion source videos.

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
    prompt: ''
    model: v3
    character_orientation: video
    mode: pro
    keep_original_sound: true
    element_list_str: ''
```

**Folder Structure:**

```bash
TaskFolder/
├── Source Image/        # Reference images (character appearance)
├── Source Video/        # Motion source videos
├── Generated_Video/     # Auto-created output folder
└── Metadata/            # Auto-created metadata folder
```

**Options:** Model (`v2.6`/`v3`), Character Orientation (`image`/`video`), Mode (`std`/`pro`), `keep_original_sound` (true/false), `element_list_str` (comma-separated IDs)

### **Nano Banana Configuration** (`config/batch_nano_banana_config.yaml`)

Supports two modes: **Random Source Selection** (select N random images from Source folder per API call) and **Multi-Image** (Source + Additional folder pairing).

```yaml
testbed: http://192.168.31.161/external-testbed/image_generation/

output:
  group_tasks_by: 2

schedule:
  start_time: ""  # HH:MM or empty for immediate

tasks:
  # Random Source Selection mode (recommended)
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

  # Multi-Image mode (Source + Additional folder)
  - folder: /path/to/TaskName2
    model: gemini-2.5-flash-image
    prompt: "Generate variations"
    use_multi_image: true
    multi_image_config:
      mode: sequential  # or 'random_pairing'
      folders: ["/path/to/Additional/"]
```

**Per-task fields:** `model`, `resolution` (`1K`/`2K`), `aspect_ratio` (`1:1`/`2:3`/`3:2`/`3:4`/`4:3`/`4:5`/`5:4`/`9:16`/`16:9`/`21:9` — auto-detected from source if omitted)

**Model limits:** `gemini-2.5-flash-image` (max 3 images), `gemini-3-pro-image-preview` (max 14 images)

**Random Source Selection:**

- `use_random_source_selection`: Enable selecting N images from Source folder per API call
- `use_deterministic_random`: Same seed = same selections every run (reproducible)
- `random_seed`: Explicit seed for deterministic mode (auto-generated from folder path if omitted)
- `min_images` / `max_images`: Range of images per API call
- `num_iterations`: Number of API calls to make (defaults to source file count)
- `generations_per_source`: Number of generations per source group (default: `1`). Each iteration's selected images are sent N times. Example: 50 iterations × 5 generations = 250 total API calls.
- Optimal formula: `sources_needed = num_iterations × (min_images + max_images) / 2`

**Reference Images:**

- `use_reference_images`: Set to `true` to prepend reference images to every API call
- Place reference images in `<task_folder>/Reference/` (same level as `Source/`)
- Reference images do **not** count toward `min_images` / `max_images` limits
- Example: With 1 reference image and `min_images=1`, `max_images=4`, the API receives 2–5 images (1 ref + 1–4 source)

#### Error 429 (Resource Exhausted) Retry

Nano Banana has built-in handling for Google API `429 RESOURCE_EXHAUSTED` errors. When this error occurs, the retry count is saved to the file's metadata and the file is retried on the next script run.

- **`max_retries_error429`** (default: `3`) — Set in `api_definitions.json` under the `nano_banana` entry. Controls how many re-runs will retry a 429-failed file.
- The count is persisted in each file's `_metadata.json` as `error429_retries` and increments on each 429 failure.
- On re-run, files with 429 errors below the limit are retried; once the limit is reached they are skipped.

### **Vidu Effects Configuration** (`config/batch_vidu_effects_config.yaml`)

```yaml
base_folder: Media Files/Vidu/1027 Product
testbed: http://192.168.31.161/external-testbed/video_effect/
model_version: viduq2-pro

tasks:
  - category: Product
    effect: Auto Spin
```

### **Vidu Reference Configuration** (`config/batch_vidu_reference_config.yaml`)

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

**Options:** Duration (`4`/`5`/`8`s), Resolution (`720p`/`1080p`), up to 6 reference images per source

### **Pixverse Configuration** (`config/batch_pixverse_config.yaml`)

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

**Defaults:** Model v6, Duration 5s, Quality 540p, Motion Mode normal, Seed -1

### **Pixverse TTV Configuration** (`config/batch_pixverse_ttv_config.yaml`)

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

**Defaults:** Model v6, Aspect Ratio 16:9, Duration 5s, Quality 540p, Seed -1

### **Seedance TTV Configuration** (`config/batch_seedance_ttv_config.yaml`)

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

**Defaults:** Model dreamina-seedance-2-0-260128, Aspect Ratio adaptive, Duration 5s, Resolution 720p, Seed -1, Audio enabled

### **Seedance I2V Configuration** (`config/batch_seedance_i2v_config.yaml`)

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

**Defaults:** Model dreamina-seedance-2-0-260128, Aspect Ratio adaptive, Duration 5s, Resolution 720p, Seed -1, Audio enabled. Each task folder must contain a `Source` subfolder with input images.

### **GenVideo Configuration** (`config/batch_genvideo_config.yaml`)

```yaml
testbed: http://192.168.31.161/external-testbed/genvideo/

tasks:
  - folder: /path/to/TaskName1
    img_prompt: "Generate a gashapon capsule"
    model: gpt-image-1
    quality: low
```

**Models:** `gpt-image-1`, `gemini-2.5-flash-image-preview` | **Quality:** `low`/`medium`/`high`

### **Runway Configuration** (`config/batch_runway_config.yaml`)

```yaml
testbed: http://192.168.31.161/external-testbed/runway/
model: gen4_aleph
ratio: 1280:720
public_figure_moderation: low  # low/medium/high

tasks:
  - folder: /path/to/TaskName1
    prompt: "Face swap effect"
    pairing_strategy: all_combinations  # or 'one_to_one'
```

**Pairing:** `one_to_one` (1:1 mapping) or `all_combinations` (N×M outputs)
**Ratios:** `1280:720`, `720:1280`, `1104:832`, `960:960`, `832:1104`, `1584:672`, `848:480`, `640:480`

### **Wan 2.2 Configuration** (`config/batch_wan_config.yaml`)

```yaml
testbed: http://210.244.31.18:7007/

tasks:
  - folder: Media Files/Wan 2.2/Test
    prompt: "The person is dancing"
    animation_mode: move  # or 'mix'
```

**Cross-matching:** All videos × all images (e.g., 5 videos × 4 images = 20 outputs)
**Requires:** `Source Image/` and `Source Video/` folders

### **Veo Configuration** (`config/batch_veo_config.yaml`)

Text-to-video generation (no input images required).

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

**Models:** `veo-2.0-generate-001`, `veo-3.0-generate-001`, `veo-3.0-fast-generate-001`, `veo-3.0-generate-preview`, `veo-3.1-generate-preview`, `veo-3.1-fast-generate-preview`, `veo-3.1-generate-001`, `veo-3.1-fast-generate-001`
**Options:** Ratio (`16:9`/`9:16`), Resolution (`720p`/`1080p`), `compression_quality` (`optimized`/`lossless`), `enhance_prompt`, `generate_audio`, `person_generation` (`allow_all`/`allow_adult`/`dont_allow`)

### **Veo ITV Configuration** (`config/batch_veo_itv_config.yaml`)

Image-to-video generation with source images.

```yaml
root_folder: Media Files/Veo_ITV
generation_count: 2  # Videos per source image

tasks:
  - style_name: Style 11_Statue Selfie
    folder: Media Files/Veo_ITV/Style 11_Statue Selfie
    prompt: "The statue comes to life in a cinematic motion."
    model_id: veo-3.1-generate-001
    duration_seconds: 8
```

**Folder Structure:**

```bash
root_folder/
├── Style 11_Statue Selfie/
│   ├── Source/           # Input images
│   ├── Generated_Video/  # {image_name}_{n}.mp4
│   └── Metadata/
```

**Output Naming:** `{source_image_name}_{generation_number}.mp4` (e.g., `selfie_1.mp4`, `selfie_2.mp4`)

## 📊 Report Generation

PowerPoint reports auto-generated with title slides, side-by-side comparisons, metadata tracking, and hyperlinks.

**Templates:** `Scripts/templates/I2V templates.pptx`, `I2V Comparison Template.pptx`
**Output:** `Report/[MMDD] API Name Task Name.pptx`

## 🔧 Installation

```bash
cd Scripts
pip install -r requirements.txt
brew install ffmpeg  # macOS (required for video processing)
```

**Requirements:** Python 3.8+, FFmpeg, 8GB+ RAM

**Key Dependencies:**

- `ruamel.yaml` - Round-trip YAML parsing that preserves formatting when saving config files
- `gradio_client` - API client for AI services
- `python-pptx` - PowerPoint report generation
- `opencv-python` - Video/image processing
- `pillow-heif` - HEIF/HEIC image format support
- `wakepy` - Cross-platform sleep prevention (used on non-macOS)
- `tqdm` - Progress bars for batch processing

## � Testbed Cookie Setup

The testbed at `192.168.31.161` requires browser cookie authentication. Each
user must provide their own cookie. The cookie is **never committed to Git**.

### Option 1: `.env` File (recommended for CLI / code usage)

```bash
cd Scripts
cp .env.example .env
```

Edit `.env` and paste your cookie:

```env
TESTBED_COOKIE=session_id=abc123; auth_token=xyz789
```

### Option 2: GUI Field

Open the GUI → Advanced Options → **Testbed Cookie** field. The field
auto-loads the value from `.env` on launch. You can paste a different cookie
here and it will be used for the current run only.

### Option 3: Environment Variable

Export the variable before running:

```bash
export TESTBED_COOKIE="session_id=abc123; auth_token=xyz789"
python core/runall.py kling auto
```

### How to Get Your Cookie

1. Open the testbed URL in your browser and log in.
2. Open DevTools (F12) → **Network** tab.
3. Reload the page and click any request to the testbed host.
4. Copy the full **Cookie** header value from the request headers.

## �📦 Building the Desktop App

To package the application as a standalone executable for distribution:

```bash
cd Scripts
pip install pyinstaller
pyinstaller --name "AI Video Suite" --onedir --windowed \
    --add-data "config:config" --add-data "templates:templates" \
    --add-data "core:core" --add-data "handlers:handlers" \
    --hidden-import ruamel.yaml --collect-data gradio_client gui_app.py
```

The app bundle will be created at `Scripts/dist/AI Video Suite.app` (macOS) or `Scripts/dist/AI Video Suite.exe` (Windows).

**For detailed instructions** including troubleshooting, distribution, and platform-specific options, see [build_executable.md](build_executable.md).

## 📈 File Requirements

| API | Max Size | Min Dimensions | Formats |
| ----- | ---------- | ---------------- | --------- |
| Kling | 10MB | 300px | JPG, PNG, WebP |
| Pixverse | 20MB | 128px | JPG, PNG |
| Nano Banana | 32MB | 100px | JPG, PNG, WebP |
| GenVideo/Vidu | 50MB | 128px | JPG, PNG |
| Runway | 500MB | 320px | JPG, PNG + MP4, MOV |
| Veo ITV | 30MB | 300px | JPG, PNG, WebP |

## 🎯 API Features Summary

| API | Type | Key Features |
| ----- | ------ | -------------- |
| Kling 2.5 | I2V | Streaming downloads, v2.5-turbo model, negative prompts |
| Kling Effects | I2V | 100+ preset effects, custom effects |
| Kling Endframe | I2V | A→B transitions, pairing modes |
| Kling TTV | T2V | Text-to-video, sound generation, multiple models |
| Kling Motion | I+V | Image + video motion control, cross-matching |
| Pixverse | I2V | v6 model, custom effect IDs, multi-clip |
| Pixverse TTV | T2V | Text-to-video, v6 model, effects, multi-clip |
| GenVideo | I2I | Gashapon style, GPT/Gemini models |
| Nano Banana | I2I | Multi-image (up to 14), random source selection, deterministic random |
| Vidu Effects | I2V | Category organization, viduq2-pro |
| Vidu Reference | I2V | Up to 6 references, movement control |
| Runway | V2V | one_to_one/all_combinations pairing |
| Wan 2.2 | I+V | Auto-cropping, video×image cross-match |
| DreamActor | I+V | Image + video face reenactment, base64 encoding |
| Veo | T2V | Veo 2.0–3.1, audio generation, compression quality |
| Veo ITV | I2V | Image-to-video, multi-generation per image |

**All APIs use deterministic file sorting for reproducible results.**

## 📝 Output Naming

| API | Output Pattern |
| ----- | ---------------- |
| Kling | `{filename}_generated.mp4` |
| Kling Effects | `{filename}_{effect}_effect.mp4` |
| Kling Endframe | `{filename}_generated_{n}.mp4` |
| Kling TTV/Veo | `{style}-{n}_generated.mp4` |
| Pixverse TTV | `{style}-{n}_generated.mp4` |
| Kling Motion | `{video}_{image}_motion.mp4` |
| Veo ITV | `{source_image}_{n}.mp4` |
| Pixverse/Vidu | `{filename}_{effect}_effect.mp4` |
| Runway | `{filename}_ref_{ref}_runway_generated.mp4` |
| Wan 2.2 | `{video}_{image}_{mode}.mp4` |
| Nano Banana | `{filename}_image_{n}.{ext}` |
| GenVideo | `{filename}_generated.{ext}` |

**Metadata:** `{filename}_metadata.json` (includes success status, processing time, API params, attempt count)

## 🔧 Architecture

The framework uses an auto-discovery handler system:

- **`HandlerRegistry`** - Auto-discovers and registers API handlers
- **`BaseAPIHandler`** - Common processing logic (validation, metadata, retries)
- **`UnifiedAPIProcessor`** - Image conversion, video extraction, optimal ratio matching
  - **Sleep prevention** – On macOS, uses native `caffeinate -di` subprocess tracked by PID. On other platforms, uses `wakepy` library. Cleanup is guaranteed via `finally`, `atexit`, and `SIGINT`/`SIGTERM` signal handlers so orphaned processes cannot block system sleep. Multiple concurrent script instances are safe.
- **`UnifiedReportGenerator`** - PowerPoint generation with parallel metadata loading

**16 API handlers:** Kling, KlingEffects, KlingEndframe, KlingTTV, KlingMotion, Pixverse, PixverseTTV, Genvideo, NanoBanana, ViduEffects, ViduReference, Runway, Wan, DreamActor, Veo, VeoItv

---

> **Tip:** Download videos with: `yt-dlp -f "bv*[vcodec~='^(h264|avc)']+ba[acodec~='^(mp?4a|aac)']" "URL" -o "%(title)s.%(ext)s"`
