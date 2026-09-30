/**
 * Verify drop zone: upload an exported MP4 to `POST /exports/verify` and show what the server
 * found. The page's primary action is still "Create signed export" — this zone's own "Verify
 * export" button is a contained secondary action (same visual-weight convention as F3b's
 * self-contained SHA recompute strip: a tinted result panel, no competing filled button).
 *
 * Two independent facts are reported and never merged into one badge:
 *   1. signature validity  -> IntegrityChip `verified` | `mismatch`
 *   2. source image match  -> does the manifest's source hash equal a registered evidence image
 * A signature can be valid while the source is unregistered; the headline says exactly which.
 */
import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { FileCheck2, Loader2, ShieldAlert, ShieldCheck, ShieldQuestion, UploadCloud } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { IntegrityChip } from "@/components/signature/integrity-chip";
import { api } from "@/api/client";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { components } from "@/api/schema.gen";
import { apiErrorMessage } from "./lib/csrf";

type VerifyResult = components["schemas"]["ExportVerifyResult"];

const MAX_HASH_BYTES = 256 * 1024 * 1024;

async function sha256OfFile(file: File): Promise<string | null> {
  const subtle = typeof crypto !== "undefined" ? crypto.subtle : undefined;
  if (!subtle || file.size > MAX_HASH_BYTES) return null;
  try {
    const digest = await subtle.digest("SHA-256", await file.arrayBuffer());
    return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    return null;
  }
}

async function verifyFile(file: File): Promise<{ result: VerifyResult; fileSha256: string | null }> {
  const formData = new FormData();
  formData.append("file", file, file.name);
  // openapi-fetch passes a FormData body through untouched and lets the browser set the multipart
  // boundary (its defaultBodySerializer). The generated request type says `{ file: string }`
  // (the OpenAPI `binary` format is rendered as `string`), so we hand it a placeholder `body`
  // to satisfy the type and supply the real FormData via `bodySerializer`.
  const [{ data, error }, fileSha256] = await Promise.all([
    api.POST("/api/exports/verify", { body: { file: "" }, bodySerializer: () => formData }),
    sha256OfFile(file),
  ]);
  if (!data) throw new Error(apiErrorMessage(error, "The server could not verify this file."));
  return { result: data, fileSha256 };
}

