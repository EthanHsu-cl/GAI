---
name: update-batch-prompts
description: Add or replace prompt-driven tasks in a custom-prompt image-to-video batch config YAML (Kling I2V, I2I2V, Veo ITV, Seedance I2V, Kling Endframe, Vidu I2V). Use when the user wants to add the per-task parameters for one of these APIs — typically pasting prompt / negative-prompt text blocks copied from a Google Slides deck. Asks which API, how many tasks, and whether to replace or append, then collects the content for each task's arguments.
---

# update-batch-prompts

Build new `tasks:` entries for one of the **custom-prompt image-to-video** configs and either replace the existing list or append to it. These APIs each have a different per-task field shape, but inside any one file every task clones the same shape — so the structure, defaults, quoting, and folder convention are learned from the existing tasks in the target file, and only the per-task *content* (prompt text, style name) is asked from the user.

This skill is for configs whose tasks carry a free-text `prompt` / `*_prompt`. For name-only effect lists with no prompt (Kling Effects, Vidu Effects, Pixverse), use **update-batch-effects** instead.

## Supported APIs

| API | Config file | Per-task content fields (ask the user) | Carry-over default fields (clone from existing task) | Per-style folder shape |
|---|---|---|---|---|
| Kling I2V | `Scripts/config/batch_kling_config.yaml` | `prompt`, `negative_prompt`, `mode` | `design_link`, `source_video_link`, `reference_folder`, `use_comparison_template` | flat: `Media Files/Kling 3.0/<MMDD> <name>` |
| I2I2V | `Scripts/config/batch_i2i2v_config.yaml` | `style_name`, `image_service`, `image_model`, `image_prompt`, `video_prompt`, `video_negative_prompt` | `image_quality`, `image_resolution`, `image_aspect_ratio`, `video_model`, `video_mode`, `video_duration`, `video_ratio` | grouped + dated: `Media Files/I2I2V/<MMDD> <N> Styles/<MMDD> <style_name>` |
| Veo ITV | `Scripts/config/batch_veo_itv_config.yaml` | `style_name`, `prompt`, `negative_prompt` | `model_id`, `duration_seconds`, `aspect_ratio`, `resolution`, `compression_quality`, `seed`, `enhance_prompt`, `generate_audio`, `person_generation` | grouped: `Media Files/Veo_ITV/<MMDD> <N> Styles/<style_name>` |
| Seedance I2V | `Scripts/config/batch_seedance_i2v_config.yaml` | `style_name`, `prompt` | `aspect_ratio` | grouped: `Media Files/Seedance I2V/<MMDD> <N> Styles/<style_name>` |
| Kling Endframe | `Scripts/config/batch_kling_endframe_config.yaml` | `prompt`, `negative_prompt`, `mode` | `duration`, `cfg`, `design_link`, `source_video_link`, `reference_folder`, `use_comparison_template` | grouped: `Media Files/Kling Endframe/<MMDD> <N> Style(s)/<name>` |
| Vidu I2V | `Scripts/config/batch_vidu_i2v_config.yaml` | `custom_effect_name`, `prompt`, `duration` | — | no folder field |

The table is a guide. **Always treat the last existing task in the target file as the source of truth** for exact field order, quoting style, block-scalar (`|`) usage, indentation, and default values. If the file's shape disagrees with the table, follow the file.

## Step 1 — Identify the target config (API)

Resolve in this order, then call `AskUserQuestion` only if still ambiguous:
1. **IDE selection / open file** — if the user has a selection in, or just opened, one of the supported config files, that is the target.
2. **Keyword in the user message** — "i2i2v", "kling endframe", "kling", "veo"/"veo itv", "seedance", "vidu" → the matching file.
3. **Prior turn context** — if the user was just editing one of these files, assume the same one.
4. Otherwise ask via `AskUserQuestion` (header `API`) listing the supported APIs above. Disambiguate "kling" between Kling I2V and Kling Endframe if unclear.

## Step 2 — Ask the premises (always, up front)

Ask these before collecting any content. Combine into a single `AskUserQuestion` call with multiple questions when the API is already known:

1. **Count** — header `Count`, question "How many tasks/effects to add?" Offer a few common counts (e.g. 1, 2, 3, 6) plus the user can type their own.
2. **Mode** — header `Mode`, question "Replace the existing tasks, or append to them?" Options: `Replace` (clears the current `tasks:` list and writes only the new ones) and `Append` (keeps existing tasks and adds the new ones after them).

