"""PAdES signing with a lab TEST certificate (docs/02-BACKEND.md §9 step 3).

PAdES/CMS tooling (pyHanko) expects an X.509-wrapped signing key, which
``pramaan_custody``'s raw Ed25519 keys are not — rather than bend the
custody module's key format to fit a PDF-signing library (risking breaking
its own, already-tested Ed25519 signature format used for the audit chain
and anchors), this module generates and caches its own dedicated RSA-2048
key + self-signed X.509 certificate, clearly labelled as a lab TEST
certificate, the same way ``pramaan_custody.keys.load_or_create_keypair``
caches an Ed25519 key: generated once, reused after. Validity dates are a
fixed range (not "now"), so the certificate's own content never depends on
wall-clock time (CLAUDE.md rule 5) — only the PAdES signature's own signing
time (outside any content hash here) is wall-clock.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

#: Deliberately not "now" — a fixed validity window keeps the certificate's
#: own bytes deterministic across regenerations, and is a clear, honest
#: marker that this is a lab test artefact, not a CA-issued production cert.
NOT_VALID_BEFORE = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
NOT_VALID_AFTER = datetime.datetime(2035, 1, 1, tzinfo=datetime.UTC)

CERT_SUBJECT_CN = "Pramaan Lab TEST Certificate (SYNTHETIC)"
CERT_ORG = "Pramaan Forensic Lab — TEST, not for production use"


def _key_cert_paths(keys_dir: Path) -> tuple[Path, Path]:
    return keys_dir / "lab_pdf_signing.key.pem", keys_dir / "lab_pdf_signing.cert.pem"


def load_or_create_lab_pdf_cert(keys_dir: Path) -> tuple[Path, Path]:
    """Return ``(key_path, cert_path)`` for the lab's PDF-signing RSA key +
    self-signed X.509 certificate under ``keys_dir``, generating them (mode
    600 for the key) on first use and reusing them after.
    """
    keys_dir.mkdir(parents=True, exist_ok=True)
    key_path, cert_path = _key_cert_paths(keys_dir)
    if key_path.exists() and cert_path.exists():
        return key_path, cert_path

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, CERT_SUBJECT_CN),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, CERT_ORG),
            x509.NameAttribute(NameOID.COUNTRY_NAME, "IN"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(1)
        .not_valid_before(NOT_VALID_BEFORE)
        .not_valid_after(NOT_VALID_AFTER)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )

    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)

    fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, key_pem)
    finally:
        os.close(fd)
    cert_path.write_bytes(cert_pem)
    return key_path, cert_path


def sign_pdf(
    pdf_bytes: bytes,
    key_path: Path,
    cert_path: Path,
    *,
    field_name: str = "PramaanLabSignature",
) -> bytes:
    """PAdES-signs ``pdf_bytes`` in place (incremental update), returning the
    signed PDF bytes. Signing time is added by pyHanko's own signing
    machinery (wall-clock, outside any manifest/report content hash — see
    module docstring and docs/02-BACKEND.md §9 step 3: "signing time is
    outside the manifest hash").
    """
    import io

    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers

    # pyhanko ships no py.typed marker (root pyproject.toml's mypy override
    # silences the missing-stubs error but its plain, unannotated defs still
    # trip `no-untyped-call`/`no-any-return` in --strict mode) — both are
    # narrowly suppressed here rather than loosening strictness repo-wide.
    signer = signers.SimpleSigner.load(str(key_path), str(cert_path))  # type: ignore[no-untyped-call]
    writer = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes))
    out = signers.sign_pdf(
        writer,
        signers.PdfSignatureMetadata(
            field_name=field_name,
            reason="Pramaan lab forensic report — TEST certificate, see certificate section.",
        ),
        signer=signer,
    )
    return bytes(out.getvalue())
