/**
 * Live SHA-256 recompute (docs/04-FRONTEND.md §5 route table: "live SHA-256 recompute with the
 * one-cycle check animation"). Hashes the payload bytes the server returned using the browser's
 * own SubtleCrypto — not trusting the server's claim, computing it independently — and compares
 * against `payload_sha256_stored`. BRAND.md §6's "signature moment": on verifying, the chip draws
 * a one-cycle checkmark stroke and settles to teal; on mismatch it settles to the danger colour,
 * just as plainly labelled, never softened.
 */
import { useEffect, useRef, useState } from "react";
import { Copy, Loader2, ShieldAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { shortHash } from "@/lib/format";
import { base64ToBytes, bytesToHexDigest, sliceAnnotation, type RawAnnotation } from "../lib/hex-annotate";

export type ShaState = "computing" | "verified" | "mismatch" | "unavailable";

export function ShaRecompute({
  frameId,
  bytesB64,
  payloadAnnotation,
  storedHash,
  className,
}: {
  frameId: string;
  bytesB64: string;
  payloadAnnotation: RawAnnotation;
  storedHash: string;
  className?: string;
}) {
  const [state, setState] = useState<ShaState>("computing");
  const [recomputed, setRecomputed] = useState<string | null>(null);
  const reduceMotion = usePrefersReducedMotion();

  useEffect(() => {
    let cancelled = false;
    setState("computing");
    setRecomputed(null);

    const subtle = typeof crypto !== "undefined" ? crypto.subtle : undefined;
    if (!subtle) {
      setState("unavailable");
      return;
    }

    const bytes = base64ToBytes(bytesB64);
    const payload = sliceAnnotation(bytes, payloadAnnotation);
    // A copy is required: SubtleCrypto.digest needs an ArrayBuffer-backed view whose buffer it
    // can read without the caller mutating it mid-computation, and `payload` is a subarray view
    // into a larger buffer we don't want to hand out.
    const payloadCopy = payload.slice();

    (async () => {
      const [digestBuf] = await Promise.all([
        // See prove-handlers.ts's sha256Hex for why this cast is needed under TS's DOM lib types.
        subtle.digest("SHA-256", payloadCopy as unknown as BufferSource),
        // Perceivable "recomputing" moment even though a few KB hashes near-instantly — honours
        // reduced-motion by skipping the artificial delay entirely.
        reduceMotion ? Promise.resolve() : new Promise((r) => setTimeout(r, 480)),
      ]);
      if (cancelled) return;
      const hex = bytesToHexDigest(digestBuf);
      setRecomputed(hex);
      setState(hex === storedHash ? "verified" : "mismatch");
    })().catch(() => {
      if (!cancelled) setState("unavailable");
    });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frameId, bytesB64, payloadAnnotation.offset, payloadAnnotation.length, storedHash]);

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-3 rounded-[var(--radius-card)] border p-3 transition-colors duration-[var(--dur-base)] ease-[var(--ease)]",
        state === "verified" && "border-[color-mix(in_oklab,var(--ok)_40%,transparent)] bg-[var(--ok-tint)]",
        state === "mismatch" && "border-[color-mix(in_oklab,var(--danger)_45%,transparent)] bg-[var(--danger-tint)]",
        (state === "computing" || state === "unavailable") && "border-line bg-panel",
        className,
      )}
    >
      <StateGlyph state={state} />
      <div className="min-w-0 flex-1">
        <p className="text-base font-medium text-text">
          {state === "computing" && "Recomputing SHA-256 from bytes on disk…"}
          {state === "verified" && "Verified — recomputed hash matches the stored claim"}
          {state === "mismatch" && "Mismatch — recomputed hash does not match the stored claim"}
          {state === "unavailable" && "Recompute unavailable in this browser context"}
        </p>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-3 truncate font-data text-caption text-text-2">
          {recomputed && <span>sha256 {shortHash(recomputed)}</span>}
          <span>stored {shortHash(storedHash)}</span>
        </p>
      </div>
      {recomputed && (
        <button
          type="button"
          onClick={() => void navigator.clipboard?.writeText(recomputed).catch(() => undefined)}
          aria-label="Copy recomputed hash"
          className="focus-ring rounded p-1 text-text-3 hover:bg-[var(--ink-600)] hover:text-text"
        >
          <Copy size={13} strokeWidth={1.75} />
        </button>
      )}
    </div>
  );
}

function StateGlyph({ state }: { state: ShaState }) {
  if (state === "computing") {
    return <Loader2 size={18} strokeWidth={1.75} className="shrink-0 animate-spin text-text-3" aria-hidden />;
  }
  if (state === "mismatch") {
    return <ShieldAlert size={18} strokeWidth={1.75} className="shrink-0 text-danger" aria-hidden />;
  }
  if (state === "unavailable") {
    return <ShieldAlert size={18} strokeWidth={1.75} className="shrink-0 text-text-3" aria-hidden />;
  }
  // verified: an explicit inline SVG so the one-cycle checkmark stroke (BRAND.md §6) actually
  // draws, rather than a static icon swap.
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="shrink-0" aria-hidden>
      <circle cx="12" cy="12" r="10" className="text-ok" stroke="currentColor" strokeWidth="1.5" opacity="0.35" />
      <path
        d="M7 12.5l3.2 3.2L17 9"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="integrity-check-draw text-ok"
      />
    </svg>
  );
}

function usePrefersReducedMotion(): boolean {
  const ref = useRef(false);
  const [, setTick] = useState(0);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    ref.current = mq.matches;
    setTick((t) => t + 1);
    const onChange = () => setTick((t) => t + 1);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return ref.current;
}