If the user already stated count and/or mode in their message, skip those questions.

## Step 3 — Learn the per-task template from the file

`Read` the target config. From the **last existing task** capture:
- The exact field set and their order.
- Per-field formatting: which values are quoted (single vs double), which use block scalars (`| ` literal blocks), indentation width, and whether entries are separated by a blank line.
- The carry-over default values (everything in the "default fields" column).
- The **folder convention**: the `Media Files/...` prefix, whether there is a `<MMDD> <N> Styles` group segment, and whether the per-style leaf is date-prefixed (I2I2V leaves are `<MMDD> <name>`; Veo/Seedance leaves are just `<name>`).

If the file has zero existing tasks, fall back to the table above and to the commented example block in the file.

## Step 4 — Collect the content for each new task

For the content fields (the ones the user pastes from the Slides text blocks), ask in **plain text** — not `AskUserQuestion` — because prompt text is long. In one message, lay out exactly what you need per task, numbered, so the user can paste blocks in order. For example, for I2I2V:

```
Paste the following for each of the N tasks (I'll use the existing defaults for models/ratios/duration unless you say otherwise):

Task 1
  • style_name:
  • image_service (nano_banana | openai_image):
  • image_prompt:
  • video_prompt:
  • video_negative_prompt:
```

Guidance:
- Only ask for the **content fields** for that API (see the table). Reuse the carry-over defaults silently from Step 3; mention you're doing so, and let the user override any default if they want.
- If the user already pasted the blocks in their message, parse them directly instead of re-asking.
- For I2I2V, `image_model` follows `image_service`: default `gemini-3.1-flash-image-preview` for `nano_banana`, `gpt-image-2` for `openai_image`, unless the existing default task or the user says otherwise.
- A field the user leaves blank → use the file's default empty form (e.g. `negative_prompt: ''`).

## Step 5 — Derive folder paths

For APIs with a `folder` field, build each task's folder from the convention learned in Step 3:
- **Date `<MMDD>`** — pull from the existing group/folder prefix of the target file (per the project's date-source rule: use the folder-name date prefix; fall back to the current date only when there is no prefix). On a full **Replace** where the user is clearly starting a new batch for today, current date is acceptable — confirm if unsure.
- **Group count `<N>`** — the total number of tasks in the final list (existing + new, for Append; just the new ones, for Replace). Apply the same `<MMDD> <N> Style(s)` group segment to **every** task in the written block, since that segment is embedded in each folder path.
  - **Grammar:** `1 Style` (singular) when N = 1; `2 Styles` (plural) when N ≥ 2. Match the file's existing noun (`Styles` for I2I2V/Veo/Seedance, `Style(s)` for Kling Endframe). Never write `1 Styles`.
- **Per-style leaf** — match the file's leaf convention (date-prefixed for I2I2V, plain `style_name` for Veo/Seedance, the `name` for Kling/Endframe).

## Step 6 — Build and apply the edit

1. Format each new task entry by cloning the template's exact shape (field order, quoting, block scalars, blank-line separators).
2. Use `Edit`:
   - **Replace** — `old_string` = the whole existing `tasks:` block (from `tasks:` through the last task entry, not including trailing blank lines before the next top-level key or comment); `new_string` = `tasks:` + the newly formatted entries.
   - **Append** — `old_string` = the last existing task entry; `new_string` = that same entry + the new entries after it (with the file's separator style).
   - For grouped-folder APIs on Append where `<N>` changed, the group segment in the **existing** task folders also changes — rewrite the full `tasks:` block (treat it like Replace but keep the existing tasks' content) so every folder reflects the new count.
3. If the API has a separate `base_folder`/group key outside the tasks (none of the current files do, but check), update it too.
4. Confirm with a one-line summary including a clickable `file:line` link to the new tasks region, e.g. `[batch_i2i2v_config.yaml:28-60](Scripts/config/batch_i2i2v_config.yaml#L28-L60)`.

## What NOT to change

- Don't touch `comments`, `template_path`, `output`, `testbed`, `schedule`, `root_design_link`, `root_source_video_link`, `root_folder`, `model_version`, or any top-level key outside the `tasks:` list (and the group-count segment inside folder paths).
- Don't reorder or rename fields; clone the existing shape exactly.
- Don't add YAML commentary or leave the commented example block altered.
- Don't change the `Media Files/...` path prefix — only the `<MMDD> <N> Style(s)` segment and the per-style leaf.
