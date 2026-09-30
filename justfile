# Pramaan — one-command gates. See docs/05-INFRA-QA.md §3.
#
# `just setup` prepares a clean clone; `just check` is the gate every wave
# and every scoped workstream runs before calling a task done.

set shell := ["bash", "-uc"]

default: check

# ---------------------------------------------------------------------------
# Setup and environment
# ---------------------------------------------------------------------------

# Prepare a clean clone: Python workspace, pnpm workspace, optional Rust
# extension build, optional Kaitai compile, then print the doctor table.
setup:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "== uv sync (Python workspace) =="
    uv sync --all-packages
    echo "== pnpm install (web workspace) =="
    pnpm install
    echo "== maturin develop (optional Rust extension) =="
    # maturin is a `uv add --dev` dependency (root pyproject.toml), installed
    # into .venv by the `uv sync` above — never required on PATH. The
    # `python` Cargo feature (crates/scanner/Cargo.toml) is off by default so
    # plain `cargo build/test/clippy` never need it; only this maturin build
    # turns it on. Run from crates/scanner/ (not the repo root) so maturin's
    # pyproject.toml auto-discovery doesn't pick up the root workspace file,
    # which isn't a maturin project and has no [build-system] table.
    if command -v cargo >/dev/null 2>&1 && uv run --no-sync maturin --version >/dev/null 2>&1; then
        echo "cargo + maturin available; building the pramaan_scanner extension (release, feature 'python')."
        (cd crates/scanner && uv run --no-sync maturin develop --release --features python)
    elif command -v cargo >/dev/null 2>&1; then
        echo "cargo found, maturin not installed — skipping PyO3 build. Pure-Python scanner fallback will be used (docs/05-INFRA-QA.md §2)."
    else
        echo "cargo not found — skipping Rust build entirely. Pure-Python scanner fallback will be used."
    fi
    echo "== Kaitai Struct compile (optional) =="
    if command -v kaitai-struct-compiler >/dev/null 2>&1 || command -v ksc >/dev/null 2>&1; then
        echo "kaitai-struct-compiler available; C2 (Wave 2) wires the .ksy -> packages/formats/pramaan_formats/generated compile step."
    else
        echo "kaitai-struct-compiler not found — skipping. Fallback: hand-written struct parsers, .ksy files kept as the spec (docs/05-INFRA-QA.md §2)."
    fi
    echo "== Fonts (Geist Mono / DejaVu Sans Mono for OSD + corpus rendering) =="
    echo "Font download/verification is wired by F1 (web) and Q1 (synthdvr) in Wave 1. Skipping for now."
    echo "== setup complete =="

# Print the environment prerequisites table (docs/05-INFRA-QA.md §2).
# `just doctor --md` (or `just doctor md`) prints Markdown, for pasting
# into a progress file.
doctor mode="plain":
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "{{mode}}" = "md" ] || [ "{{mode}}" = "--md" ]; then
        ./tools/doctor.sh --md
    else
        ./tools/doctor.sh
    fi

# ---------------------------------------------------------------------------
# The gate: `just check` = every scoped check, run by the orchestrator at
# every wave gate. Subagents run only their own scoped target while working.
# ---------------------------------------------------------------------------

check: check-core check-backend check-ai check-web check-qa
    @echo "== just check: all scoped checks passed =="

# CORE: packages/core, packages/formats, packages/recovery, packages/logs,
# crates/scanner, tests/core.
check-core:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "== check-core: ruff =="
    uv run ruff check packages/core packages/formats packages/recovery packages/logs
    echo "== check-core: mypy --strict =="
    uv run mypy --strict packages/core packages/formats packages/recovery packages/logs
    echo "== check-core: pytest (not slow) =="
    just _pytest tests/core
    echo "== check-core: cargo fmt/clippy/test (crates/scanner, optional) =="
    if command -v cargo >/dev/null 2>&1; then
        cargo fmt --manifest-path Cargo.toml --check
        cargo clippy --workspace --all-targets --manifest-path Cargo.toml -- -D warnings
        cargo test --workspace --manifest-path Cargo.toml
    else
        echo "cargo not found — skipping Rust checks (Python scanner fallback is authoritative)."
    fi

