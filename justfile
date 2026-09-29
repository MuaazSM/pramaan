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
# Corpus, validation, demo, e2e, screenshots — stubs until their owning
# tasks (Q1/Q2, Q3, F-tasks) land. Each prints a message and exits 0 so
# `just check`/CI never depend on unimplemented work.
# ---------------------------------------------------------------------------

# Builds the synthetic DVR disk corpus (docs/05-INFRA-QA.md §4) into
# corpus/images/ (gitignored) + corpus/truth/, and corpus/manifest.json.
# Q1 (this) wires HIKSIM/DHSIM/GENSIM; Q2 (Wave 2) adds HWSIM/XSIM to the
# same `pramaan_synthdvr.cli` registry. Only the "small" profile exists
# (the ~13 GiB free disk budget on the dev machine rules out "full").
corpus profile="small":
    uv run python -m pramaan_synthdvr.cli build-all {{profile}}

validate:
    @echo "just validate: not yet implemented (Q3, Wave 4 builds tests/validation + docs/VALIDATION.md)."

demo:
    @echo "just demo: not yet implemented (wired once B1/B2 land the case pipeline, Wave 1-2)."

e2e:
    @echo "just e2e: not yet implemented (Q3, Wave 4 wires tests/e2e Playwright + API e2e)."

shots:
    @echo "just shots: not yet implemented (F1, Wave 1 wires 'pnpm -C apps/web shots')."

# ---------------------------------------------------------------------------
# Dev loop and Docker Compose — stubs/skeleton until B1 (apps/api,
# apps/worker) and infra/docker/ land.
# ---------------------------------------------------------------------------

dev:
    @echo "just dev: not yet implemented (needs apps/api + apps/web dev servers, wired by B1/F1)."

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
