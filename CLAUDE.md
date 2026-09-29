# CLAUDE.md — Pramaan repo rules

Pramaan is a multi-vendor DVR/NVR forensic platform (SIH 2026, PS 26150). Read this file fully before any work. It overrides your defaults.

## Where things are

| Need | Read |
| --- | --- |
| What we are building and why | `docs/PRD.md` |
| Forensic core (scanner, parsers, recovery, logs) | `docs/01-FORENSIC-CORE.md` |
| Backend (API, jobs, storage, custody, reports, export) | `docs/02-BACKEND.md` |
| AI and timeline (four-clock, OCR, analytics, Claude) | `docs/03-AI-TIMELINE.md` |
| Frontend | `docs/04-FRONTEND.md` + `references/` |
| Infra, synthetic corpus, testing, validation | `docs/05-INFRA-QA.md` |
| Task prompts, waves, acceptance checks | `docs/PROMPTBOOK.md` |
| Overnight run state | `docs/PROGRESS.md` (orchestrator) and `docs/progress/<TASK_ID>.md` (one file per task, written by the agent doing it) |
| Brand, tokens, UI references | `references/BRAND.md`, `references/tokens.css`, `references/UI_REFERENCES.md` |

## Non-negotiable forensic rules

1. **Evidence is read-only.** Open images with read-only file modes only. Never write, truncate or `mmap` with write access to anything under an evidence path. Tests enforce this.
2. **Only `packages/core` opens evidence files** (`EvidenceReader`). Everything else asks core for bytes.
3. **Never re-encode original video.** Remux with stream copy. Transcoded viewing proxies are allowed only as clearly labelled derived files.
4. **Every derived artefact records provenance**: parent SHA-256, tool version, function name, parameters, UTC timestamp (`Provenance` model in core).
5. **Determinism.** Same input + same version = byte-identical outputs. No wall-clock values or random IDs inside hashed artefacts; derive IDs from content hashes; sort before serialising.
6. **The LLM never produces a finding.** Claude output is a labelled draft, gets only structured metadata, never frames, thumbnails or disk bytes.
7. **Honesty about synthetic data.** The corpus is synthetic, modelled on published layouts. Never write copy, docs or reports claiming compatibility with real vendor disks that has not been tested.

## Engineering rules

- Python 3.11+, managed with **uv** (workspace). Type hints everywhere; `ruff` + `mypy --strict` on `packages/`.
- Rust stable, Cargo workspace; the scanner is optional at runtime: a pure-Python fallback with the same interface must exist.
- Web: pnpm, React + TypeScript strict, Vite. Follow `docs/04-FRONTEND.md` exactly for stack and quality bar.
- One command gate: **`just check`** (lint, types, unit tests for all languages), run by the orchestrator at every wave gate. While working on a task, run your scoped gate (`just check-core`, `check-backend`, `check-ai`, `check-web`, `check-qa`). Never mark a task done while your scoped gate is red.
- Stay inside the paths your task owns (see ownership table in `docs/PROMPTBOOK.md`). If you must touch a shared contract (`packages/core/pramaan_core/models.py`, `packages/core/pramaan_core/schema.sql`, `apps/api/openapi.json`), make the smallest additive change and note it in your `docs/progress/<TASK_ID>.md` under "Contract changes".
- Prefer boring, well-known libraries. If a dependency fails to install, use the documented fallback in the relevant implementation doc and log it in your task's progress file.
- Do not `git commit` from a subagent; the orchestrator commits after reviewing each task.
- No secrets in git. `ANTHROPIC_API_KEY` comes from the environment only; tests use recorded fixtures.
- Small, focused commits: `feat(core): …`, `fix(web): …`, `test(qa): …`, `docs: …`.

## Git and GitHub

- Remote: `origin` = https://github.com/MuaazSM/pramaan (branch `main`). All pushes go there and nowhere else.
- Push only when `gh api user -q .login` prints exactly `MuaazSM`. If it prints anything else, or `gh` is not logged in, do not push; commit locally and record "push skipped: wrong/no gh account" in docs/PROGRESS.md.
- Commits are authored by the configured git user only. Never add `Co-Authored-By:` trailers, "Generated with Claude Code" lines, or any other attribution to commit messages, PR descriptions or tags.
- Never force-push, rewrite history, or push to any other remote.

## When unsure

Choose the option that keeps evidence safe and the build green, write the decision in your task's progress file under "Decisions", and keep going. Do not stop to ask questions during the overnight run.
