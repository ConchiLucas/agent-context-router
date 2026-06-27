# AI Context Index

This file is for AI coding agents. Keep it short. Do not paste full project knowledge here.

## First step for any task

Run:

```bash
ctx prepare --project <project-slug> --task "<copy the user's task>"
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

