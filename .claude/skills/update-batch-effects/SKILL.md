---
name: update-batch-effects
description: Replace the `tasks:` list in batch effects config YAMLs (Kling Effects, Vidu Effects, Pixverse) with a new list of effect entries supplied by the user. Use when the user provides a list of effect names (optionally with numeric IDs for Pixverse) and asks to replace, swap, or update the effects for one of these APIs.
---

# update-batch-effects

Replace the `tasks:` block in one of three batch effects config files with a new list of effect entries. Each API has its own per-task shape and formatting — match the target file exactly.

## Supported configs

| API | File | Per-task shape |
|---|---|---|
| Kling Effects | `Scripts/config/batch_kling_effects_config.yaml` | `effect:` (empty) + `custom_effect: 'name'`, no blank line between entries |
| Vidu Effects | `Scripts/config/batch_vidu_effects_config.yaml` | `category: People` + `custom_effect_name: name`, blank line between entries |
| Pixverse | `Scripts/config/batch_pixverse_config.yaml` | `effect: Name` + `prompt: ''` + `custom_effect_id: 'id'` + `negative_prompt: ''`, blank line between entries |

## Step 1 — Identify the target config

In order of precedence:
1. **IDE selection** — if the user has a selection inside one of the three files, that is the target.
2. **Keyword in the user message** — "kling" / "kling effects" → Kling Effects file; "vidu" → Vidu Effects file; "pixverse" → Pixverse file.
3. **Prior turn context** — if the user just edited one of these files and continues with a follow-up list, assume the same file.
4. Otherwise, ask the user which API to update via `AskUserQuestion`.

## Step 2 — Parse the user's effect list

The user supplies a newline-separated list. Each line is one of:
- `effect_name` — name only. Used for Kling and Vidu.
- `effect_name<TAB>id` or `effect_name<whitespace>id` (id is all digits) — name + numeric ID. Used for Pixverse.

For Pixverse, every entry must have an ID. If any entry is missing one, stop and ask the user.

For Vidu, default `category` to `People` unless the user specifies otherwise.

## Step 3 — Format the new `tasks:` block

Match the target file's exact indentation and spacing:

### Kling Effects
```yaml
tasks:
  - effect:
    custom_effect: 'NAME_1'
  - effect:
    custom_effect: 'NAME_2'
```
- 2-space indent for list items
- `custom_effect` value quoted with single quotes
- No blank lines between entries

### Vidu Effects
```yaml
tasks:
- category: People
  custom_effect_name: NAME_1

- category: People
  custom_effect_name: NAME_2
```
- Top-level array (no leading indent on `-`)
- `custom_effect_name` value unquoted
- One blank line between entries

### Pixverse
```yaml
tasks:
  - effect: NAME_1
    prompt: ''
    custom_effect_id: 'ID_1'
    negative_prompt: ''

  - effect: NAME_2
    prompt: ''
    custom_effect_id: 'ID_2'
    negative_prompt: ''
```
- 2-space indent for list items
- `effect` value unquoted; `custom_effect_id` quoted with single quotes
- `prompt` and `negative_prompt` always empty strings
- One blank line between entries

## Step 4 — Apply the edit

1. `Read` the target config.
2. Use `Edit` with:
   - `old_string` = the existing `tasks:` block, from the line `tasks:` through the last task entry (do not include the trailing blank line(s) that separate `tasks:` from the next top-level key)
   - `new_string` = the newly formatted block built above
3. Confirm with a one-line summary that includes a clickable file:line link to the new tasks region (e.g. `[batch_pixverse_config.yaml:22-41](Scripts/config/batch_pixverse_config.yaml#L22-L41)`).

## What NOT to change

- Do not touch `effect_options`, `comments`, `base_folder`, `design_link`, `source_video_link`, `schedule`, `output`, `model_version`, `default_settings`, or any field outside the `tasks:` block.
- Do not reorder or rename top-level keys.
- Do not add commentary to the YAML.
- Do not auto-update `base_folder` to reflect today's date or the new effect count — leave it untouched unless the user asks.
