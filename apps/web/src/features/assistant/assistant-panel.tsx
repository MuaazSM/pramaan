import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, Check, Sparkles, SearchX, WandSparkles, X } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  applyChipEdit,
  filterToChips,
  isFilterEdited,
  isLlmDisabledError,
  parseChipInput,
  previewRow,
  removeChip,
  type EvidenceSearchFilter,
  type FilterChip,
  type FilterKey,
} from "./lib/filter-chips";

type QueryOutcome =
  | { kind: "ok"; filter: EvidenceSearchFilter; resultCount: number; results: Record<string, unknown>[] }
  | { kind: "disabled" };

const PREVIEW_ROWS = 3;

/**
 * "Ask about this case" (docs/03-AI-TIMELINE.md §8.3.1): a natural-language question is turned by
 * the backend's Claude tool-use flow into a structured evidence filter, shown here as editable
 * chips. CLAUDE.md rule 6: the model never produces a finding — the filter is a labelled draft
 * the examiner adjusts locally (edits are NOT re-submitted), and the model only ever sees the
 * question text, never frames or disk bytes (§8.2).
 *
 * Reference products studied: Linear/Raycast command surfaces (inline, keyboard-first), GitHub
 * issue-search filter chips (structured tokens from free text).
 */
export function AssistantPanel({ caseId, onClose, onBack }: { caseId: string; onClose: () => void; onBack?: () => void }) {
  const [question, setQuestion] = useState("");
  // The filter the examiner is working with: starts as the model's proposal, then edited locally.
  const [filter, setFilter] = useState<EvidenceSearchFilter | null>(null);

  const ask = useMutation({
    mutationFn: async (q: string): Promise<QueryOutcome> => {
      const { data, error, response } = await api.POST("/api/cases/{cid}/assistant/query", {
        params: { path: { cid: caseId } },
        body: { question: q },
      });
      if (data) return { kind: "ok", filter: data.filter, resultCount: data.result_count, results: data.results };
      // 404 llm_disabled is the default state of the demo environment, not a failure.
      if (isLlmDisabledError(response?.status, error)) return { kind: "disabled" };
      throw new Error("assistant query failed");
    },
    onSuccess: (outcome) => setFilter(outcome.kind === "ok" ? outcome.filter : null),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (q) ask.mutate(q);
  }

  const outcome = ask.data;

  return (
    <div className="flex max-h-[70vh] flex-col overflow-hidden rounded-[var(--radius-panel)] bg-panel text-text">
      <div className="flex items-center gap-2 border-b border-line px-4 pb-2 pt-3 pr-12">
        {onBack && (
          <Button variant="ghost" size="icon" aria-label="Back to commands" onClick={onBack} className="-ml-2 size-7">
            <ArrowLeft size={15} strokeWidth={1.5} />
          </Button>
        )}
        <Sparkles size={15} strokeWidth={1.75} className="text-ai" />
        <h2 className="text-section text-text">Ask about this case</h2>
      </div>

      <form onSubmit={submit} className="flex items-center gap-2 border-b border-line px-4 py-3">
        <Input
          autoFocus
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. deleted footage on channel 3 yesterday afternoon"
          aria-label="Question about this case"
          className="h-9"
        />
        <Button type="submit" disabled={ask.isPending || question.trim() === ""}>
          {ask.isPending ? "Asking…" : "Ask"}
        </Button>
      </form>

      <div className="min-h-[120px] overflow-y-auto px-4 py-3" aria-live="polite">
        {ask.isPending && <Loading />}
        {ask.isError && !ask.isPending && <ErrorState onRetry={() => ask.mutate(question.trim())} />}
        {!ask.isPending && outcome?.kind === "disabled" && <DisabledState />}
        {!ask.isPending && outcome?.kind === "ok" && filter && (
          <Proposal
            original={outcome.filter}
            filter={filter}
            onChange={setFilter}
            resultCount={outcome.resultCount}
            results={outcome.results}
          />
        )}
        {!ask.isPending && !ask.isError && !outcome && (
          <p className="text-sm text-text-2">
            Describe what you are looking for. The assistant turns it into a filter you can review and edit — it
            never sees frames or disk bytes, and it does not draw conclusions.
          </p>
        )}
      </div>

      <div className="flex justify-end border-t border-line px-4 py-2">
        <Button variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>
    </div>
  );
}

function Loading() {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Interpreting your question">
      <Skeleton className="h-7 w-2/3" />
      <Skeleton className="h-16 w-full" />
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div role="alert" className="flex items-center justify-between gap-3 rounded-[var(--radius-card)] border border-line-strong bg-control p-3">
      <p className="text-sm text-text-2">The assistant couldn't answer that just now. Nothing was changed.</p>
      <Button variant="secondary" size="sm" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}

/** Calm explanation for 404 `llm_disabled` — the default state, so no alarming colours or icons. */
function DisabledState() {
  return (
    <div data-testid="assistant-disabled" className="flex items-start gap-3 rounded-[var(--radius-card)] border border-line-strong bg-control p-3">
      <SearchX size={16} strokeWidth={1.5} className="mt-0.5 shrink-0 text-text-3" />
      <div>
        <p className="text-base font-medium text-text">AI assistant is not enabled</p>
        <p className="mt-1 text-sm text-text-2">
          This installation runs with the LLM feature switched off, so questions can't be turned into filters. All
          forensic analysis, search and reporting work without it. An administrator can enable it in the server
          configuration.
        </p>
      </div>
    </div>
  );
}

function Proposal({
  original,
  filter,
  onChange,
  resultCount,
  results,
}: {
  original: EvidenceSearchFilter;
  filter: EvidenceSearchFilter;
  onChange: (f: EvidenceSearchFilter) => void;
  resultCount: number;
  results: Record<string, unknown>[];
}) {
  const chips = filterToChips(filter);
  const edited = isFilterEdited(original, filter);
  const preview = results.slice(0, PREVIEW_ROWS);

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-[var(--radius-card)] border border-dashed border-[color-mix(in_oklab,var(--ai)_55%,transparent)] bg-[var(--ai-tint)] p-3">
        {/* Extends BRAND.md §8's exact "AI draft · needs examiner review" phrase family — dot kept
            for consistency with the AIDraftBlock signature component. */}
        <div className="mb-2 flex items-center gap-1.5 text-label font-medium text-ai">
          <WandSparkles size={13} strokeWidth={1.75} />
          AI draft {"·"} proposed filter, needs examiner review
        </div>
        {chips.length === 0 ? (
          <p className="text-sm text-text-2">The assistant proposed no filter fields for that question.</p>
        ) : (
          <ChipRow chips={chips} filter={filter} onChange={onChange} />
        )}
        {edited && (
          <p className="mt-2 text-caption text-text-3">
            Edited locally — edits are not re-run automatically.{" "}
            <button type="button" className="focus-ring text-accent-text underline-offset-2 hover:underline" onClick={() => onChange(original)}>
              Reset to proposal
            </button>
          </p>
        )}
      </div>

      <div>
        <p className="text-sm text-text-2" data-testid="assistant-result-count">
          <span className="font-data tabular-nums text-text">{resultCount}</span> {resultCount === 1 ? "result" : "results"} for
          the proposed filter
        </p>
        {preview.length > 0 && (
          <ul className="mt-2 flex flex-col gap-1">
            {preview.map((row, i) => (
              <li key={i} className="rounded-[var(--radius-control)] border border-line bg-control px-2.5 py-1.5 font-data text-caption text-text-2">
                {previewRow(row)
                  .map((kv) => `${kv.key}: ${kv.value}`)
                  .join(" · ") || "(no displayable fields)"}
              </li>
            ))}
            {results.length > preview.length && (
              <li className="px-1 text-caption text-text-3">+ {results.length - preview.length} more not shown</li>
            )}
          </ul>
        )}
      </div>
    </div>
  );
}

