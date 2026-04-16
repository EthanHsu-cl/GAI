# Add New API Handler

You are adding a new API platform to the GAI automation suite. Follow every step below sequentially. Do not skip steps.

## Required Input

The user must provide:
1. **API documentation** — The Gradio `client.predict()` call signature, parameter definitions, and return tuple structure.
2. **API type** — One of: `image_to_video`, `text_to_video`, `effects`, `endframe`, `motion`, or `reference`.
3. **Default parameter values** — The defaults for all API parameters (aspect ratio, duration, resolution, model, seed, etc.).

## Step-by-Step Process

### Step 1: Determine the API identifier

Derive a snake_case API name from the platform name (e.g., `seedance_ttv`, `kling_effects`). This identifier is used everywhere: handler filename, config filename, api_definitions key, runall mappings, and report generator references.

### Step 2: Create the Handler

Create `Scripts/handlers/{api_name}_handler.py`.

**Rules:**
- Import `BaseAPIHandler` from `.base_handler`.
- Class name: Convert snake_case to CamelCase + `Handler` (e.g., `SeedanceTTVHandler`). The `HandlerRegistry` auto-discovers handlers by scanning `*_handler.py` files — no manual registration needed.
- **For text-to-video APIs:** Use `_validate_text_to_video_structure()` in `validate_structure()`.
- **For image/video input APIs:** Use `_validate_task_folder_structure()` or `_validate_base_folder_structure()` in `validate_structure()`.

**Required methods to implement:**

1. `validate_structure(self, tasks, config)` — Call the appropriate base validation method.

2. `_make_api_call(self, file_path, task_config, attempt)` — Map config fields to the Gradio `client.predict()` call. Use `self.config.get("default_settings", {})` for global defaults and `task_config.get()` for per-task overrides. Always include `api_name=self.api_defs["api_name"]` as the last parameter.

3. `_handle_result(self, result, file_path, task_config, output_folder, metadata_folder, base_name, file_name, start_time, attempt)` — Parse the API response tuple, save video files (try URL download first via `self.processor.download_file()`, then local copy via `shutil.copy2()`), and save metadata via `self.processor.save_metadata()`.

4. `process_task(self, task, task_num, total_tasks)` — Orchestrate task execution with generation_count support, skip-if-already-processed logic, and rate limiting.

5. `process(self, file_path, task_config, output_folder, metadata_folder, attempt, max_retries)` — Process a single generation by calling `_make_api_call` then `_handle_result`.

**Reference handlers by API type:**
- Text-to-video: `pixverse_ttv_handler.py`, `kling_ttv_handler.py`
- Image-to-video: `kling_handler.py`, `veo_itv_handler.py`
- Effects: `kling_effects_handler.py`, `pixverse_handler.py`

### Step 3: Create the Config File

Create `Scripts/config/batch_{api_name}_config.yaml`.

**Structure:**
```yaml
# {Platform} Configuration
template_path: templates/I2V templates.pptx
output_directory: /Users/ethanhsu/Desktop/EthanHsu-cl/GAI/Report
testbed: {endpoint_url}
design_link: ""
source_video_link: ""
generation_count: 1

output_folder: Media Files/{Platform Name}/{MMDD} {N} Styles

default_settings:
  # All API default parameters here

tasks:
  - style_name: Task_Name
    prompt: |
      Prompt text here
    # Per-task overrides here
```

**Task content:** Copy the 21 standard benchmark tasks from `batch_pixverse_ttv_config.yaml` or `batch_veo_config.yaml`, adapting fields to match the new API's parameter names. Preserve the same `style_name` values and `prompt` text. Keep aspect ratios consistent with veo and pixverse_ttv configs.

### Step 4: Add API Definitions

Add an entry to `Scripts/core/api_definitions.json` under the API name key.

