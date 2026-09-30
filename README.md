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
| `docs/SOP.md` | Examiner standard operating procedure |
| `docs/USER_MANUAL.md` | Screen-by-screen guide with screenshots |
| `docs/OEM_COMPARISON.md` | What's synthetic vs. proven per OEM family, and the next milestone |
| `docs/DEMO_SCRIPT.md` | The finale demo, click by click, with fallbacks |
| `docs/VALIDATION.md` | Generated validation report (`just validate`) — current numbers against PRD §9 targets |
| `references/` | Brand kit (`BRAND.md`, `tokens.css`, `logo.svg`) and UI references |

## Quick start

Requires Python 3.11+ with `uv`, Node 20+ with `pnpm`, and `ffmpeg`/`ffprobe` on `PATH`. Rust/maturin, Docker, Redis and tesseract are optional — `just doctor` reports what's available and which fallback is active for anything missing (`docs/05-INFRA-QA.md` §2).

```bash
just setup      # uv sync + pnpm install + optional Rust/Kaitai build + doctor table
just corpus     # build the synthetic DVR disk corpus into corpus/images/ (small profile)
just check      # lint, types, unit tests across every language — the one gate
just demo       # seed a demo case through the real API and scan it (idempotent)
just dev        # run the API (real mode) + web app together for interactive use
just validate   # run the full pipeline over the corpus, regenerate docs/VALIDATION.md
just e2e        # API lifecycle + tamper tests, plus the real-mode UI test suite
```

`just dev` serves the web app at `http://localhost:5173` (API on `:8000`); seeded logins are `examiner`/`demo`, `reviewer`/`demo`, `admin`/`demo`. See `docs/DEMO_SCRIPT.md` for a full click-by-click walkthrough, including the exact commands to pre-seed a demo case before showing it to anyone.

## Run the overnight build

Follow `docs/ORCHESTRATOR.md` Part A. In short: commit this kit to a fresh repo, keep the machine awake, start Claude Code in the repo root with permissions pre-approved (ideally in a VM/container), and send:

```text
Read docs/ORCHESTRATOR.md and execute Part B. Start now; do not wait for me.
```

In the morning, read `docs/PROGRESS.md` and each task's `docs/progress/<TASK_ID>.md`.

## Important

The MVP is validated only on a **synthetic** DVR disk corpus (`tools/synthdvr`, families HIKSIM/DHSIM/HWSIM/XSIM/GENSIM) modelled on published research layouts. It does not claim compatibility with real vendor disks — see `docs/OEM_COMPARISON.md` for exactly what is and is not proven per OEM family, and `docs/VALIDATION.md` for current numbers. Real-disk validation is the next milestone (PRD §10).
