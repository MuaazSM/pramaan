/**
 * Custody screen body — hash-chain audit timeline, chain verification, and Merkle anchors.
 * Composed of three panels: VerifyPanel (the primary action, "Re-verify chain"), AnchorsPanel
 * (list + create), and AuditTimeline (cursor-paginated, Sentry-breadcrumb-style rail).
 * Contracts: GET /cases/{cid}/audit, GET /cases/{cid}/audit/verify, GET/POST /cases/{cid}/anchors.
 */
import { useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Anchor as AnchorIcon, Check, Copy, Loader2, RefreshCw, ScrollText, ShieldAlert, ShieldCheck } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { IntegrityChip, type IntegrityState } from "@/components/signature/integrity-chip";
import { QueryErrorState } from "@/components/shell/query-error-state";
import { api } from "@/api/client";
import { errorFromResponse } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import { formatTimecode, shortHash } from "@/lib/format";
import type { components } from "@/api/schema.gen";

type AuditEntry = components["schemas"]["AuditEntry"];
type Anchor = components["schemas"]["Anchor"];
type AnchorBackend = NonNullable<components["schemas"]["AnchorCreate"]["backend"]>;

const PAGE_SIZE = 25;

/** Real-mode mutating routes need the double-submit CSRF header (docs/02-BACKEND.md §11); the
 * shared client doesn't add it. Returns `{}` when the cookie is absent (mock/stub mode). */
function csrfHeaders(): Record<string, string> {
  const cookie = typeof document !== "undefined" ? document.cookie : "";
  const match = /(?:^|;\s*)pramaan_csrf=([^;]+)/.exec(cookie);
  return match ? { "X-CSRF-Token": decodeURIComponent(match[1]) } : {};
}

/** Pull `{ error: { code, message } }` out of a non-2xx body (the API's uniform error envelope). */
function describeError(status: number, body: unknown): string {
  const err = (body as { error?: { code?: string; message?: string } } | undefined)?.error;
  const code = err?.code ?? `http_${status}`;
  const message = err?.message ?? "The request failed.";
  return `${message} (${status} ${code})`;
}

export function CustodyScreen({ caseId }: { caseId: string }) {
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-5 p-6">
      <div>
        <h1 className="text-page-title text-text">Custody</h1>
        <p className="mt-1 text-base text-text-2">
          Every action on this case is an entry in a hash-chained, Ed25519-signed log. Verification recomputes the chain; anchors
          commit a Merkle root of it.
        </p>
      </div>
      <VerifyPanel caseId={caseId} />
      <AnchorsPanel caseId={caseId} />
      <AuditTimeline caseId={caseId} />
    </div>
  );
}

/* -------------------------------------------------------------------------------------------- */
/* Chain verification                                                                           */
/* -------------------------------------------------------------------------------------------- */

function useVerify(caseId: string) {
  // Same query key as ScreenShell's custody-seal query, so re-verifying here also refreshes the footer strip.
  return useQuery({
    queryKey: ["audit-verify", caseId],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/cases/{cid}/audit/verify", { params: { path: { cid: caseId } } });
      if (error) throw errorFromResponse(response, "the chain verification result could not be loaded");
      return data ?? null;
    },
  });
}