# BACKEND: apps/api, apps/worker, packages/custody, packages/reporting,
# packages/export, tests/backend. OpenAPI export/diff is wired once
# apps/api/pramaan_api has real routes (W0.3).
check-backend:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "== check-backend: ruff =="
    uv run ruff check apps/api apps/worker packages/custody packages/reporting packages/export
    echo "== check-backend: mypy --strict (packages/) =="
    uv run mypy --strict packages/custody packages/reporting packages/export
    echo "== check-backend: pytest (not slow) =="
    just _pytest tests/backend
    echo "== check-backend: OpenAPI export + diff =="
    if [ -f apps/api/pramaan_api/openapi_export.py ]; then
        uv run python apps/api/pramaan_api/openapi_export.py --check
    else
        echo "apps/api/pramaan_api/openapi_export.py not present yet (wired by W0.3) — skipping."
    fi

# AI: packages/timeline, packages/analytics, packages/llm, tests/ai.
check-ai:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "== check-ai: ruff =="
    uv run ruff check packages/timeline packages/analytics packages/llm
    echo "== check-ai: mypy --strict =="
    uv run mypy --strict packages/timeline packages/analytics packages/llm
    echo "== check-ai: pytest (not slow) =="
    just _pytest tests/ai

# WEB: apps/web.
check-web:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "== check-web: lint =="
    pnpm -C apps/web lint
    echo "== check-web: typecheck =="
    pnpm -C apps/web typecheck
    echo "== check-web: test =="
    pnpm -C apps/web test

# QA: root tooling, tools/, corpus/, tests/e2e, tests/validation.
check-qa:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "== check-qa: ruff (tools/) =="
    uv run ruff check tools
    echo "== check-qa: pytest tests/e2e (not slow) =="
    just _pytest tests/e2e
    echo "== check-qa: pytest tests/validation (not slow) =="
    just _pytest tests/validation
    echo "== check-qa: corpus manifest present =="
    test -f corpus/manifest.json

# Internal helper: run pytest on a path if it exists, tolerating "no tests
# collected" (exit code 5) for still-empty test directories.
_pytest path:
    #!/usr/bin/env bash
    set -uo pipefail
    if [ ! -d "{{path}}" ]; then
        echo "{{path}} does not exist yet — skipping."
        exit 0
    fi
    uv run pytest "{{path}}" -m "not slow"
    ec=$?
    if [ "$ec" -eq 0 ]; then
        exit 0
    elif [ "$ec" -eq 5 ]; then
        echo "{{path}}: no tests collected — treated as pass."
        exit 0
    else
        exit "$ec"
    fi

# ---------------------------------------------------------------------------
# Corpus, validation, demo, e2e, screenshots.
# ---------------------------------------------------------------------------

# Builds the synthetic DVR disk corpus (docs/05-INFRA-QA.md §4) into
# corpus/images/ (gitignored) + corpus/truth/, and corpus/manifest.json.
# Q1 (this) wires HIKSIM/DHSIM/GENSIM; Q2 (Wave 2) adds HWSIM/XSIM to the
# same `pramaan_synthdvr.cli` registry. Only the "small" profile exists
# (the ~13 GiB free disk budget on the dev machine rules out "full").
corpus profile="small":
    uv run python -m pramaan_synthdvr.cli build-all {{profile}}

# Runs the full synthetic corpus through the real API (docs/05-INFRA-QA.md
# §5, task Q3) and writes docs/VALIDATION.md + docs/validation.json. Always
# exits 0 once it completes a run — every metric a corpus image can't
# exercise, or whose producer hasn't landed, is recorded as "not available"
# with a reason rather than crashing the harness (see docs/VALIDATION.md
# "Cross-workstream issues" for anything that traces to a bug elsewhere).
validate *args:
    uv run python tools/validate/validate.py --timeout 1800 {{args}}

demo *args:
    uv run python tools/demo/demo.py {{args}}

