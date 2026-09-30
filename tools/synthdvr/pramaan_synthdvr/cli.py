"""`just corpus` entry point: builds the full "small" profile corpus
(docs/05-INFRA-QA.md §4.3 — HIKSIM/DHSIM/GENSIM from Q1, HWSIM/XSIM from
Q2) into corpus/images/ and corpus/truth/, checks ground-truth
self-consistency on every image, and writes corpus/manifest.json.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from pramaan_synthdvr import manifest
from pramaan_synthdvr.truth import check_self_consistency
from pramaan_synthdvr.writers import dhsim, gensim, hiksim, hwsim, xsim

REPO_ROOT = Path(__file__).resolve().parents[3]
SMALL_PROFILE_LIMIT_BYTES = 128 * 1024 * 1024

# (name, family, scenario, build_fn(images_dir, truth_dir) -> Path)
_JOBS: list[tuple[str, str, str, Callable[[Path, Path], Path]]] = [
    (
        "hiksim_clean",
        "hiksim",
        "none",
        lambda images_dir, truth_dir: hiksim.build_image(
            "hiksim_clean", images_dir, truth_dir, scenario="clean"
        ),
    ),
    (
        "hiksim_format",
        "hiksim",
        "format",
        lambda images_dir, truth_dir: hiksim.build_image(
            "hiksim_format", images_dir, truth_dir, scenario="format"
        ),
    ),
    (
        "hiksim_clockchange",
        "hiksim",
        "none+time_change+osd_drift",
        lambda images_dir, truth_dir: hiksim.build_image(
            "hiksim_clockchange", images_dir, truth_dir, scenario="clockchange"
        ),
    ),
    (
        "dhsim_format",
        "dhsim",
        "format",
        lambda images_dir, truth_dir: dhsim.build_image(
            "dhsim_format", images_dir, truth_dir, scenario="format"
        ),
    ),
    (
        "dhsim_expiry",
        "dhsim",
        "expiry",
        lambda images_dir, truth_dir: dhsim.build_image(
            "dhsim_expiry", images_dir, truth_dir, scenario="expiry"
        ),
    ),
    (
        "gensim_carve",
        "gensim",
        "n/a",
        lambda images_dir, truth_dir: gensim.build_image("gensim_carve", images_dir, truth_dir),
    ),
    (
        "hwsim_format",
        "hwsim",
        "format",
        lambda images_dir, truth_dir: hwsim.build_image(
            "hwsim_format", images_dir, truth_dir, scenario="format"
        ),
    ),
    (
        "hwsim_overwrite",
        "hwsim",
        "overwrite",
        lambda images_dir, truth_dir: hwsim.build_image(
            "hwsim_overwrite", images_dir, truth_dir, scenario="overwrite"
        ),
    ),
    (
        "xsim_unknown",
        "xsim",
        "none",
        lambda images_dir, truth_dir: xsim.build_image(
            "xsim_unknown", images_dir, truth_dir, scenario="none"
        ),
    ),
    (
        "xsim_format",
        "xsim",
        "format",
        lambda images_dir, truth_dir: xsim.build_image(
            "xsim_format", images_dir, truth_dir, scenario="format"
        ),
    ),
]


def _emit_e01(img_path: Path, target_no_ext: Path) -> None:
    """`hiksim_format.E01`, so E01 ingestion has a fixture (docs/05-INFRA-QA.md
    §4.3: "Also emit hiksim_format.E01 if ewfacquire exists")."""
    cmd = [
        "ewfacquire",
        "-u",
        "-q",
        "-f",
        "encase6",
        "-c",
        "deflate:none",
        "-m",
        "fixed",
        "-d",
        "sha256",
        "-t",
        str(target_no_ext),
        str(img_path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)


def build_all(
    profile: str = "small",
    *,
    images_dir: Path | None = None,
    truth_dir: Path | None = None,
    manifest_path: Path | None = None,
) -> list[dict[str, object]]:
    images_dir = images_dir or (REPO_ROOT / "corpus" / "images")
    truth_dir = truth_dir or (REPO_ROOT / "corpus" / "truth")
    manifest_path = manifest_path or (REPO_ROOT / "corpus" / "manifest.json")
    images_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    for name, family, scenario, build_fn in _JOBS:
        print(f"== building {name} ({family}/{scenario}) ==", file=sys.stderr)
        path = build_fn(images_dir, truth_dir)
        errs = check_self_consistency(path, truth_dir, name)
        if errs:
            raise SystemExit(
                f"{name}: ground-truth self-consistency check failed "
                f"({len(errs)} error(s)):\n" + "\n".join(errs[:20])
            )
        size = path.stat().st_size
        if size > SMALL_PROFILE_LIMIT_BYTES:
            raise SystemExit(
                f"{name}: {size} bytes exceeds the small-profile limit "
                f"({SMALL_PROFILE_LIMIT_BYTES} bytes)"
            )
        entry = manifest.image_entry(name, family, scenario, path)
        entries.append(entry)
        print(f"   ok: {size} bytes, sha256={entry['sha256']}", file=sys.stderr)

    if shutil.which("ewfacquire"):
        try:
            _emit_e01(images_dir / "hiksim_format.img", images_dir / "hiksim_format")
            print("== emitted hiksim_format.E01 ==", file=sys.stderr)
        except subprocess.CalledProcessError as exc:
            print(
                f"ewfacquire failed (non-fatal, .img is still the source of truth): {exc.stderr}",
                file=sys.stderr,
            )
    else:
        print(
            "ewfacquire not found — skipping hiksim_format.E01 "
            "(fallback: .img only; see docs/progress/Q1.md 'Fallbacks used').",
            file=sys.stderr,
        )

    manifest.write_manifest(manifest_path, profile, entries, generated_at_s=time.time())
    print(f"== wrote {manifest_path} ({len(entries)} images) ==", file=sys.stderr)
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pramaan-synthdvr")
    sub = parser.add_subparsers(dest="command", required=True)

    build_all_p = sub.add_parser("build-all", help="build the whole owned corpus")
    build_all_p.add_argument("profile", nargs="?", default="small")

    args = parser.parse_args(argv)
    if args.command == "build-all":
        if args.profile != "small":
            print(
                f"profile {args.profile!r} requested, but Q1 only implements 'small' "
                "(the ~13 GiB free disk budget rules out 'full' on this machine); "
                "building 'small' instead.",
                file=sys.stderr,
            )
        build_all(profile="small")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