function VerifyPanel({ caseId }: { caseId: string }) {
  const verify = useVerify(caseId);
  const result = verify.data;

  return (
    <section aria-labelledby="verify-heading" className="rounded-[var(--radius-panel)] border border-line bg-panel p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span
            className={cn(
              "flex size-9 items-center justify-center rounded-[var(--radius-card)] border",
              !result
                ? "border-line-strong bg-control"
                : result.ok
                  ? "border-[color-mix(in_oklab,var(--ok)_40%,transparent)] bg-[var(--ok-tint)]"
                  : "border-[color-mix(in_oklab,var(--danger)_40%,transparent)] bg-[var(--danger-tint)]",
            )}
          >
            {!result ? (
              <Loader2 size={16} strokeWidth={1.75} className="animate-spin text-text-3" />
            ) : result.ok ? (
              <ShieldCheck size={16} strokeWidth={1.75} className="text-ok" />
            ) : (
              <ShieldAlert size={16} strokeWidth={1.75} className="text-danger" />
            )}
          </span>
          <div>
            <h2 id="verify-heading" className="text-section text-text">
              Chain verification
            </h2>
            <p className="text-sm text-text-2">
              Recomputes every entry hash, link and signature on the server. Read-only — re-verifying changes nothing.
            </p>
          </div>
        </div>
        <Button onClick={() => void verify.refetch()} disabled={verify.isFetching}>
          <RefreshCw size={14} strokeWidth={1.75} className={cn(verify.isFetching && "animate-spin")} />
          Re-verify chain
        </Button>
      </div>

      <div className="mt-4" aria-live="polite">
        {verify.isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : verify.isError || !result ? (
          <QueryErrorState error={verify.error} subject="the chain verification result" className="py-4" />
        ) : (
          <div data-testid="verify-result" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Result">
              {result.ok ? <Badge variant="ok">chain ok</Badge> : <Badge variant="danger">chain broken</Badge>}
            </Stat>
            <Stat label="Entries">
              <span className="font-data tabular-nums text-text">{result.length.toLocaleString()}</span>
            </Stat>
            <Stat label="Head hash" wide>
              {result.head_hash ? (
                <IntegrityChip state={result.ok ? "verified" : "mismatch"} hash={result.head_hash} />
              ) : (
                <span className="text-sm text-text-3">empty chain</span>
              )}
            </Stat>
            {!result.ok && result.first_bad_seq != null && (
              <Stat label="First bad entry">
                <span className="font-data tabular-nums text-danger">#{result.first_bad_seq}</span>
              </Stat>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function Stat({ label, children, wide }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={cn("flex flex-col gap-1", wide && "col-span-2")}>
      <span className="text-label text-text-3">{label}</span>
      <div className="flex min-h-6 items-center">{children}</div>
    </div>
  );
}

/* -------------------------------------------------------------------------------------------- */
/* Anchors                                                                                       */
/* -------------------------------------------------------------------------------------------- */

function AnchorsPanel({ caseId }: { caseId: string }) {
  const qc = useQueryClient();
  const [backend, setBackend] = useState<AnchorBackend>("local");

  const anchors = useQuery({
    queryKey: ["anchors", caseId],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/cases/{cid}/anchors", { params: { path: { cid: caseId } } });
      if (error) throw errorFromResponse(response, "anchors could not be loaded");
      return data ?? [];
    },
  });

  const create = useMutation({
    mutationFn: async (chosen: AnchorBackend) => {
      const { data, error, response } = await api.POST("/api/cases/{cid}/anchors", {
        params: { path: { cid: caseId } },
        body: { backend: chosen },
        headers: csrfHeaders(),
      });
      if (!response.ok || !data) throw new Error(describeError(response.status, error));
      return data;
    },
    onSuccess: () => {
      // Creating an anchor appends an `anchor.created` audit entry in real mode, so refresh all three.
      void qc.invalidateQueries({ queryKey: ["anchors", caseId] });
      void qc.invalidateQueries({ queryKey: ["audit", caseId] });
      void qc.invalidateQueries({ queryKey: ["audit-verify", caseId] });
    },
  });

  const sorted = [...(anchors.data ?? [])].sort((a, b) => b.to_seq - a.to_seq || b.ts_utc.localeCompare(a.ts_utc));

  return (
    <section aria-labelledby="anchors-heading" className="rounded-[var(--radius-panel)] border border-line bg-panel p-5">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-[var(--radius-card)] border border-line-strong bg-control">
            <AnchorIcon size={16} strokeWidth={1.75} className="text-text-2" />
          </span>
          <div>
            <h2 id="anchors-heading" className="text-section text-text">
              Anchors
            </h2>
            <p className="text-sm text-text-2">Merkle root over entry hashes, signed with the lab key.</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Select value={backend} onValueChange={(v) => setBackend(v as AnchorBackend)}>
            <SelectTrigger className="w-44" aria-label="Anchor backend">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="local">Local ledger</SelectItem>
              <SelectItem value="fabric">Fabric (interface only)</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="secondary" onClick={() => create.mutate(backend)} disabled={create.isPending}>
            {create.isPending ? <Loader2 size={14} className="animate-spin" /> : <AnchorIcon size={14} strokeWidth={1.75} />}
            Create anchor
          </Button>
        </div>
      </div>

      {create.isError && (
        <p
          role="alert"
          data-testid="anchor-error"
          className="mb-3 rounded-[var(--radius-card)] border border-[color-mix(in_oklab,var(--danger)_40%,transparent)] bg-[var(--danger-tint)] p-3 text-sm text-danger"
        >
          Anchor not created. {create.error instanceof Error ? create.error.message : "Unknown error."}
        </p>
      )}
      {create.isSuccess && !create.isPending && (
        <p role="status" className="mb-3 flex items-center gap-1.5 text-sm text-ok">
          <Check size={12} strokeWidth={2} /> {create.data.backend} anchor created over entries #{create.data.from_seq}–#{create.data.to_seq}.
        </p>
      )}

      {anchors.isLoading ? (
        <Skeleton className="h-20 w-full" />
      ) : anchors.isError ? (
        <QueryErrorState error={anchors.error} subject="anchors" onRetry={() => void anchors.refetch()} className="py-4" />
      ) : sorted.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-[var(--radius-card)] border border-dashed border-line-strong py-8 text-center">
          <AnchorIcon size={22} strokeWidth={1.5} className="text-text-3" />
          <p className="text-base text-text-2">No anchors yet. Create one to commit the current chain head.</p>
        </div>
      ) : (
        <ul data-testid="anchor-list" className="flex flex-col gap-2">
          {sorted.map((a) => (
            <AnchorRow key={a.id} anchor={a} />
          ))}
        </ul>
      )}
    </section>
  );
}

function AnchorRow({ anchor }: { anchor: Anchor }) {
  return (
    <li
      data-testid="anchor-row"
      className="grid gap-x-4 gap-y-2 rounded-[var(--radius-card)] border border-line bg-card p-3 text-sm sm:grid-cols-[1fr_auto]"
    >
      <div className="flex min-w-0 flex-col gap-1.5">
        <div className="flex items-center gap-2">
          <Badge variant={anchor.backend === "fabric" ? "brand" : "neutral"}>{anchor.backend}</Badge>
          <span className="font-data tabular-nums text-text-2">
            entries #{anchor.from_seq}–#{anchor.to_seq}
          </span>
        </div>
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="shrink-0 text-text-3">merkle root</span>
          <CopyMono value={anchor.merkle_root} label="Copy Merkle root" />
        </div>
      </div>
      <div className="flex flex-col gap-1.5 sm:items-end">
        <span className="font-data tabular-nums text-text-2">{formatTimecode(anchor.ts_utc)}</span>
        <span className="flex items-center gap-1.5">
          <span className="text-text-3">lab sig</span>
          <span className="font-data text-text-2" title={anchor.lab_signature}>
            {shortHash(anchor.lab_signature)}
          </span>
        </span>
      </div>
    </li>
  );
}

/** Plain mono value + copy button. Deliberately not `IntegrityChip`: a Merkle root is not a payload hash, so it has no verified/mismatch state. */
function CopyMono({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      // clipboard unavailable (insecure context / headless) — no-op
    }
  }
  return (
    <span className="inline-flex min-w-0 items-center gap-1 rounded-full border border-line-strong bg-control px-2 py-1">
      <span className="truncate font-data text-text" title={value}>
        {value}
      </span>
      <button
        type="button"
        onClick={() => void copy()}
        aria-label={label}
        className="focus-ring shrink-0 rounded p-0.5 text-text-3 hover:bg-[var(--ink-600)] hover:text-text"
      >
        {copied ? <Check size={11} strokeWidth={1.75} className="text-ok" /> : <Copy size={11} strokeWidth={1.75} />}
      </button>
    </span>
  );
}

/* -------------------------------------------------------------------------------------------- */
/* Audit timeline                                                                                */
/* -------------------------------------------------------------------------------------------- */

function AuditTimeline({ caseId }: { caseId: string }) {
  const verify = useVerify(caseId);
  const audit = useInfiniteQuery({
    queryKey: ["audit", caseId],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) => {
      const { data, error, response } = await api.GET("/api/cases/{cid}/audit", {
        params: { path: { cid: caseId }, query: { cursor: pageParam, limit: PAGE_SIZE } },
      });
      if (!response.ok || !data) throw new Error(describeError(response.status, error));
      return data;
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const entries = audit.data?.pages.flatMap((p) => p.items) ?? [];
  const v = verify.data;

  function stateFor(seq: number): IntegrityState {
    if (!v) return "pending";
    if (!v.ok && v.first_bad_seq != null && seq >= v.first_bad_seq) return "mismatch";
    return v.ok ? "verified" : "pending";
  }

  return (
    <section aria-labelledby="audit-heading" className="rounded-[var(--radius-panel)] border border-line bg-panel p-5">
      <div className="mb-4 flex items-center gap-2.5">
        <span className="flex size-9 items-center justify-center rounded-[var(--radius-card)] border border-line-strong bg-control">
          <ScrollText size={16} strokeWidth={1.75} className="text-text-2" />
        </span>
        <div>
          <h2 id="audit-heading" className="text-section text-text">
            Audit log
          </h2>
          <p className="text-sm text-text-2">
            Chain order, oldest first.
            {v && ` Showing ${entries.length.toLocaleString()} of ${v.length.toLocaleString()} entries.`}
          </p>
        </div>
      </div>

      {audit.isLoading ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      ) : audit.isError ? (
        <p role="alert" className="text-sm text-danger">
          Could not load the audit log.{" "}
          <button type="button" className="focus-ring underline" onClick={() => void audit.refetch()}>
            Retry
          </button>
        </p>
      ) : entries.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-[var(--radius-card)] border border-dashed border-line-strong py-10 text-center">
          <ScrollText size={24} strokeWidth={1.5} className="text-text-3" />
          <p className="text-base text-text-2">No custody entries recorded for this case yet.</p>
        </div>
      ) : (
        <>
          <ol data-testid="audit-timeline" className="flex flex-col">
            {entries.map((e, i) => (
              <AuditRow key={e.seq} entry={e} state={stateFor(e.seq)} last={i === entries.length - 1} />
            ))}
          </ol>
          {audit.hasNextPage && (
            <div className="mt-3 flex justify-center">
              <Button variant="secondary" size="sm" onClick={() => void audit.fetchNextPage()} disabled={audit.isFetchingNextPage}>
                {audit.isFetchingNextPage && <Loader2 size={13} className="animate-spin" />}
                Load more
              </Button>
            </div>
          )}
        </>
      )}
    </section>
  );
}

const DOT: Record<IntegrityState, string> = {
  verified: "border-ok bg-[var(--ok-tint)]",
  pending: "border-warn bg-[var(--warn-tint)]",
  mismatch: "border-danger bg-[var(--danger-tint)]",
};

function AuditRow({ entry, state, last }: { entry: AuditEntry; state: IntegrityState; last: boolean }) {
  return (
    <li data-testid="audit-entry" data-seq={entry.seq} className="relative flex gap-3 pb-4 last:pb-0">
      {/* left rail: connecting line + status dot */}
      <div className="relative flex w-3 shrink-0 justify-center">
        {!last && <span aria-hidden className="absolute top-3 -bottom-4 w-px bg-line-strong" />}
        <span aria-hidden className={cn("relative z-10 mt-1 size-3 rounded-full border-2", DOT[state])} />
      </div>
      <div className="min-w-0 flex-1 rounded-[var(--radius-card)] border border-line bg-card px-3 py-2.5">
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="font-data text-caption tabular-nums text-text-3">#{entry.seq}</span>
            <span className="truncate font-data text-sm font-medium text-text">{entry.action}</span>
          </div>
          <span className="font-data text-caption tabular-nums text-text-2">{formatTimecode(entry.ts_utc)}</span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-text-2">
          <span>
            {entry.actor} <span className="text-text-3">({entry.role})</span>
          </span>
          <span className="font-data text-text-3">
            {entry.object_type}/{entry.object_id}
          </span>
          {entry.payload_sha256 && (
            <span className="font-data text-text-3" title={entry.payload_sha256}>
              payload {shortHash(entry.payload_sha256)}
            </span>
          )}
          <IntegrityChip state={state} hash={entry.entry_hash} className="ml-auto" />
        </div>
      </div>
    </li>
  );
}
