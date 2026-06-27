# AI Context Index

This file is for AI coding agents. Keep it short. Do not paste full project knowledge here.

## First step for any task

You can generate this file with:

```bash
ctx project init-index --project <project-slug> --area <area>
```

Run:

```bash
ctx prepare --project <project-slug> --task "<copy the user's task>"
```

If this task clearly belongs to one area, route it directly:

```bash
ctx prepare --project <project-slug> --area <area> \
  --entrypoint-path AI_CONTEXT_INDEX.md \
  --entrypoint-rule "<matched rule>" \
  --task "<copy the user's task>"
```

Use the returned `trace_id` for follow-up reads.

## Read a specific document only when needed

Run:

```bash
ctx read <doc-id> --trace <trace-id> --reason "<why this document is needed>"
```

## Rules

- Do not read large docs manually before running `ctx prepare`.
- Prefer the documents returned by `ctx prepare`.
- If needed context is missing, mention the missing document in the final response.
