# Batch config YAML conventions

These `batch_*.yaml` files drive the generation pipelines. When generating or
editing them, follow the comment-placement rule below.

## Comments go in a `comments:` section, never inline

Documentation for fields (option lists, "openai only", step headers, defaults,
etc.) belongs in a single top-level `comments:` mapping at the **end of the
file** — keyed by the field name it explains. Example:

```yaml
tasks:
  - style_name: ...
    image_service: openai_image
    image_model: gpt-image-2
    image_quality: auto

comments:
  image_service: |
    Per-task selection of which image API to use.
    Options: nano_banana | openai_image
  image_quality: |
    openai_image only. Options: auto | low | medium | high.
```

Do **not** put inline `#` comments next to task fields, e.g. avoid:

```yaml
    image_service: openai_image
    # nano_banana | openai_image          <-- WRONG: inline comment on a task field
```

### Why

Tasks are cloned to generate new entries (the `update-batch-prompts` skill and
the GUI both treat the last task as the template). Inline comments get copied
into every generated task, producing noise. Keeping all documentation in the
single trailing `comments:` section keeps task entries clean and the docs in one
place.

### Applying the rule

- New task entries: emit only the data fields — no `#` comments.
- If a field needs explanation, add or update its entry under the trailing
  `comments:` block instead of annotating the task.
- A short `# Comments and documentation` header line directly above the
  `comments:` key is fine; per-field inline comments inside `tasks:` are not.

## Examples go in `comments:`, not as commented-out YAML

Do **not** park commented-out example tasks (`# - folder: ...`) between the
`tasks:` list and the `comments:` block. Put illustrative variants under an
`example:` key inside `comments:` as a block scalar:

```yaml
comments:
  example: |
    nano_banana variant (alternative to the task above):
      - style_name: ...
        image_service: nano_banana
        image_model: gemini-3.1-flash-image-preview
        ...
```

## Keep a live task as the template

Every config should retain at least one real, runnable task — that live task is
the clone-template the `update-batch-prompts` skill and the GUI copy to build new
entries. Don't rely on a commented-out example task to document the shape; if a
live task already exists, a redundant commented duplicate should be removed
(its shape is documented by the live task plus the `comments:` section).
