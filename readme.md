# Automated Processing & Reporting Automation Suite

A Python automation framework for batch processing images/videos through 12+ AI APIs with automated PowerPoint report generation.

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

## �️ Desktop GUI Usage

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
```
key = value
key: value
```

**Examples:**
```
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
   ```
   prompt = Generate a magical forest scene
   ```
5. Click **"▶ Run"**

#### Example 3: Veo ITV (Image-to-Video)

1. Select **Platform**: "veoitv" (Veo ITV)
2. Select **Action**: "Process Only" (generate videos without report)
3. Click **Browse...** and select your custom YAML config
4. Click **"▶ Run"**
5. Videos will be saved to `Generated_Video/` in each style folder

### **Important Notes**

- **Runtime overrides are temporary** — they only apply to the current run and do NOT modify your YAML config files
- **FFmpeg required** — video processing requires FFmpeg to be installed on your system
- **Network required** — the app connects to API servers defined in your config files
- **Reports saved to** `Report/` folder with date-prefixed filenames

## �📋 Platform Commands

| Short Name | Full Name | Description |
| :-- | :-- | :-- |
| `kling` | Kling 2.1 | Image-to-video generation with v2.1 model |
| `klingfx` | Kling Effects | Apply premade video effects to images |
| `klingend` | Kling Endframe | Start/end frame video generation (A→B transitions) |
| `klingttv` | Kling TTV | Text-to-video generation (no input images) |
| `pixverse` | Pixverse v4.5 | Effect-based video generation with custom effects |
| `genvideo` | GenVideo | Image-to-image transformation (Gashapon style) |
| `nano` | Nano Banana/Google Flash | Multi-image generation with AI models |
| `vidu` | Vidu Effects | Effect-based video generation with categories |
| `viduref` | Vidu Reference | Multi-reference guided video generation |
| `runway` | Runway Gen4 | Video processing with face swap and effects |
| `wan` | Wan 2.2 | Image + video cross-matching with motion animation |
| `veo` | Google Veo | Text-to-video generation with AI models |
| `veoitv` | Google Veo ITV | Image-to-video generation with AI models |
| `all` | All Platforms | Process all APIs sequentially or in parallel |

## Video Download Command Example

```bash
# File download command example:
yt-dlp -f "bv*[vcodec~='^(h264|avc)']+ba[acodec~='^(mp?4a|aac)']" "link" --cookies-from-browser chrome -o "%(title)s.%(ext)s"
```

## 📁 Project Structure

```bash
GAI/                                    # Project root
└── Scripts/                           # Main scripts directory
    ├── config/                        # Configuration files (YAML format)
    │   ├── batch_kling_config.yaml        # Kling I2V configuration
    │   ├── batch_kling_effects_config.yaml # Kling Effects configuration
    │   ├── batch_kling_endframe_config.yaml # Kling Endframe configuration
    │   ├── batch_kling_ttv_config.yaml    # Kling TTV configuration
    │   ├── batch_pixverse_config.yaml     # Pixverse configuration
    │   ├── batch_genvideo_config.yaml     # GenVideo configuration
    │   ├── batch_nano_banana_config.yaml  # Nano Banana configuration
    │   ├── batch_runway_config.yaml       # Runway configuration
    │   ├── batch_vidu_effects_config.yaml # Vidu Effects configuration
    │   ├── batch_vidu_reference_config.yaml # Vidu Reference configuration
    │   ├── batch_wan_config.yaml          # Wan 2.2 configuration
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
├── Reference/           # Runway, Vidu Reference: reference images
├── Generated_Video/     # Auto-created outputs
└── Metadata/            # Auto-created metadata
```

**API-specific input folders:**

- Most APIs: `Source/`
- Wan 2.2: `Source Image/` + `Source Video/` (cross-matched)
- Nano Banana multi-image: `Source/` + `Additional/`
- Runway/Vidu Reference: `Source/` + `Reference/`

## ⚙️ Configuration Files

All configuration files are located in the `Scripts/config/` directory and follow API-specific naming conventions.

**Common Configuration Fields** (applicable to most APIs):

- **`design_link`**: URL to design reference materials (optional)
- **`source_video_link`**: URL to source video reference (optional)
- **`reference_folder`**: Path to reference comparison folder (optional)
- **`use_comparison_template`**: Enable comparison template for reports (boolean)

### **Kling Configuration** (`config/batch_kling_config.yaml`)

```yaml
testbed: http://192.168.31.161:8000/kling/
model_version: v2.1