export function VerifyZone() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [extraIgnored, setExtraIgnored] = useState(false);

  const verifyMutation = useMutation({ mutationFn: verifyFile });

  function choose(files: FileList | null) {
    const first = files?.[0] ?? null;
    if (!first) return;
    setExtraIgnored((files?.length ?? 0) > 1);
    setFile(first);
    verifyMutation.reset();
  }

  return (
    <div className="flex flex-col gap-4" data-testid="verify-zone">
      <div>
        <h2 className="text-section text-text">Verify an export</h2>
        <p className="mt-0.5 text-sm text-text-2">
          Drop an exported MP4 to check its signature and whether its source image is registered here.
        </p>
      </div>

      <label
        htmlFor="export-verify-file"
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragEnter={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          choose(e.dataTransfer.files);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center gap-2 rounded-[var(--radius-card)] border border-dashed px-4 py-6 text-center transition-colors duration-[var(--dur-fast)]",
          "focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-[var(--brand-500)]",
          dragging ? "border-[var(--brand-500)] bg-[var(--selected)]" : "border-line-strong bg-panel hover:bg-control",
        )}
      >
        <input
          ref={inputRef}
          id="export-verify-file"
          type="file"
          className="sr-only"
          aria-label="Export file to verify"
          onChange={(e) => {
            choose(e.target.files);
            e.target.value = ""; // allow re-selecting the same file
          }}
        />
        {file ? <FileCheck2 size={22} strokeWidth={1.5} className="text-accent-text" aria-hidden /> : <UploadCloud size={22} strokeWidth={1.5} className="text-text-3" aria-hidden />}
        {file ? (
          <>
            <span className="max-w-full truncate font-data text-sm text-text" data-testid="verify-file-name">
              {file.name}
            </span>
            <span className="font-data text-caption tabular-nums text-text-3">{formatBytes(file.size)} — click or drop to choose a different file</span>
          </>
        ) : (
          <>
            <span className="text-base font-medium text-text">Drop an export here, or click to choose</span>
            <span className="text-caption text-text-3">One file. It is uploaded to the server for verification and is not stored.</span>
          </>
        )}
        {extraIgnored && <span className="text-caption text-warn">Only the first file was used.</span>}
      </label>

      <div className="flex justify-end">
        <Button
          type="button"
          variant="secondary"
          disabled={!file || verifyMutation.isPending}
          onClick={() => file && verifyMutation.mutate(file)}
        >
          {verifyMutation.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <ShieldCheck aria-hidden />}
          {verifyMutation.isPending ? "Verifying…" : "Verify export"}
        </Button>
      </div>

      <div aria-live="polite" aria-busy={verifyMutation.isPending}>
        {verifyMutation.isPending && (
          <div className="flex items-center gap-3 rounded-[var(--radius-card)] border border-line bg-panel p-3">
            <Loader2 size={18} strokeWidth={1.75} className="shrink-0 animate-spin text-text-3" aria-hidden />
            <p className="text-base text-text-2">Checking signature and source hash…</p>
          </div>
        )}
        {verifyMutation.isError && (
          <div role="alert" className="flex items-start gap-3 rounded-[var(--radius-card)] border border-line-strong bg-panel p-3">
            <ShieldQuestion size={18} strokeWidth={1.75} className="mt-0.5 shrink-0 text-text-3" aria-hidden />
            <div>
              <p className="text-base font-medium text-text">Verification could not be completed</p>
              <p className="mt-0.5 text-sm text-text-2">
                {verifyMutation.error instanceof Error ? verifyMutation.error.message : "Unknown error."} This is not a verdict on the file — try again.
              </p>
            </div>
          </div>
        )}
        {verifyMutation.isSuccess && <VerifyResultPanel result={verifyMutation.data.result} fileSha256={verifyMutation.data.fileSha256} />}
      </div>
    </div>
  );
}

const HASH_RE = /^[0-9a-f]{32,128}$/i;

