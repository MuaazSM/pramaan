"""High-level report build orchestration (docs/02-BACKEND.md §9).

Wires together ``manifest`` → ``certificate``/``appendix`` → ``render`` →
``pdf`` → ``signing`` into the one function ``apps/api``'s real-mode report
store calls. Kept a thin, pure-orchestration layer over the other modules
so each of those stays independently unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pramaan_reporting.appendix import build_hash_appendix
from pramaan_reporting.certificate import build_certificate_data
from pramaan_reporting.manifest import (
    ManifestInputs,
    build_manifest,
    manifest_bytes,
    report_id,
    report_sha256,
)
from pramaan_reporting.pdf import PdfBackend, html_to_pdf
from pramaan_reporting.render import render_certificate_html, render_report_html
from pramaan_reporting.signing import load_or_create_lab_pdf_cert, sign_pdf


@dataclass(frozen=True)
class ReportArtifacts:
    report_id: str
    report_sha256: str
    manifest: dict[str, Any]
    manifest_json: bytes
    certificate: dict[str, Any]
    pdf_bytes: bytes
    certificate_pdf_bytes: bytes
    pdf_backend: PdfBackend


def build_report(
    inputs: ManifestInputs,
    *,
    keys_dir: Path,
    generated_utc: str,
    thumbnails: list[dict[str, Any]] | None = None,
) -> ReportArtifacts:
    """Build the full set of report artefacts for one case snapshot.

    Determinism (CLAUDE.md rule 5): ``manifest``/``manifest_json``/
    ``report_sha256``/``report_id`` depend only on ``inputs`` — calling this
    twice with logically-identical inputs (any dict/list ordering) produces
    byte-identical manifest bytes and the same report id/hash. The rendered
    PDF bytes are *not* guaranteed byte-identical across runs (the PAdES
    signature embeds a wall-clock signing time by design — docs/02-BACKEND.md
    §9 step 3: "signing time is outside the manifest hash"), but the
    manifest they were built from is reproducible and independently
    re-hashable from the PDF's own embedded/appendix content.
    """
    manifest = build_manifest(inputs)
    m_bytes = manifest_bytes(manifest)
    sha256 = report_sha256(manifest)
    rid = report_id(sha256)

    envelope = {
        "report_id": rid,
        "case_id": inputs.case.get("id"),
        "generated_utc": generated_utc,
        "report_sha256": sha256,
    }
    certificate = build_certificate_data(manifest)
    appendix = build_hash_appendix(manifest, sha256)

    report_html = render_report_html(
        {
            "manifest": manifest,
            "envelope": envelope,
            "certificate": certificate,
            "appendix": appendix,
            "thumbnails": thumbnails or [],
        }
    )
    certificate_html = render_certificate_html({"envelope": envelope, "certificate": certificate})

    pdf_bytes, backend = html_to_pdf(report_html)
    certificate_pdf_bytes, cert_backend = html_to_pdf(certificate_html)

    key_path, cert_path = load_or_create_lab_pdf_cert(keys_dir)
    signed_pdf = sign_pdf(pdf_bytes, key_path, cert_path, field_name="PramaanReportSignature")
    signed_certificate_pdf = sign_pdf(
        certificate_pdf_bytes, key_path, cert_path, field_name="PramaanCertificateSignature"
    )

    return ReportArtifacts(
        report_id=rid,
        report_sha256=sha256,
        manifest=manifest,
        manifest_json=m_bytes,
        certificate=certificate,
        pdf_bytes=signed_pdf,
        certificate_pdf_bytes=signed_certificate_pdf,
        pdf_backend=backend if backend == cert_backend else backend,
    )
