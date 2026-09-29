#!/usr/bin/env bash
# Pramaan environment doctor — docs/05-INFRA-QA.md §2.
#
# Prints a table of prerequisites, whether each was found, and which
# fallback is active when an optional tool is missing. `--md` prints a
# GitHub-flavoured Markdown table instead of a plain aligned one, for
# pasting into docs/progress/<TASK_ID>.md.
set -uo pipefail

MD=0
if [ "${1:-}" = "--md" ]; then
  MD=1
fi

# Each row: name|required(yes/no)|found(yes/no)|detail|fallback
ROWS=()

check_cmd() {
  # check_cmd <label> <binary> <required> <fallback> [version_flag]
  local label="$1" bin="$2" required="$3" fallback="$4" vflag="${5:---version}"
  if command -v "$bin" >/dev/null 2>&1; then
    local ver
    ver="$("$bin" $vflag 2>&1 | head -n1)"
    ROWS+=("${label}|${required}|yes|${ver}|-")
  else
    ROWS+=("${label}|${required}|no|not found|${fallback}")
  fi
}

# Python >= 3.11 + uv (required)
if command -v python3 >/dev/null 2>&1; then
  PYVER="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || echo unknown)"
  PYOK="$(python3 -c 'import sys; print(1 if sys.version_info[:2] >= (3, 11) else 0)' 2>/dev/null || echo 0)"
  if [ "$PYOK" = "1" ]; then
    ROWS+=("Python >=3.11|yes|yes|${PYVER}|-")
  else
    ROWS+=("Python >=3.11|yes|no|found ${PYVER} (<3.11)|install Python 3.11+")
  fi
else
  ROWS+=("Python >=3.11|yes|no|not found|install Python 3.11+")
fi
check_cmd "uv" uv yes "install uv via its official installer (https://astral.sh/uv)"

# Node >= 20 + pnpm (required)
if command -v node >/dev/null 2>&1; then
  NODEVER="$(node --version)"
  NODEMAJOR="$(node -e 'process.stdout.write(String(process.versions.node.split(".")[0]))' 2>/dev/null || echo 0)"
  if [ "${NODEMAJOR:-0}" -ge 20 ] 2>/dev/null; then
    ROWS+=("Node >=20|yes|yes|${NODEVER}|-")
  else
    ROWS+=("Node >=20|yes|no|found ${NODEVER} (<20)|install Node 20+")
  fi
else
  ROWS+=("Node >=20|yes|no|not found|install Node 20+")
fi
check_cmd "pnpm" pnpm yes "corepack enable"

# ffmpeg + ffprobe (required)
check_cmd "ffmpeg" ffmpeg yes "install via system package manager"
check_cmd "ffprobe" ffprobe yes "install via system package manager"

# Optional tools
check_cmd "Rust (cargo)" cargo no "Python scanner fallback (packages/core pure-Python backend)"
check_cmd "maturin" maturin no "Python scanner fallback; PyO3 build skipped by 'just setup'"
check_cmd "Docker" docker no "inline jobs; LocalAnchor instead of Fabric"
check_cmd "Redis (redis-server)" redis-server no "JOB_BACKEND=inline"
check_cmd "tesseract" tesseract no "other OCR engines / template matcher"
check_cmd "ewfacquire (libewf)" ewfacquire no "raw images only (no E01 acquisition)" "-h"

if command -v kaitai-struct-compiler >/dev/null 2>&1; then
  ROWS+=("kaitai-struct-compiler|no|yes|$(kaitai-struct-compiler --version 2>&1 | head -n1)|-")
elif command -v ksc >/dev/null 2>&1; then
  ROWS+=("kaitai-struct-compiler|no|yes|$(ksc --version 2>&1 | head -n1)|-")
else
  ROWS+=("kaitai-struct-compiler|no|no|not found|hand-written struct parsers (.ksy kept as spec)")
fi

print_plain() {
  printf "%-24s %-9s %-6s %-40s %s\n" "TOOL" "REQUIRED" "FOUND" "DETAIL" "FALLBACK IF MISSING"
  printf '%s\n' "--------------------------------------------------------------------------------------------------------------------"
  for row in "${ROWS[@]}"; do
    IFS='|' read -r label required found detail fallback <<< "$row"
    printf "%-24s %-9s %-6s %-40s %s\n" "$label" "$required" "$found" "${detail:0:40}" "$fallback"
  done
}

print_md() {
  echo "| Tool | Required | Found | Detail | Fallback if missing |"
  echo "| --- | --- | --- | --- | --- |"
  for row in "${ROWS[@]}"; do
    IFS='|' read -r label required found detail fallback <<< "$row"
    echo "| ${label} | ${required} | ${found} | ${detail} | ${fallback} |"
  done
}

if [ "$MD" = "1" ]; then
  print_md
else
  print_plain
fi

# Exit non-zero only if a REQUIRED tool is missing.
missing_required=0
for row in "${ROWS[@]}"; do
  IFS='|' read -r label required found _detail _fallback <<< "$row"
  if [ "$required" = "yes" ] && [ "$found" = "no" ]; then
    missing_required=1
    echo "MISSING REQUIRED TOOL: ${label}" >&2
  fi
done
exit $missing_required