function VerifyResultPanel({ result, fileSha256 }: { result: VerifyResult; fileSha256: string | null }) {
  const sigOk = result.signature_valid;
  const srcOk = result.source_matches_registered_evidence;
  const manifest = { ...result.manifest };
  const notes = Array.isArray(manifest._verification_notes) ? (manifest._verification_notes as unknown[]).map(String) : [];
  delete manifest._verification_notes;
  const claimedSource = typeof manifest.source_sha256 === "string" ? manifest.source_sha256 : null;

  const tone = !sigOk ? "danger" : srcOk ? "ok" : "warn";
  const headline = !sigOk
    ? "Signature invalid — do not rely on this file"
    : srcOk
      ? "Signature valid — source image is registered"
      : "Signature valid — but the source image is not registered here";

  return (
    <div
      data-testid="verify-result"
      data-signature-valid={String(sigOk)}
      data-source-matches={String(srcOk)}
      className={cn(
        "flex flex-col gap-3 rounded-[var(--radius-card)] border p-3",
        tone === "ok" && "border-[color-mix(in_oklab,var(--ok)_40%,transparent)] bg-[var(--ok-tint)]",
        tone === "warn" && "border-[color-mix(in_oklab,var(--warn)_40%,transparent)] bg-[var(--warn-tint)]",
        tone === "danger" && "border-[color-mix(in_oklab,var(--danger)_45%,transparent)] bg-[var(--danger-tint)]",
      )}
    >
      <div className="flex items-center gap-2.5">
        {tone === "ok" ? (
          <ShieldCheck size={18} strokeWidth={1.75} className="shrink-0 text-ok" aria-hidden />
        ) : (
          <ShieldAlert size={18} strokeWidth={1.75} className={cn("shrink-0", tone === "danger" ? "text-danger" : "text-warn")} aria-hidden />
        )}
        <p className="text-base font-medium text-text">{headline}</p>
      </div>

      <dl className="flex flex-col gap-2">
        <FactRow
          label="Signature"
          testId="fact-signature"
          caption={sigOk ? "The manifest signature verifies against a known examiner key." : "The manifest signature does not verify. The file was altered or is not a Pramaan export."}
        >
          {fileSha256 ? (
            <IntegrityChip state={sigOk ? "verified" : "mismatch"} hash={fileSha256} />
          ) : (
            <Badge variant={sigOk ? "ok" : "danger"}>{sigOk ? "verified" : "mismatch"}</Badge>
          )}
        </FactRow>
        <FactRow
          label="Source image"
          testId="fact-source"
          caption={
            srcOk
              ? "The manifest's source SHA-256 equals a registered evidence image."
              : sigOk
                ? "No registered evidence image has this source SHA-256. The export is authentic but its source is not in this system."
                : "No registered evidence image matches. This hash is unauthenticated because the signature is invalid."
          }
        >
          {claimedSource ? (
            <IntegrityChip state={srcOk ? "verified" : "mismatch"} hash={claimedSource} />
          ) : (
            <Badge variant="danger">no source hash reported</Badge>
          )}
        </FactRow>
      </dl>
      {fileSha256 && <p className="-mt-1 text-caption text-text-3">Signature chip hash is the SHA-256 of the file you uploaded, computed in your browser.</p>}

      {notes.length > 0 && (
        <ul className="list-disc pl-5 text-sm text-text-2">
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}

      <ManifestRows manifest={manifest} untrusted={!sigOk} />
    </div>
  );
}

function FactRow({ label, caption, testId, children }: { label: string; caption: string; testId: string; children: React.ReactNode }) {
  return (
    <div data-testid={testId} className="flex flex-col gap-1 rounded-[var(--radius-control)] border border-line bg-panel px-2.5 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <dt className="text-label text-text-3">{label}</dt>
        <dd className="min-w-0">{children}</dd>
      </div>
      <p className="text-caption text-text-2">{caption}</p>
    </div>
  );
}

function ManifestRows({ manifest, untrusted }: { manifest: Record<string, unknown>; untrusted: boolean }) {
  const keys = Object.keys(manifest).sort();
  if (keys.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <h3 className="text-label text-text-3">
        Manifest{untrusted ? " (unauthenticated — signature invalid)" : ""}
      </h3>
      <dl className="grid grid-cols-[minmax(0,10rem)_1fr] gap-x-3 gap-y-1.5 rounded-[var(--radius-control)] border border-line bg-panel p-2.5 text-sm max-sm:grid-cols-1">
        {keys.map((k) => (
          <ManifestRow key={k} name={k} value={manifest[k]} />
        ))}
      </dl>
    </div>
  );
}

function ManifestRow({ name, value }: { name: string; value: unknown }) {
  return (
    <>
      <dt className="break-words font-data text-text-3">{name}</dt>
      <dd className="min-w-0 text-text">
        <ManifestValue value={value} />
      </dd>
    </>
  );
}

function ManifestValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-text-3">null</span>;
  if (typeof value === "string") {
    return HASH_RE.test(value) ? <span className="break-all font-data text-caption">{value}</span> : <span className="break-words">{value}</span>;
  }
  if (typeof value === "number") return <span className="font-data tabular-nums">{value.toLocaleString("en-US")}</span>;
  if (typeof value === "boolean") return <span className="font-data">{String(value)}</span>;
  const json = JSON.stringify(value);
  if (Array.isArray(value) && json.length > 80) {
    return (
      <details>
        <summary className="cursor-pointer text-text-2">{value.length} entries</summary>
        <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all font-data text-caption text-text-2">{JSON.stringify(value, null, 1)}</pre>
      </details>
    );
  }
  return <span className="break-all font-data text-caption">{json}</span>;
}
