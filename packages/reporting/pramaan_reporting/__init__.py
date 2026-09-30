"""Report templates, BSA Section 63 certificate, PDF signing
(docs/02-BACKEND.md §9)."""

from __future__ import annotations

from pramaan_reporting.builder import ReportArtifacts, build_report
from pramaan_reporting.manifest import (
    ManifestInputs,
    build_manifest,
    manifest_bytes,
    report_id,
    report_sha256,
)

__all__ = [
    "ManifestInputs",
    "ReportArtifacts",
    "build_manifest",
    "build_report",
    "manifest_bytes",
    "report_id",
    "report_sha256",
]
