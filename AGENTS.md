# AGENTS.md — Keyway Project Rules

## Push Policy (CRITICAL)

- **Never push to remote unless the user explicitly says "push" or "推送".**
- Local commits (`git commit`) are fine without permission.
- `git push` in any form requires explicit user instruction.
- This includes: `git push`, `git push --tags`, `gh repo create --push`, `gh release create`, and any CI-triggering tag operations.
- If you are unsure whether the user authorized a push, do not push — ask first.

## Local-Only Files

The following directories/files are local planning artifacts and must NOT be committed or pushed:

- `docs/` — internal design documents and implementation plans
- Any file matching `docs/*.md`

These are listed in `.gitignore`. If you need to create a new planning document, place it under `docs/` and it will be automatically excluded.

## General Rules

- Follow the existing code style and patterns in the repository.
- Run `python -m pytest -q` after any code change and ensure all tests pass.
- Never commit `.env`, `*.db`, `data/`, or any file containing real credentials.
- The package name on PyPI is `keyway-router`; the import name is `keyway`.
