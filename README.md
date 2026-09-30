# Pramaan

**Multi-vendor DVR/NVR forensic analysis platform.** Pramaan identifies a CCTV recorder's disk format, lists and plays its recordings, recovers deleted footage, discovers undocumented layouts from the bytes alone, reconciles the recorder's clocks into one trustworthy timeline, and produces a signed, court-ready report with a Bharatiya Sakshya Adhiniyam (BSA) Section 63 certificate. Every step is read-only, reproducible and recorded in a hash-chained custody log.

Built for Smart India Hackathon 2026, problem statement **26150** (NTRO).

> **Synthetic data only.** Pramaan is validated on a *synthetic* DVR disk corpus (families HIKSIM, DHSIM, HWSIM, XSIM, GENSIM) modelled on published research layouts. It has **not** been tested on real vendor disks and makes no compatibility claim for any real manufacturer. Real-disk validation is the next milestone.

---

## Contents

- [What it does](#what-it-does)
- [Validation results](#validation-results)
- [How it works](#how-it-works)
- [Repository layout](#repository-layout)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Demo walkthrough](#demo-walkthrough)
- [Command reference](#command-reference)
- [Configuration](#configuration)
- [Forensic guarantees](#forensic-guarantees)
- [The synthetic corpus](#the-synthetic-corpus)
- [AI assistant and its guardrails](#ai-assistant-and-its-guardrails)
- [Testing and quality gates](#testing-and-quality-gates)
- [Known limitations](#known-limitations)
- [How this repository was built](#how-this-repository-was-built)

---

## What it does

| Capability | What the examiner gets |
| --- | --- |
| **Identify** | Fingerprints the disk image, names the recorder family and support tier (A = known layout, B = inferred layout, C = raw carving), and shows the reasons and OEM lineage behind the match. |
| **Acquire / register** | Registers an image read-only, computes SHA-256 and MD5 in one streaming pass, verifies them, and records the seizure clock (recorder display time vs. reference time). Raw and E01 images are supported (E01 via `pyewf` when available). |
| **Parse** | Lists every recording per channel with byte offsets, for HIKSIM, DHSIM and HWSIM (Tier A). |
| **Recover** | Finds deleted and unindexed footage (format, retention expiry, overwrite scenarios) with vendor-aware and generic H.264/H.265 carvers, and builds playable clips by **stream copy** — never re-encoding. |
| **Infer (Tier B)** | For an unknown recorder (XSIM), discovers the record header layout (magic, channel, timestamp, length, sequence) from the data alone, emits a draft `.ksy` spec and a plain-language summary, and lets the examiner confirm it; confirmation re-runs the downstream pipeline. |
| **Timeline** | Four-clock normalisation (frame header, recording index, on-screen OSD text via OCR, seizure reference) with per-frame confidence; handles clock changes, including a clock set back by an hour. |
| **Logs and deletion verdicts** | Parses device logs (including records carved from outside the log area) and explains each deletion: method (format / expiry / overwrite), time window and, when a log exists, the actor. |
| **Review** | A synced multi-camera workspace: canvas timeline with coverage, deleted and motion layers, 1/4/9 video grid, J/K/L shuttle, frame stepping, jump-to-timecode, and a frame inspector. |
| **Prove it** | For any frame, an annotated hex view of the exact bytes on disk, with sector numbers, decoded header fields and a live in-browser SHA-256 recompute against the stored hash. |
| **Report** | A deterministic manifest (stable `report_sha256`), a branded, digitally signed PDF report and a prefilled BSA Section 63 certificate (Part A / Part B) whose wording follows the actual intake path. |
| **Export** | Signed MP4 exports (stream copy) with an embedded and a detached Ed25519-signed manifest, plus a verify endpoint that detects any tampering. |
| **Custody** | Every mutating action is an Ed25519-signed, hash-chained audit entry; the chain can be verified from the UI, and Merkle roots are anchored to a local ledger. |
| **Motion triage** | Frame-difference motion events drawn on the timeline to speed up review. |
| **Assistant (optional)** | "Ask about this case" and narrative drafting over structured metadata only, labelled as AI drafts, budget-capped, off by default. |

---

## Validation results

`just validate` runs the full corpus through the real API and regenerates the validation report. Latest run (10 images, 0 run errors):

| Metric | Target | Result |
| --- | --- | --- |
| Deleted-frame recovery (synthetic) | ≥ 95% | 99.8% ✅ |
| Recovery precision | ≥ 99% | 99.7% ✅ |
| Recording parse | 100% | 100% ✅ |
| Timestamp error ≤ 1 s | ≥ 99% | 100% ✅ |
| Deletion actor attribution | 100% | 100% ✅ |
| XSIM inference (5 required fields) | 100% | 100% ✅ |
| Motion F1 | ≥ 80% | 100% ✅ |
| Determinism (report hash stable across cases) | yes | yes ✅ |
| Read-only guarantee | yes | yes ✅ |
| Deletion method correct | 100% | 83.3% ⚠️ — the remaining miss is on `xsim_format` and is being fixed in the harness (it scored findings before the examiner confirmed the inferred layout) |

Methodology notes (from the validation harness):

- Only frames and motion events that physically survive on disk are scored; footage the scenario overwrote completely is reported separately as unrecoverable, not counted as a miss.
- Tier B (XSIM) metrics are scored after examiner confirmation of the inferred layout, mirroring the real workflow.
- The harness compares the inferred XSIM layout with hidden ground truth; the inference code itself never sees that truth (a test fails if any XSIM signature appears as a literal in `packages/`).

Scan throughput is reported per image as whole-job wall-clock time; it is not scored against a target.

---

## How it works

```text
            ┌───────────────────────────── apps/web (React) ─────────────────────────────┐
            │ cases · evidence · recordings · findings · review · prove-it · reports ... │
            └──────────────────────────────────┬──────────────────────────────────────────┘
                                               │  REST + WebSocket (typed OpenAPI client)
            ┌──────────────────────────────────▼──────────────────────────────────────────┐
            │ apps/api (FastAPI)  auth · cases · evidence · jobs · frames · hex · clips  │
            │                     reports · exports · custody · anchors · timeline · AI  │
            └──────────────────────────────────┬──────────────────────────────────────────┘
                                               │  job runner (inline or dramatiq + Redis)
 apps/worker pipeline (resumable, each stage cached by input hash):
   hash_verify → fingerprint → parse_index → infer_layout → carve → frame_index
               → logs → deletion_verdict → clips → timeline → motion
                                               │
  packages/core      read-only EvidenceReader, hashing, models, case DB, Parquet frame index, provenance
  crates/scanner     Rust signature / Annex-B scanner (PyO3), with a byte-identical pure-Python fallback
  packages/formats   fingerprints, HIKSIM / DHSIM / HWSIM parsers (+ .ksy specs)
  packages/recovery  carvers, SPS clustering, clip builder, format inference, deletion verdicts
  packages/logs      RATS / DHLG device-log parsers
  packages/timeline  clock models, OSD reader (Paddle → Rapid → Tesseract → template matcher)
  packages/analytics motion triage
  packages/custody   Ed25519 hash chain, Merkle anchors
  packages/reporting manifest, HTML → PDF (WeasyPrint, Chromium fallback), PAdES signing, BSA §63
  packages/export    signed MP4 export and verification
  packages/llm       guarded, budgeted Claude layer (fixture / Anthropic / local providers)
```

Each case lives in its own folder under the data directory: a SQLite case database, Parquet frame indexes, derived artefacts (thumbnails, clips, reports, exports) with provenance, and a JSONL mirror of the custody chain.

---

## Repository layout

| Path | Contents |
| --- | --- |
| `apps/api` | FastAPI application, routers, real-mode stores, fixtures for stub mode, `openapi.json` (generated) |
| `apps/worker` | Pipeline stages, stage registry, inline and dramatiq job runners |
| `apps/web` | React 19 + TypeScript (strict) + Vite + Tailwind v4 examiner UI, MSW mocks, Playwright specs |
| `packages/*` | Python libraries listed in [How it works](#how-it-works) (uv workspace) |
| `crates/scanner` | Rust scanner crate (optional at runtime) |
| `tools/synthdvr` | Deterministic synthetic DVR disk generator and ground truth |
| `tools/demo` | `just demo` seeding script |
| `tools/validate` | Validation harness behind `just validate` |
| `tools/bindiff` | Block-level binary diff helper for disk images |
| `tools/doctor.sh` | Prerequisite check behind `just doctor` |
| `corpus/` | Corpus manifest and ground truth (`truth/*.json`); images are generated into `corpus/images/` (gitignored) |
| `tests/{core,backend,ai,validation,e2e}` | Test suites per workstream |
| `references/` | Brand kit (`BRAND.md`, `tokens.css`, `logo.svg`) and UI references |
| `CLAUDE.md` | Repository rules (forensic integrity, ownership, gates) |

The product requirements, implementation specs, SOP, user manual, OEM comparison, demo script and generated validation report live in `docs/`, which is kept local and is not published in this repository.

---

## Requirements

| Tool | Required | Notes |
| --- | --- | --- |
| Python 3.11+ with [uv](https://docs.astral.sh/uv/) | yes | Python workspace and virtualenv |
| Node 20+ with pnpm | yes | Web app |
| ffmpeg / ffprobe | yes | Clip remux (stream copy), corpus encoding, decoding for OSD and motion |
| [just](https://github.com/casey/just) | yes | Command runner |
| Rust (cargo) + maturin | optional | Fast scanner; the pure-Python fallback is used otherwise |
| Redis | optional | `dramatiq` job backend; the inline runner is the default |
| Tesseract | optional | One of the OCR fallbacks; a built-in template matcher always works |
| ewfacquire (libewf) | optional | E01 corpus variant |
| Kaitai Struct compiler | optional | `.ksy` specs are kept as documentation; parsers are hand-written |

Run `just doctor` to see what is installed and which fallback is active. Disk use is modest: the default corpus is about 46 MiB.

---

## Quick start

```bash
git clone https://github.com/MuaazSM/pramaan.git
cd pramaan

just setup      # uv sync, pnpm install, optional Rust build, doctor table
just corpus     # generate the 10-image synthetic corpus into corpus/images/
just check      # lint + types + unit tests for every language (the one gate)
just demo       # seed demo case CR-2026-0412 through the real API and scan it
```

To explore the seeded case in the browser:

```bash
just demo --keep-running --port 8000   # API on :8000 with the seeded demo data
pnpm -C apps/web dev                   # web app on http://localhost:5173
```

Logins: `examiner` / `demo`, `reviewer` / `demo` (read-only review role), `admin` / `demo`.

`just dev` also starts the API and web app together, but against a separate, empty data directory (`./data/dev`); use it to register your own evidence. `just dev-mock` runs the web app alone against built-in mocks, with no API needed.

---

## Demo walkthrough

`just demo` creates case **CR-2026-0412**, registers `hiksim_format`, `dhsim_format`, `hwsim_format` and `xsim_unknown`, scans them, confirms the XSIM inferred layout, generates a signed report with the BSA certificate, creates a signed export and verifies it. A good 7–10 minute path through the UI:

1. **Cases → CR-2026-0412**: integrity summary, evidence cards with tier badges, recent custody entries.
2. **Evidence → hiksim_format**: identification reasons and OEM lineage, the 11-stage pipeline, device log table (note the `hdd format` event by `admin`).
3. **Findings**: the format deletion on CH3, with method, actor, window, reasons and recovered-frame links.
4. **Review**: scrub the multi-camera timeline, see the hatched deleted region and motion strip, press `G` and jump to a timecode, step frames with the arrow keys, open the frame inspector's clock stack.
5. **Prove it**: from a recovered frame, open the hex view and watch the SHA-256 recompute match the stored hash.
6. **Evidence → xsim_unknown**: the inferred layout panel, its summary and draft spec, and the confirmation that made the footage playable.
7. **Reports**: download the signed PDF and the BSA Section 63 certificate; note the report hash.
8. **Exports**: verify a signed export, then verify a tampered copy and watch it fail.
9. **Custody**: re-verify the hash chain and show the Merkle anchor.

Press `?` anywhere for the keyboard shortcut sheet and `⌘K` / `Ctrl+K` for the command palette.

---

## Command reference

| Command | What it does |
| --- | --- |
| `just setup` | Install Python and Node dependencies, build the optional Rust extension, print the doctor table |
| `just doctor` | Show prerequisites and active fallbacks |
| `just check` | Every scoped check below, in one gate |
| `just check-core` / `check-backend` / `check-ai` / `check-web` / `check-qa` | Scoped lint, type and unit-test gates per workstream (`check-backend` also fails if `openapi.json` is stale) |
| `just corpus [profile]` | Generate the synthetic corpus (`small` profile) and its manifest |
| `just demo [--keep-running] [--port N]` | Seed and scan the demo case through the real API; idempotent |
| `just dev` | API (real mode) + web dev server together |
| `just dev-mock` | Web app only, against mocks |
| `just validate` | Full-corpus validation through the real API; regenerates the validation report |
| `just e2e` | API lifecycle and tamper tests, plus the real-mode Playwright suite |
| `just shots` | Playwright screenshots of every screen in both themes and two sizes |
| `pnpm -C apps/web lighthouse` | Lighthouse and bundle budgets for the web app |

Slow corpus-backed tests are excluded from `just check`; run them with `uv run pytest tests/<suite> -m slow`.

---

## Configuration

The API reads environment variables with the `PRAMAAN_` prefix (and a local `.env`, which is gitignored).

| Variable | Default | Meaning |
| --- | --- | --- |
| `PRAMAAN_DATA_DIR` | `./data` | Root for case folders, keys, app database and anchor ledger |
| `PRAMAAN_STUB_MODE` | `true` | `true` serves deterministic fixtures; set `0`/`false` for real cases (`just demo` and `just dev` do this) |
| `PRAMAAN_EVIDENCE_ROOTS` | `["./data/evidence"]` | JSON list of directories evidence may be registered from |
| `PRAMAAN_JOB_BACKEND` | `inline` | `inline` or `dramatiq` (needs Redis) |
| `PRAMAAN_REDIS_URL` | `redis://localhost:6379/0` | Redis for the dramatiq backend |
| `PRAMAAN_ANCHOR_BACKEND` | `local` | `local` Merkle ledger (`fabric` is not implemented) |
| `PRAMAAN_SESSION_SECRET` | development value | Session signing secret; **set a strong value outside development** |
| `PRAMAAN_LLM_ENABLED` | `false` | Enables the assistant routes |
| `PRAMAAN_LLM_PROVIDER` | `fixture` | `fixture` (offline recorded responses), `anthropic` or `local` (Ollama) |
| `PRAMAAN_ANTHROPIC_API_KEY` | unset | Only needed with the `anthropic` provider; never commit it |

The web app talks to the real API by default and proxies `/api` (including the WebSocket) to `http://localhost:8000`; `VITE_MOCK=1` switches it to mocks.

---

## Forensic guarantees

These rules are enforced in code and by tests:

1. **Evidence is read-only.** Images are opened with read-only file modes only (`O_RDONLY`, read-only `mmap`); tests assert the image hash and modification time are unchanged after a full scan. Only `packages/core` opens evidence files.
2. **Original video is never re-encoded.** Clips and exports are stream-copied; `ffprobe` checks confirm codec parameters match the source.
3. **Provenance on every derived artefact**: parent SHA-256, tool version, function, parameters and UTC timestamp.
4. **Determinism.** The same input and version produce byte-identical frame indexes, clips, export manifests and report manifests; IDs derive from content hashes, including frame IDs (image, offset, payload hash).
5. **Custody.** Every mutating API action appends an Ed25519-signed, hash-chained audit entry; verification recomputes the chain end to end.
6. **The LLM never produces a finding.** See below.

---

## The synthetic corpus

`just corpus` deterministically generates 10 small disk images (same config → same SHA-256) with exact ground truth for every frame, recording, deletion, log event, clock segment and motion event.

| Family | Tier | Modelled on | Images |
| --- | --- | --- | --- |
| HIKSIM | A | Hikvision-style layout from published research | `hiksim_clean`, `hiksim_format`, `hiksim_clockchange` (+ E01 variant) |
| DHSIM | A | Dahua-style layout from published research | `dhsim_format`, `dhsim_expiry` |
| HWSIM | A | GPT-partitioned layout with 20-byte NAL headers | `hwsim_format`, `hwsim_overwrite` |
| XSIM | B | Undocumented layout, known only to the generator's ground truth | `xsim_unknown`, `xsim_format` |
| GENSIM | C | Raw interleaved H.264 with no headers | `gensim_carve` |

Video is rendered with an on-screen date/time overlay and scripted motion, encoded once to H.264, and embedded exactly as each format specifies. Scenarios cover format deletion, retention expiry, overwrite, a clock set back by one hour and OSD clock drift.

---

## AI assistant and its guardrails

The assistant is **off by default** and works fully offline with recorded fixtures.

- It only ever receives structured metadata. A payload guard rejects frames, thumbnails, disk bytes and oversized payloads before any provider call.
- Case questions are answered by a locally executed `search_evidence` tool; the model proposes a filter, shown to the examiner as editable chips.
- Narrative drafts are validated sentence by sentence: every sentence must cite evidence IDs that exist, and the output is labelled as an AI draft that the examiner accepts or rejects.
- A budget meter enforces spend caps in code, and every call is recorded in `llm_calls` and the custody log.
- Tests never call a live API; a single optional live smoke test runs only when both `ANTHROPIC_API_KEY` and `LLM_LIVE_SMOKE=1` are set.

---

## Testing and quality gates

- **Python**: `ruff` and `mypy --strict` on `packages/`, pytest suites per workstream (core, backend, ai, validation), with slow corpus-backed tests behind `-m slow`.
- **Rust**: `cargo fmt`, `clippy -D warnings`, unit tests; parity tests prove the Rust and Python scanners return identical results.
- **Web**: ESLint with a token lint (no raw colours outside brand tokens), `tsc` strict, Vitest (including a timeline redraw performance test: well under 8 ms per frame for 8 channels × 24 h), Playwright screenshot and mock e2e specs, Lighthouse and bundle budgets (initial JS about 149 KB gzip against a 300 KB budget).
- **Contracts**: `apps/api/openapi.json` is generated and checked for staleness; the web client is generated from it.
- **End to end**: API lifecycle and tamper tests (evidence, export, custody chain) and a real-mode Playwright suite against a demo-seeded API.
- **Validation**: `just validate` measures every metric above against the corpus ground truth.

---

## Known limitations

- **Synthetic corpus only.** No real vendor disk has been tested; results above apply to the synthetic families.
- **BSA Section 63 certificate** is a prefilled template; verify its wording against the official Schedule before filing. Signatures use a clearly labelled **test** lab certificate.
- **Fabric anchoring** is not implemented (returns 501); only the local Merkle ledger is available.
- **Docker Compose** (`just up` / `just down`) is not set up yet; run the services with `just dev`.
- **Detection** (object detection on the timeline) is not implemented; motion triage is.
- **E01** support depends on `pyewf`; the positive E01 path has limited test coverage.
- The corpus's E01 variant is not byte-for-byte reproducible, because `ewfacquire` stamps the acquisition time; the raw images are.

---

## How this repository was built

The MVP was built in one overnight run by an orchestrating Claude Code session that executed a promptbook of task cards in waves, dispatching parallel subagents per workstream (core, backend, AI, web, QA), reviewing each result, running the gates and committing. The rules every agent followed are in `CLAUDE.md`.