function ChipRow({
  chips,
  filter,
  onChange,
}: {
  chips: FilterChip[];
  filter: EvidenceSearchFilter;
  onChange: (f: EvidenceSearchFilter) => void;
}) {
  const [editingKey, setEditingKey] = useState<FilterKey | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  // The editor is derived from the live chip list, so removing the chip being edited closes it.
  const editing = chips.find((c) => c.key === editingKey) ?? null;

  function open(chip: FilterChip) {
    if (chip.kind === "boolean") {
      onChange(applyChipEdit(filter, chip.key, chip.editValue === "true" ? "false" : "true"));
      return;
    }
    setEditingKey(chip.key);
    setDraft(chip.editValue);
    setError(null);
  }

  function apply() {
    if (!editing) return;
    const parsed = parseChipInput(editing.key, draft);
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    onChange(applyChipEdit(filter, editing.key, draft));
    setEditingKey(null);
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-1.5">
        {chips.map((chip) => (
          <span
            key={chip.key}
            data-testid={`filter-chip-${chip.key}`}
            className={cn(
              "inline-flex items-center overflow-hidden rounded-full border bg-panel text-label",
              editing?.key === chip.key ? "border-[var(--ai)]" : "border-line-strong",
            )}
          >
            <button
              type="button"
              onClick={() => open(chip)}
              aria-label={chip.kind === "boolean" ? `Toggle ${chip.label}` : `Edit ${chip.label}`}
              aria-pressed={chip.kind === "boolean" ? chip.value === "yes" : undefined}
              className="focus-ring flex items-center gap-1.5 py-1 pl-2.5 pr-1.5 hover:bg-control"
            >
              <span className="text-text-3">{chip.label}</span>
              <span className="font-data text-text">{chip.value}</span>
            </button>
            <button
              type="button"
              onClick={() => onChange(removeChip(filter, chip.key))}
              aria-label={`Remove ${chip.label} filter`}
              className="focus-ring border-l border-line py-1 pl-1.5 pr-2 text-text-3 hover:bg-control hover:text-text"
            >
              <X size={11} strokeWidth={2} />
            </button>
          </span>
        ))}
      </div>

      {editing && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            apply();
          }}
          className="flex flex-col gap-1.5 rounded-[var(--radius-control)] border border-line bg-panel p-2"
          aria-label={`Edit ${editing.label}`}
        >
          <div className="flex items-center gap-2">
            <ChipEditor chip={editing} draft={draft} onDraft={(v) => { setDraft(v); setError(null); }} />
            <Button type="submit" size="sm" aria-label={`Apply ${editing.label}`}>
              <Check size={13} strokeWidth={2} />
              Apply
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setEditingKey(null)}>
              Cancel
            </Button>
          </div>
          {error && (
            <p role="alert" className="text-caption text-danger">
              {error}
            </p>
          )}
        </form>
      )}
    </div>
  );
}

function ChipEditor({ chip, draft, onDraft }: { chip: FilterChip; draft: string; onDraft: (v: string) => void }) {
  const common = { "aria-label": `${chip.label} value`, autoFocus: true, className: "h-8 flex-1" };
  switch (chip.kind) {
    case "enum":
      return (
        <select
          {...common}
          value={draft}
          onChange={(e) => onDraft(e.target.value)}
          className="focus-ring h-8 flex-1 rounded-[var(--radius-control)] border border-line-strong bg-control px-2 text-base text-text"
        >
          {chip.options?.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      );
    case "datetime":
      return <Input {...common} type="datetime-local" value={draft} onChange={(e) => onDraft(e.target.value)} />;
    case "number":
      return <Input {...common} type="number" step="any" value={draft} onChange={(e) => onDraft(e.target.value)} />;
    default:
      return (
        <Input
          {...common}
          value={draft}
          onChange={(e) => onDraft(e.target.value)}
          placeholder={chip.kind === "number-list" ? "e.g. 2, 3" : undefined}
        />
      );
  }
}
