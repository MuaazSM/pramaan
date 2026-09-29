/**
 * /cases — Cases list.
 * Primary action: New case. Reference products studied: Linear (table density, status pills,
 * filters as chips), Stripe Dashboard (data table with search + filters row).
 */
import { useMemo, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Plus, FolderKanban, Search } from "lucide-react";
import { ScreenShell } from "@/components/shell/screen-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { api } from "@/api/client";
import type { components } from "@/api/schema.gen";

type CaseStatus = components["schemas"]["Case"]["status"];

export const Route = createFileRoute("/_app/cases/")({
  component: CasesScreen,
});

const STATUS_VARIANT: Record<CaseStatus, "ok" | "neutral" | "warn"> = {
  open: "ok",
  closed: "neutral",
  archived: "warn",
};

const STATUS_FILTERS: CaseStatus[] = ["open", "closed", "archived"];

function CasesScreen() {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<CaseStatus | null>(null);

  const { data: cases, isLoading } = useQuery({
    queryKey: ["cases"],
    queryFn: async () => {
      const { data } = await api.GET("/api/cases");
      return data ?? [];
    },
  });

  const filtered = useMemo(() => {
    return (cases ?? []).filter((c) => {
      if (statusFilter && c.status !== statusFilter) return false;
      if (query && !`${c.case_number} ${c.title}`.toLowerCase().includes(query.toLowerCase())) return false;
      return true;
    });
  }, [cases, statusFilter, query]);

  return (
    <ScreenShell segments={[{ label: "Cases" }]}>
      <div className="mx-auto flex max-w-6xl flex-col gap-4 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-[20px] font-semibold tracking-[-0.02em] text-text">Cases</h1>
            <p className="text-[13px] text-text-2">Every case this workstation has examined.</p>
          </div>
          <Button>
            <Plus size={15} strokeWidth={1.75} />
            New case
          </Button>
        </div>

        <div className="flex items-center gap-2">
          <div className="relative w-64">
            <Search size={14} strokeWidth={1.75} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-3" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search case number or title"
              className="pl-8"
            />
          </div>
          <div className="flex items-center gap-1.5">
            {STATUS_FILTERS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setStatusFilter(statusFilter === s ? null : s)}
                className={cn(
                  "focus-ring rounded-full border px-2.5 py-1 text-xs font-medium capitalize transition-colors duration-[var(--dur-fast)]",
                  statusFilter === s
                    ? "border-[color-mix(in_oklab,var(--brand-500)_45%,transparent)] bg-[var(--selected)] text-accent-text"
                    : "border-line-strong bg-control text-text-2 hover:text-text",
                )}
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        {isLoading ? (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-11 w-full" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState hasCases={(cases?.length ?? 0) > 0} />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Case no.</TableHead>
                <TableHead>Title</TableHead>
                <TableHead>Lab</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((c) => (
                <TableRow key={c.id} tabIndex={0} className="focus-ring cursor-pointer">
                  <TableCell>
                    <Link to="/cases/$cid" params={{ cid: c.id }} className="focus-ring rounded font-mono text-[12px] text-accent-text hover:underline">
                      {c.case_number}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Link to="/cases/$cid" params={{ cid: c.id }} className="focus-ring rounded text-text hover:underline">
                      {c.title}
                    </Link>
                  </TableCell>
                  <TableCell className="text-text-2">{c.lab ?? "—"}</TableCell>
                  <TableCell>
                    <Badge variant={STATUS_VARIANT[c.status]} className="capitalize">
                      {c.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="tabular-nums text-text-2">
                    {new Date(c.updated_utc).toISOString().slice(0, 16).replace("T", " ")}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </ScreenShell>
  );
}

function EmptyState({ hasCases }: { hasCases: boolean }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-[var(--radius-panel)] border border-dashed border-line-strong py-16 text-center">
      <FolderKanban size={28} strokeWidth={1.5} className="text-text-3" />
      <p className="text-[13px] text-text-2">
        {hasCases ? "No cases match these filters." : "No cases yet. Create one to register evidence."}
      </p>
      {!hasCases && (
        <Button size="sm">
          <Plus size={14} strokeWidth={1.75} />
          New case
        </Button>
      )}
    </div>
  );
}