tasks:
  - folder: /path/to/TaskName1
    prompt: "Transform this portrait into a cinematic video"
    negative_prompt: "blurry, low quality"
```

### **Kling Effects Configuration** (`config/batch_kling_effects_config.yaml`)

Applies premade video effects to images. Supports both preset effects and custom effect names.

```yaml
base_folder: ../Media Files/Kling Effects/1127 Test
testbed: http://192.168.31.161:8000/kling/

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
testbed: http://192.168.31.161:8000/kling/
model_version: v2.1
generation_count: 1  # Global default, can override per task

output:
  directory: /Users/ethanhsu/Desktop/EthanHsu-cl/GAI/Report
  group_tasks_by: 3  # Combine N tasks into one report (0 = individual)

tasks:
  - mode: pro
    folder: ../Media Files/Kling Endframe/1030 3 Styles/Anime Awakening
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
testbed: http://192.168.31.161:8000/kling/
model: "v2.5-turbo"
output_folder: ../Media Files/Kling TTV/Test

tasks:
  - style_name: "Dog Running"
    prompt: "A dog is happily running toward its owner"
    mode: "std"
    duration: 5
    ratio: "16:9"
    cfg: 0.5
```

**Options:** Model (`v1.6`/`v2.1`/`v2.5-turbo`), Mode (`std`/`pro`), Ratio (`16:9`/`9:16`/`1:1`)

### **Nano Banana Configuration** (`config/batch_nano_banana_config.yaml`)

```yaml
testbed: http://192.168.31.161:8000/image_generation/
tasks:
  - folder: /path/to/TaskName1
    prompt: "Generate variations"
    use_multi_image: true
    multi_image_config:
      mode: sequential  # or 'random_pairing'
      folders: ["/path/to/Additional/"]
```

**Model limits:** `gemini-2.5-flash-image` (max 3 images), `gemini-3-pro-image-preview` (max 14 images)

### **Vidu Effects Configuration** (`config/batch_vidu_effects_config.yaml`)

```yaml
base_folder: ../Media Files/Vidu/1027 Product
testbed: http://192.168.31.161:8000/video_effect/
model_version: viduq2-pro

tasks:
  - category: Product
    effect: Auto Spin
```

### **Vidu Reference Configuration** (`config/batch_vidu_reference_config.yaml`)

```yaml
base_folder: ../Media Files/Vidu_Ref/1201 1 Style
testbed: http://192.168.31.161:8000/video_effect/
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
base_folder: ../Media Files/Pixverse
testbed: http://192.168.31.161:8000/pixverse_image/

tasks:
  - effect: Dynamic Motion
    prompt: "Add dynamic motion"
    custom_effect_id: ""
```

**Defaults:** Model v4.5, Duration 5s, Quality 720p

### **GenVideo Configuration** (`config/batch_genvideo_config.yaml`)

```yaml
testbed: http://192.168.31.161:8000/genvideo/

tasks:
  - folder: /path/to/TaskName1
    img_prompt: "Generate a gashapon capsule"
    model: gpt-image-1
    quality: low
```

**Models:** `gpt-image-1`, `gemini-2.5-flash-image-preview` | **Quality:** `low`/`medium`/`high`

### **Runway Configuration** (`config/batch_runway_config.yaml`)

```yaml
testbed: http://192.168.31.161:8000/runway/
model: gen4_aleph

tasks:
  - folder: /path/to/TaskName1
    prompt: "Face swap effect"
    pairing_strategy: one_to_one  # or 'all_combinations'
    requires_reference: true
```

**Pairing:** `one_to_one` (1:1 mapping) or `all_combinations` (N×M outputs)
**Ratios:** `1280:720`, `720:1280`, `1104:832`, `960:960`, `832:1104`, `1584:672`

### **Wan 2.2 Configuration** (`config/batch_wan_config.yaml`)

```yaml
testbed: http://210.244.31.18:7008/

tasks:
  - folder: ../Media Files/Wan 2.2/Test
    prompt: "The person is dancing"
    animation_mode: move  # or 'mix'
```

**Cross-matching:** All videos × all images (e.g., 5 videos × 4 images = 20 outputs)
**Requires:** `Source Image/` and `Source Video/` folders

### **Veo Configuration** (`config/batch_veo_config.yaml`)

Text-to-video generation (no input images required).

```yaml
testbed: http://192.168.31.161:8000/google_veo/

tasks:
  - prompt: "A serene landscape with mountains at sunset"
    model_id: veo-3.1-generate-001
    duration_seconds: 8
    aspect_ratio: "16:9"
    resolution: 1080p
    output_folder: ../Media Files/Veo/Test1/Generated_Video
