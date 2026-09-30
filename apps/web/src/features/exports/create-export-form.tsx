/**
 * Range picker / create-export form. The page's single primary action: "Create signed export".
 * Native controls only (datetime-local like recordings-screen's filter row, a number input, the
 * Radix Select primitive) — no custom range picker. Time fields are IST wall-clock values (see
 * lib/time.ts) sent as normalised-time microseconds.
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, PackagePlus, TextCursorInput } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useToast } from "@/components/ui/use-toast";
import { api } from "@/api/client";
import { formatTimecodeUs } from "@/lib/format";
import type { components } from "@/api/schema.gen";
import { apiErrorMessage, csrfHeaders } from "./lib/csrf";
import { istLocalToUs, usToIstLocal } from "./lib/time";

type ExportRecord = components["schemas"]["ExportRecord"];

export interface ExportPrefill {
  recording_id?: string;
  channel?: number;
  from_norm_us?: number;
  to_norm_us?: number;
}

const NONE = "__none__";

const DATETIME_CLASS =
  "focus-ring h-8 w-full max-w-72 rounded-[var(--radius-control)] border border-line-strong bg-control px-2 font-mono text-[12px] text-text disabled:cursor-not-allowed disabled:opacity-40";

export function CreateExportForm({
  caseId,
  prefill,
  onCreated,
}: {
  caseId: string;
  prefill: ExportPrefill;
  onCreated: (record: ExportRecord) => void;
}) {
  const { toast } = useToast();
  const hasPrefill = Object.values(prefill).some((v) => v !== undefined);

  const [recordingId, setRecordingId] = useState(prefill.recording_id ?? "");
  const [channel, setChannel] = useState(prefill.channel !== undefined ? String(prefill.channel) : "");
  const [fromLocal, setFromLocal] = useState(prefill.from_norm_us !== undefined ? usToIstLocal(prefill.from_norm_us) : "");
  const [toLocal, setToLocal] = useState(prefill.to_norm_us !== undefined ? usToIstLocal(prefill.to_norm_us) : "");
  const [showPrefillHint, setShowPrefillHint] = useState(hasPrefill);
  const [validationError, setValidationError] = useState<string | null>(null);

  const recordingsQuery = useQuery({
    queryKey: ["recordings", caseId],
    queryFn: async () => (await api.GET("/api/cases/{cid}/recordings", { params: { path: { cid: caseId } } })).data ?? [],
  });
  const recordings = useMemo(
    () => [...(recordingsQuery.data ?? [])].sort((a, b) => a.channel - b.channel || (a.start_ts_us ?? 0) - (b.start_ts_us ?? 0)),
    [recordingsQuery.data],
  );

  const createMutation = useMutation({
    mutationFn: async (body: components["schemas"]["ExportCreate"]) => {
      const { data, error } = await api.POST("/api/cases/{cid}/exports", {
        params: { path: { cid: caseId } },
        body,
        headers: csrfHeaders(),
      });
      if (!data) throw new Error(apiErrorMessage(error, "The export could not be created."));
      return data;
    },
    onSuccess: (record) => {
      onCreated(record);
      toast({ title: "Signed export created", description: record.id, variant: "ok" });
    },
  });

  const usingRecording = recordingId !== "";

  function edited<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v);
      setShowPrefillHint(false);
      setValidationError(null);
    };
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setValidationError(null);
    createMutation.reset();

    if (usingRecording) {
      createMutation.mutate({ recording_id: recordingId, channel: null, from_norm_us: null, to_norm_us: null });
      return;
    }
    const channelNum = channel.trim() === "" ? null : Number(channel);
    if (channelNum === null || !Number.isInteger(channelNum) || channelNum < 0) {
      setValidationError("Choose a recording, or enter a channel number (optionally with a time range).");
      return;
    }
    const fromUs = istLocalToUs(fromLocal);
    const toUs = istLocalToUs(toLocal);
    if (fromUs !== null && toUs !== null && fromUs > toUs) {
      setValidationError("The range start must not be after the range end.");
      return;
    }
    createMutation.mutate({ recording_id: null, channel: channelNum, from_norm_us: fromUs, to_norm_us: toUs });
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" aria-labelledby="create-export-heading">
      <div className="flex flex-col gap-2">
        <div>
          <h2 id="create-export-heading" className="text-[15px] font-semibold tracking-[-0.01em] text-text">
            Create export
          </h2>
          <p className="mt-0.5 text-[12px] text-text-2">Pick a whole recording, or a channel with an optional time range.</p>
        </div>
        {showPrefillHint && (
          <Badge variant="brand" className="w-fit whitespace-nowrap" data-testid="prefill-hint">
            <TextCursorInput size={11} strokeWidth={1.75} aria-hidden />
            Prefilled from review selection
          </Badge>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="export-recording">Recording (optional)</Label>
        <Select value={recordingId || NONE} onValueChange={edited((v: string) => setRecordingId(v === NONE ? "" : v))}>
          <SelectTrigger id="export-recording" aria-label="Recording">
            <SelectValue placeholder={recordingsQuery.isLoading ? "Loading recordings…" : "None — use channel + time range"} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE}>None — use channel + time range</SelectItem>
            {recordings.map((r) => (
              <SelectItem key={r.id} value={r.id}>
                <span className="font-mono text-[12px]">
                  CH{r.channel} · {r.id}
                  {r.start_ts_us != null ? ` · ${formatTimecodeUs(r.start_ts_us)}` : ""}
                </span>
              </SelectItem>
            ))}
            {/* A prefilled recording id that is not (yet) in the fetched list must still be selectable-looking. */}
            {recordingId && !recordings.some((r) => r.id === recordingId) && (
              <SelectItem value={recordingId}>
                <span className="font-mono text-[12px]">{recordingId}</span>
              </SelectItem>
            )}
          </SelectContent>
        </Select>
        {recordingsQuery.isError && <p className="text-[11px] text-danger">Recordings could not be loaded — use a channel instead.</p>}
        {usingRecording && <p className="text-[11px] text-text-3">A recording export covers the whole recording; channel and time range are ignored.</p>}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="export-channel">Channel</Label>
        <Input
          id="export-channel"
          type="number"
          min={0}
          step={1}
          inputMode="numeric"
          value={channel}
          disabled={usingRecording}
          onChange={(e) => edited(setChannel)(e.target.value)}
          className="w-28 font-mono tabular-nums"
          placeholder="e.g. 2"
        />
      </div>

      <fieldset className="flex flex-col gap-1.5" disabled={usingRecording}>
        <legend className="mb-1.5 text-xs font-medium text-text-2">Normalised time range (IST)</legend>
        <div className="grid grid-cols-[3rem_1fr] items-center gap-x-2 gap-y-2">
          <label htmlFor="export-from" className="text-[11px] text-text-3">
            From
          </label>
          <input
            id="export-from"
            type="datetime-local"
            step={1}
            value={fromLocal}
            onChange={(e) => edited(setFromLocal)(e.target.value)}
            aria-label="From normalised time (IST)"
            className={DATETIME_CLASS}
          />
          <label htmlFor="export-to" className="text-[11px] text-text-3">
            To
          </label>
          <input
            id="export-to"
            type="datetime-local"
            step={1}
            value={toLocal}
            onChange={(e) => edited(setToLocal)(e.target.value)}
            aria-label="To normalised time (IST)"
            className={DATETIME_CLASS}
          />
        </div>
      </fieldset>
      <p className="-mt-2 text-[11px] leading-snug text-text-3">
        In this build the backend matches the range against each frame&apos;s header (device) clock; normalised-clock filtering is pending the timeline workstream.
      </p>

      {(validationError || createMutation.isError) && (
        <p role="alert" className="rounded-[var(--radius-control)] border border-[color-mix(in_oklab,var(--danger)_45%,transparent)] bg-[var(--danger-tint)] px-2.5 py-2 text-[12px] text-danger">
          {validationError ?? (createMutation.error instanceof Error ? createMutation.error.message : "The export could not be created.")}
        </p>
      )}

      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] leading-snug text-text-3">Stream copy only — original video is never re-encoded.</p>
        <Button type="submit" variant="primary" disabled={createMutation.isPending}>
          {createMutation.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <PackagePlus aria-hidden />}
          {createMutation.isPending ? "Creating…" : "Create signed export"}
        </Button>
      </div>
    </form>
  );
}
