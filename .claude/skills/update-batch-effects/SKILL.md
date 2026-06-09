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
3. Update `base_folder` (see Step 5).
4. Clear `source_video_link` — set it to an empty string (`source_video_link: ''`) via a separate `Edit` call. The link is stale after the tasks change; a new one will be produced once the script completes.
5. Confirm with a one-line summary that includes a clickable file:line link to the new tasks region (e.g. `[batch_pixverse_config.yaml:22-41](Scripts/config/batch_pixverse_config.yaml#L22-L41)`).

## Step 5 — Always update `base_folder`

Every time the `tasks:` block is replaced, also rewrite `base_folder` to reflect today's date and the new effect count. The last path segment follows this shape:

```
<MMDD> <count> <noun>
```

- `<MMDD>` — today's date in zero-padded month + day (e.g. `0522` for May 22). Use the `currentDate` from the context, not a date from the existing folder name.
- `<count>` — the number of entries in the newly written `tasks:` block.
- `<noun>` — match the API's existing convention:
  - Pixverse → `Style` (singular) / `Styles` (plural)
  - Kling Effects → `Effect` / `Effects`
  - Vidu Effects → `Effect` / `Effects`

**Grammar — singular vs. plural is required.** When `<count>` is 1, use the singular noun (`1 Effect`, `1 Style`). When `<count>` is 2 or more, use the plural (`2 Effects`, `7 Styles`). Never write `1 Effects` or `1 Styles`.

Keep the path prefix (everything before the last segment) exactly as it appears in the file — only the final segment changes. Edit the `base_folder:` line via a separate `Edit` call so the tasks-block edit stays self-contained.

Examples:
- Pixverse with 7 entries on 2026-05-22 → `Media Files/Pixverse/0522 7 Styles`
- Vidu with 1 entry on 2026-05-22 → `Media Files/Vidu/0522 1 Effect`
- Kling with 2 entries on 2026-05-22 → `Media Files/Kling Effects/0522 2 Effects`

## What NOT to change

- Do not touch `effect_options`, `comments`, `design_link`, `schedule`, `output`, `model_version`, `default_settings`, or any field outside the `tasks:` block, `base_folder`, and `source_video_link`.
- Do not reorder or rename top-level keys.
- Do not add commentary to the YAML.
- Do not change the path prefix of `base_folder` — only rewrite the final `<MMDD> <count> <noun>` segment.