```

**Models:** `veo-2.0-generate-001`, `veo-3.0-generate-001`, `veo-3.0-fast-generate-001`, `veo-3.1-generate-preview`
**Options:** Ratio (`16:9`/`9:16`), Resolution (`720p`/`1080p`), `enhance_prompt`, `generate_audio`

### **Veo ITV Configuration** (`config/batch_veo_itv_config.yaml`)

Image-to-video generation with source images.

```yaml
root_folder: ../Media Files/Veo_ITV
generation_count: 2  # Videos per source image

tasks:
  - style_name: Style 11_Statue Selfie
    folder: ../Media Files/Veo_ITV/Style 11_Statue Selfie
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

## 📈 File Requirements

| API | Max Size | Min Dimensions | Formats |
|-----|----------|----------------|---------|
| Kling | 10MB | 300px | JPG, PNG, WebP |
| Pixverse | 20MB | 128px | JPG, PNG |
| Nano Banana | 32MB | 100px | JPG, PNG, WebP |
| GenVideo/Vidu | 50MB | 128px | JPG, PNG |
| Runway | 500MB | 320px | JPG, PNG + MP4, MOV |
| Veo ITV | 30MB | 300px | JPG, PNG, WebP |

## 🎯 API Features Summary

| API | Type | Key Features |
|-----|------|--------------|
| Kling 2.1 | I2V | Streaming downloads, v2.1 model, negative prompts |
| Kling Effects | I2V | 100+ preset effects, custom effects |
| Kling Endframe | I2V | A→B transitions, pairing modes |
| Kling TTV | T2V | Text-to-video, multiple models |
| Pixverse | I2V | v4.5 model, custom effect IDs |
| GenVideo | I2I | Gashapon style, GPT/Gemini models |
| Nano Banana | I2I | Multi-image (up to 14), sequential/random pairing |
| Vidu Effects | I2V | Category organization, viduq2-pro |
| Vidu Reference | I2V | Up to 6 references, movement control |
| Runway | V2V | one_to_one/all_combinations pairing |
| Wan 2.2 | I+V | Auto-cropping, video×image cross-match |
| Veo | T2V | Veo 2.0-3.1, audio generation |
| Veo ITV | I2V | Image-to-video, multi-generation per image |

**All APIs use deterministic file sorting for reproducible results.**

## 📝 Output Naming

| API | Output Pattern |
|-----|----------------|
| Kling | `{filename}_generated.mp4` |
| Kling Effects | `{filename}_{effect}_effect.mp4` |
| Kling Endframe | `{filename}_generated_{n}.mp4` |
| Kling TTV/Veo | `{style}-{n}_generated.mp4` |
| Veo ITV | `{source_image}_{n}.mp4` |
| Pixverse/Vidu | `{filename}_{effect}_effect.mp4` |
| Runway | `{filename}_ref_{ref}_runway_generated.mp4` |
| Wan 2.2 | `{video}_{image}_{mode}.mp4` |
| Nano Banana | `{filename}_image_{n}.{ext}` |
| GenVideo | `{filename}_generated.{ext}` |

**Metadata:** `{filename}_metadata.json` (includes success status, processing time, API params, attempt count)

## 🔧 Architecture

### **Handler System**

Auto-discovery handler system in `handlers/` directory:

- **`HandlerRegistry`** - Auto-discovers and registers handlers
- **`BaseAPIHandler`** - Common processing logic (validation, metadata, retries)
- **API Handlers** - Override `_make_api_call()` and `_handle_result()` only

**13 handlers:** `KlingHandler`, `KlingEffectsHandler`, `KlingEndframeHandler`, `KlingTTVHandler`, `PixverseHandler`, `GenvideoHandler`, `NanoBananaHandler`, `ViduEffectsHandler`, `ViduReferenceHandler`, `RunwayHandler`, `WanHandler`, `VeoHandler`, `VeoItvHandler`

### **Core Components**

```python
# Create processor/generator
from core.unified_api_processor import create_processor
from core.unified_report_generator import create_report_generator

processor = create_processor("nano_banana", "config/custom.yaml")
generator = create_report_generator("kling", "config/custom.yaml")
```

**UnifiedAPIProcessor:** Auto image conversion, video info extraction, endframe pairing, optimal ratio matching
**UnifiedReportGenerator:** MediaPair dataclass, parallel metadata loading, batch aspect ratio, format conversion