**Required fields:**
```json
{
    "endpoint": "{testbed_url}",
    "api_name": "/{gradio_api_route}",
    "file_types": [],
    "validation": {},
    "folders": {
        "output": "Generated_Video",
        "metadata": "Metadata"
    },
    "rate_limit": 3,
    "task_delay": 10,
    "max_retries": 3,
    "special_handling": "text_to_video",
    "config_structure": "task_list",
    "report": {
        "enabled": true,
        "template_path": "templates/I2V templates.pptx",
        "output_directory": "/Users/ethanhsu/Desktop/EthanHsu-cl/GAI/Report",
        "use_comparison": false
    },
    "task_fields": ["prompt", ...],
    "api_params": { ... },
    "model_options": [...],
    "aspect_ratio_options": [...]
}
```

- For image/video input APIs, populate `file_types` (e.g., `[".jpg", ".jpeg", ".png"]`) and `validation` (max_size_mb, min_dimension, aspect_ratio range).
- For text-to-video APIs, set `"special_handling": "text_to_video"` and `"config_structure": "task_list"`.
- For effects/base-folder APIs, set `"config_structure": "base_folder"`.
- Validate the JSON after editing: `python3 -c "import json; json.load(open('Scripts/core/api_definitions.json')); print('JSON valid')"`.

### Step 5: Register in runall.py

Edit `Scripts/core/runall.py` — add entries in **all four** locations:

1. **`API_MAPPING`** dict — Add both the canonical name and a shorthand alias:
   ```python
   '{api_name}': '{api_name}',
   '{shorthand}': '{api_name}',
   ```

2. **`CONFIG_MAPPING`** dict:
   ```python
   '{api_name}': 'config/batch_{api_name}_config.yaml',
   ```

3. **Help text** — Add a `print()` line in the PLATFORMS section.

4. **Examples** — Add a `print()` line in the EXAMPLES section.

### Step 6: Add Report Support

Edit `Scripts/core/unified_report_generator.py` — add the API name to **all** of the following locations:

1. **Display name** — In the `DISPLAY_NAMES`-style dict in `__init__()`, add: `'{api_name}': '{Display Name}'`

2. **Slide config** — In `get_slide_config()`, add a config block. Use the same format as the closest matching API type:
   - Text-to-video: `media_types: ['prompt', 'generated']` with 2-media layout
   - Image-to-video: `media_types: ['source', 'generated']` with 2-media layout
   - Effects: `media_types: ['source', 'generated']` with 2-media layout
   
   Set `metadata_fields` to match the fields saved in `_handle_result`.

3. **Video detection** — Add to the `is_video` check list (search for `'pixverse_ttv'` in the `is_video` line).

4. **`process_batch()`** — Add to the appropriate routing condition:
   - Text-to-video: the `["veo", "kling_ttv", "pixverse_ttv", ...]` list
   - Base folder: the `["vidu_effects", "vidu_reference", ...]` list
   - Otherwise falls through to task folder structure

5. **`process_text_to_video_batch()`** (text-to-video only) — Add to the folder resolution condition:
   - If config uses `output_folder` at root level: add to `['kling_ttv', 'pixverse_ttv', ...]`
   - If config uses per-task `output_folder`: it falls through to the `else` (veo-style)

6. **`run()` method** — Add to the appropriate routing condition (same list as `process_batch`).

7. **Filename generation** — Search for all lists containing `'pixverse_ttv'` in `_get_filename_parts()` and `_get_grouped_filename()`. Add the new API name to each list where style count display is appropriate.

8. **`create_report_generator()`** — Add to the `supported_apis` list.

9. **`main()` argparse** — Add to the `choices` list.

### Step 7: Update README

Add a configuration section to `readme.md` following the pattern of existing TTV/effects sections. Include:
- The config filename
- A YAML example showing default_settings and one sample task
- A one-line summary of defaults

### Step 8: Validate

Run these checks:
1. `python3 -c "import json; json.load(open('Scripts/core/api_definitions.json')); print('JSON valid')"`
2. From `Scripts/` directory with conda myenv: `python -c "from core.unified_report_generator import create_report_generator; g = create_report_generator('{api_name}'); sc = g.get_slide_config(); print('Media types:', sc.get('media_types')); print('OK')"`