# API e2e + tamper tests (tests/e2e, real API subprocess per test — docs
# /05-INFRA-QA.md §6), then the WEB task's real-mode Playwright spec
# (apps/web/playwright/real-*.spec.ts) against a `just demo`-seeded API, if
# it has landed yet. Reports failures with a normal non-zero exit (these
# are real assertions, not a "must never fail" report like `just validate`)
# but never leaves a background API process running.
e2e:
    #!/usr/bin/env bash
    set -uo pipefail
    echo "== e2e: tests/e2e (API lifecycle + tamper tests, real API per test) =="
    uv run pytest tests/e2e -m slow
    backend_ec=$?

    web_ec=0
    real_specs=$(find apps/web/playwright -maxdepth 1 -name 'real-*.spec.ts' 2>/dev/null)
    if [ -z "$real_specs" ]; then
        echo "== e2e: no apps/web/playwright/real-*.spec.ts yet (pending WEB task F4) — skipping the Playwright real-mode spec =="
    else
        # Free :8000 first — a killed/orphaned uvicorn from a previous run
        # (e.g. a shell that didn't run this trap) can otherwise still hold
        # the port, and playwright.real.config.ts hardcodes :8000.
        for pid in $(lsof -ti:8000 2>/dev/null); do kill -9 "$pid" 2>/dev/null || true; done
        cleanup() { for pid in $(lsof -ti:8000 2>/dev/null); do kill -9 "$pid" 2>/dev/null || true; done; }
        trap cleanup EXIT

        echo "== e2e: seeding a real-mode API at :8000 for Playwright (tools/demo/demo.py --keep-running) =="
        uv run python tools/demo/demo.py --keep-running --port 8000
        demo_ec=$?
        if [ "$demo_ec" -ne 0 ]; then
            echo "== e2e: demo seeding failed (exit $demo_ec) — skipping the Playwright real-mode spec =="
            web_ec=1
        else
            echo "== e2e: running Playwright real-mode spec =="
            pnpm -C apps/web exec playwright test -c playwright.real.config.ts
            web_ec=$?
        fi
    fi

    if [ "$backend_ec" -ne 0 ]; then echo "== e2e: tests/e2e FAILED (exit $backend_ec) =="; fi
    if [ "$web_ec" -ne 0 ]; then echo "== e2e: Playwright real-mode spec FAILED (exit $web_ec) =="; fi
    if [ "$backend_ec" -eq 0 ] && [ "$web_ec" -eq 0 ]; then
        echo "== e2e: done (backend passed; Playwright real-mode ran or is pending F4) =="
    fi
    exit $(( backend_ec > web_ec ? backend_ec : web_ec ))

shots:
    @echo "just shots: not yet implemented (F1, Wave 1 wires 'pnpm -C apps/web shots')."

# ---------------------------------------------------------------------------
# Dev loop and Docker Compose — stubs/skeleton until B1 (apps/api,
# apps/worker) and infra/docker/ land.
# ---------------------------------------------------------------------------

# API (real mode) on :8000 + web dev server (real mode, VITE_MOCK unset)
# on :5173, together. `apps/web/vite.config.ts` proxies `/api` (and
# `/api/ws`) to `http://localhost:8000`, so the API must run on 8000 here.
# Data dir defaults to `./data/dev` (gitignored); override PRAMAAN_DATA_DIR /
# PRAMAAN_EVIDENCE_ROOTS / PRAMAAN_JOB_BACKEND in the environment before
# calling `just dev` to point at something else. Ctrl-C stops both.
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    export PRAMAAN_DATA_DIR="${PRAMAAN_DATA_DIR:-./data/dev}"
    export PRAMAAN_STUB_MODE=0
    export PRAMAAN_EVIDENCE_ROOTS="${PRAMAAN_EVIDENCE_ROOTS:-[\"$(pwd)/corpus/images\"]}"
    export PRAMAAN_JOB_BACKEND="${PRAMAAN_JOB_BACKEND:-inline}"
    mkdir -p "$PRAMAAN_DATA_DIR"
    echo "== just dev: API   http://127.0.0.1:8000  (real mode, data dir: $PRAMAAN_DATA_DIR) =="
    echo "== just dev: web   http://127.0.0.1:5173  (real mode, proxies /api -> :8000) =="
    trap 'kill 0' EXIT INT TERM
    uv run uvicorn pramaan_api.main:app --host 127.0.0.1 --port 8000 &
    pnpm -C apps/web dev &
    wait -n

dev-mock:
    @echo "just dev-mock: not yet implemented (needs apps/web MSW mocks, wired by F1)."

up:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -f infra/docker/compose.yml ]; then
        docker compose -f infra/docker/compose.yml up -d
    else
        echo "infra/docker/compose.yml not present yet (wired by QA/BACKEND later) — nothing to start."
    fi

down:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -f infra/docker/compose.yml ]; then
        docker compose -f infra/docker/compose.yml down
    else
        echo "infra/docker/compose.yml not present yet — nothing to stop."
    fi
