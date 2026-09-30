/**
 * Settings screen body — four independent panels: System health (live), LLM (state + budget meter,
 * live usage), Users and roles (read-only reference), Keys (read-only reference).
 * Contracts: GET /system/health, GET /llm/usage. There is no user- or key-management endpoint, so
 * those two panels are informational only and carry no controls (CLAUDE.md rule 7 extended to UI
 * affordances: never present a control that silently does nothing).
 */
import { useQuery } from "@tanstack/react-query";
import { Activity, Bot, Check, KeyRound, Users, X } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { QueryErrorState } from "@/components/shell/query-error-state";
import { api } from "@/api/client";
import { errorFromResponse } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import { formatTimecode } from "@/lib/format";
import type { components } from "@/api/schema.gen";

type LlmUsageEntry = components["schemas"]["LlmUsageEntry"];

/**
 * Display-only reference caps from docs/03-AI-TIMELINE.md §8.2 (`llm.budget_usd_total` = 60,
 * `llm.budget_usd_per_case` = 5). No endpoint exposes the configured values, so these are the
 * documented *defaults* and are labelled as such in the UI — not live-fetched.
 */
const DEFAULT_CAP_TOTAL_USD = 60;
const DEFAULT_CAP_PER_CASE_USD = 5;

export function SettingsScreen() {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5 p-6">
      <div>
        <h1 className="text-[20px] font-semibold tracking-[-0.02em] text-text">Settings</h1>
        <p className="text-[13px] text-text-2">System health, LLM budget, roles and signing keys for this deployment.</p>
      </div>
      <HealthPanel />
      <LlmPanel />
      <UsersPanel />
      <KeysPanel />
    </div>
  );
}

function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/system/health");
      if (error || !data) throw errorFromResponse(response, "system health could not be loaded");
      return data;
    },
  });
}

function PanelHeader({
  icon: Icon,
  id,
  title,
  description,
  badge,
}: {
  icon: typeof Activity;
  id: string;
  title: string;
  description: string;
  badge?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="flex items-center gap-2.5">
        <span className="flex size-9 items-center justify-center rounded-[var(--radius-card)] border border-line-strong bg-control">
          <Icon size={16} strokeWidth={1.75} className="text-text-2" />
        </span>
        <div>
          <h2 id={id} className="text-[14px] font-semibold text-text">
            {title}
          </h2>
          <p className="text-xs text-text-2">{description}</p>
        </div>
      </div>
      {badge}
    </div>
  );
}

const PANEL = "rounded-[var(--radius-panel)] border border-line bg-panel p-5";

/* ------------------------------------- System health ----------------------------------------- */

