# Pramaan

Multi-vendor DVR/NVR forensic analysis platform — Smart India Hackathon 2026, problem statement 26150 (NTRO).

This repository starts as a **build kit**: the product requirements, five implementation docs, a promptbook and an orchestrator prompt that let Claude Code build the MVP overnight with parallel subagents.

## What's here

| Path | What it is |
| --- | --- |
| `CLAUDE.md` | Repo rules Claude Code reads automatically (forensic integrity, ownership, gates) |
| `docs/PRD.md` | Product requirements document |
| `docs/01-FORENSIC-CORE.md` | Evidence I/O, scanner, vendor parsers, carving, format inference, logs, deletion verdict; shared contracts |
| `docs/02-BACKEND.md` | FastAPI, job pipeline, custody chain, reports + BSA Section 63 certificate, signed export |
| `docs/03-AI-TIMELINE.md` | Four-clock timeline, OSD OCR, motion triage, detection, Claude assistant |
| `docs/04-FRONTEND.md` | Top-tier examiner UI, screens, quality bar, visual QA loop |
| `docs/05-INFRA-QA.md` | Tooling, synthetic DVR corpus + ground truth, validation, e2e, Docker, CI, deliverable docs |
| `docs/PROMPTBOOK.md` | Waves of task prompts with owners, acceptance and verification |
| `docs/ORCHESTRATOR.md` | How to launch the overnight run + the orchestrator prompt |
| `references/` | Brand kit (`BRAND.md`, `tokens.css`, `logo.svg`) and UI references |

## Run the overnight build

Follow `docs/ORCHESTRATOR.md` Part A. In short: commit this kit to a fresh repo, keep the machine awake, start Claude Code in the repo root with permissions pre-approved (ideally in a VM/container), and send:

```text
Read docs/ORCHESTRATOR.md and execute Part B. Start now; do not wait for me.
```

In the morning, read `docs/MORNING_REPORT.md`.

## Important

The MVP is validated on a **synthetic** DVR disk corpus modelled on published research layouts. It does not yet claim compatibility with real vendor disks; real-disk validation is the next milestone (PRD §10).