function HealthPanel() {
  const healthQuery = useHealth();
  const { data: health, isLoading, isError } = healthQuery;

  const rows = health
    ? ([
        ["Scanner backend", health.scanner_backend],
        ["ffmpeg", health.ffmpeg],
        ["pyewf", health.pyewf],
        ["weasyprint", health.weasyprint],
        ["Fabric anchoring", health.fabric],
        ["LLM enabled", health.llm_enabled],
        ["Stub mode", health.stub_mode],
      ] as const)
    : [];

  return (
    <section aria-labelledby="health-heading" className={PANEL} data-testid="panel-health">
      <PanelHeader
        icon={Activity}
        id="health-heading"
        title="System health"
        description="Live from GET /system/health — optional components fall back gracefully when off."
      />
      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : isError || !health ? (
        <QueryErrorState error={healthQuery.error} subject="system health" onRetry={() => void healthQuery.refetch()} className="py-6" />
      ) : (
        <dl className="rounded-[var(--radius-card)] border border-line bg-card px-4 text-xs">
          {rows.map(([label, value]) => (
            <div key={label} className="grid grid-cols-2 items-center border-b border-line py-2 last:border-0">
              <dt className="text-text-2">{label}</dt>
              <dd className="flex items-center justify-end gap-1.5">
                {typeof value === "boolean" ? (
                  <span className={cn("flex items-center gap-1", value ? "text-ok" : "text-text-3")}>
                    {value ? <Check size={12} strokeWidth={2} /> : <X size={12} strokeWidth={2} />}
                    {value ? "on" : "off"}
                  </span>
                ) : (
                  <span className="font-mono text-text">{value}</span>
                )}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

/* ------------------------------------------ LLM ---------------------------------------------- */

function useLlmUsage() {
  return useQuery({
    queryKey: ["llm-usage"],
    queryFn: async (): Promise<LlmUsageEntry[]> => {
      const { data, response } = await api.GET("/api/llm/usage");
      // Real backend answers 404 `llm_disabled` when the LLM is off — that is "no usage", not a failure.
      if (response.status === 404) return [];
      if (!response.ok || !data) throw new Error(`llm usage request failed (${response.status})`);
      return data;
    },
  });
}

function usd(n: number): string {
  return `$${n.toFixed(2)}`;
}

function LlmPanel() {
  const { data: health } = useHealth();
  const usage = useLlmUsage();
  const enabled = health?.llm_enabled ?? false;
  const rows = [...(usage.data ?? [])].sort((a, b) => a.created_utc.localeCompare(b.created_utc));
  const total = rows.reduce((sum, r) => sum + r.cost_usd, 0);
  const pct = Math.min(100, (total / DEFAULT_CAP_TOTAL_USD) * 100);

  return (
    <section aria-labelledby="llm-heading" className={PANEL} data-testid="panel-llm">
      <PanelHeader
        icon={Bot}
        id="llm-heading"
        title="LLM"
        description="Claude only drafts labelled text from structured metadata; it never produces findings."
        badge={health ? <Badge variant={enabled ? "ai" : "neutral"}>LLM: {enabled ? "on" : "off"}</Badge> : undefined}
      />

      <dl className="mb-4 rounded-[var(--radius-card)] border border-line bg-card px-4 text-xs">
        <div className="grid grid-cols-2 items-center border-b border-line py-2">
          <dt className="text-text-2">Provider</dt>
          <dd className="text-right text-text-2">
            configured server-side via <span className="font-mono text-text">PRAMAAN_LLM_PROVIDER</span>
          </dd>
        </div>
        <div className="grid grid-cols-2 items-center py-2">
          <dt className="text-text-2">Status</dt>
          <dd className="text-right text-text-2">
            {enabled ? "enabled — calls are metered below" : "disabled — no calls are made; history below is read-only"}
          </dd>
        </div>
      </dl>

      <div className={cn(!enabled && "opacity-60")} data-testid="budget-meter" data-inactive={!enabled}>
        <div className="mb-1 flex items-baseline justify-between text-xs">
          <span className="text-text-2">
            Total spend{!enabled && <span className="text-text-3"> · meter inactive (LLM off)</span>}
          </span>
          <span className="font-mono tabular-nums text-text">
            <span data-testid="budget-spent">{usage.isLoading ? "…" : usd(total)}</span>
            <span className="text-text-3"> / {usd(DEFAULT_CAP_TOTAL_USD)} default cap</span>
          </span>
        </div>
        {/* Own bar rather than ui/Progress: that primitive does not forward `value` to the Radix root, so it never sets aria-valuenow. */}
        <div
          role="progressbar"
          aria-label="Total LLM spend against default cap"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(pct * 100) / 100}
          aria-valuetext={`${usd(total)} of ${usd(DEFAULT_CAP_TOTAL_USD)} default cap`}
          className="h-1.5 w-full overflow-hidden rounded-full bg-control"
        >
          <div className={cn("h-full rounded-full", pct >= 80 ? "bg-warn" : "bg-accent")} style={{ width: `${pct}%` }} />
        </div>
        <p className="mt-2 text-[11px] text-text-3">
          Caps are the documented defaults (<span className="font-mono">llm.budget_usd_total</span> ={" "}
          {DEFAULT_CAP_TOTAL_USD}, <span className="font-mono">llm.budget_usd_per_case</span> = {DEFAULT_CAP_PER_CASE_USD}), not
          live-fetched — no endpoint exposes the configured values. Usage rows carry no case id, so spend against the{" "}
          {usd(DEFAULT_CAP_PER_CASE_USD)} per-case cap cannot be shown here; the server enforces both caps.
        </p>
      </div>

      <div className="mt-4">
        <h3 className="mb-1.5 text-[11px] uppercase tracking-wide text-text-3">Usage ({rows.length} calls)</h3>
        {usage.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : usage.isError ? (
          <p role="alert" className="text-xs text-danger">
            Could not load LLM usage.
          </p>
        ) : rows.length === 0 ? (
          <p className="rounded-[var(--radius-card)] border border-dashed border-line-strong py-5 text-center text-xs text-text-2">
            No LLM calls recorded.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Model</TableHead>
                <TableHead>Tokens in / out</TableHead>
                <TableHead>Cost</TableHead>
                <TableHead>Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.id}>
                  <TableCell className="font-mono text-[11px] text-text">{r.model}</TableCell>
                  <TableCell className="font-mono tabular-nums text-text-2">
                    {r.input_tokens.toLocaleString()} / {r.output_tokens.toLocaleString()}
                  </TableCell>
                  <TableCell className="font-mono tabular-nums text-text-2">${r.cost_usd.toFixed(4)}</TableCell>
                  <TableCell className="font-mono tabular-nums text-text-3">{formatTimecode(r.created_utc)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </section>
  );
}

/* --------------------------------------- Users and roles ------------------------------------- */

const ROLES: { role: string; can: string; cannot: string }[] = [
  {
    role: "examiner",
    can: "Registers evidence, runs scans, reviews recordings, generates reports and exports, creates anchors.",
    cannot: "Manage users.",
  },
  {
    role: "reviewer",
    can: "Signs in and reads case data.",
    cannot: "Run scans, create anchors, manage users.",
  },
  {
    role: "admin",
    can: "Everything an examiner can, plus user management.",
    cannot: "—",
  },
];

function UsersPanel() {
  return (
    <section aria-labelledby="users-heading" className={PANEL} data-testid="panel-users">
      <PanelHeader
        icon={Users}
        id="users-heading"
        title="Users and roles"
        description="Three seeded accounts, in-memory auth. Reference only."
        badge={<Badge variant="neutral">read-only</Badge>}
      />
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Role</TableHead>
            <TableHead>Can</TableHead>
            <TableHead>Cannot</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {ROLES.map((r) => (
            <TableRow key={r.role}>
              <TableCell className="font-mono text-[12px] text-text">{r.role}</TableCell>
              <TableCell className="text-text-2">{r.can}</TableCell>
              <TableCell className="text-text-3">{r.cannot}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="mt-3 text-[11px] text-text-3">
        Not yet backed by a management endpoint: users cannot be invited, edited or removed from the UI. Role rules per
        docs/02-BACKEND.md §11 (“reviewers cannot run scans; only admins manage users”); anchor creation is restricted to
        examiners and admins by the API.
      </p>
    </section>
  );
}

/* ------------------------------------------- Keys -------------------------------------------- */

function KeysPanel() {
  const { data: health } = useHealth();
  const items: { label: string; value: React.ReactNode }[] = [
    {
      label: "Examiner keys",
      value: (
        <>
          One <span className="font-mono">Ed25519</span> key per examiner; signs the <span className="font-mono">entry_hash</span> of
          every custody entry that examiner causes.
        </>
      ),
    },
    {
      label: "Lab key",
      value: (
        <>
          One <span className="font-mono">Ed25519</span> lab key; signs anchors (<span className="font-mono">lab_signature</span>) and
          reports.
        </>
      ),
    },
    {
      label: "Storage",
      value: "Server-side under keys/ with file mode 600. Private keys are never sent to the browser.",
    },
    {
      label: "Fabric anchoring",
      value: health ? (health.fabric ? "available on this deployment" : "not available — local ledger anchors only") : "…",
    },
  ];
  return (
    <section aria-labelledby="keys-heading" className={PANEL} data-testid="panel-keys">
      <PanelHeader
        icon={KeyRound}
        id="keys-heading"
        title="Keys"
        description="How custody entries and anchors are signed. Reference only."
        badge={<Badge variant="neutral">read-only</Badge>}
      />
      <dl className="rounded-[var(--radius-card)] border border-line bg-card px-4 text-xs">
        {items.map((it) => (
          <div key={it.label} className="grid grid-cols-[9rem_1fr] gap-3 border-b border-line py-2 last:border-0">
            <dt className="text-text-2">{it.label}</dt>
            <dd className="text-text">{it.value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-[11px] text-text-3">
        Describes the design in docs/02-BACKEND.md §8 — no key-management endpoint exists, so keys cannot be listed, rotated or
        exported here.
      </p>
    </section>
  );
}
