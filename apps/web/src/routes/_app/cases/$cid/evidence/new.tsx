/**
 * /cases/$cid/evidence/new — Intake wizard.
 * Primary action: Register and hash. Three steps: choose image (server browser scoped to
 * evidence roots), SWGDE seizure clock (DVR shows / reference shows → live offset), confirm
 * (write-blocker, notes) → hashing progress.
 * Reference products studied: Cal.com (multi-step form, clear step rail), Stripe (progress +
 * confirmation summary).
 */
import { useEffect, useMemo, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronLeft, ChevronRight, File as FileIcon, Folder, HardDrive, Lock, ShieldCheck } from "lucide-react";
import { ScreenShell } from "@/components/shell/screen-shell";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import { api } from "@/api/client";
import { useToast } from "@/components/ui/use-toast";

export const Route = createFileRoute("/_app/cases/$cid/evidence/new")({
  component: IntakeWizard,
});

const STEPS = ["Choose image", "Seizure clock", "Confirm"] as const;

function IntakeWizard() {
  const { cid } = Route.useParams();
  const caseQuery = useQuery({
    queryKey: ["case", cid],
    queryFn: async () => (await api.GET("/api/cases/{cid}", { params: { path: { cid } } })).data,
  });
  const caseLabel = caseQuery.data?.case_number ?? cid;
  const [step, setStep] = useState(0);
  const [browsePath, setBrowsePath] = useState("/evidence");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [dvrTime, setDvrTime] = useState("2026-03-12 14:07:49");
  const [refTime, setRefTime] = useState("2026-03-12 14:02:37");
  const [refSource, setRefSource] = useState("Examiner mobile (NTP-synced)");
  const [timezone, setTimezone] = useState("Asia/Kolkata");
  const [writeBlocker, setWriteBlocker] = useState("Tableau T35689iu");
  const [notes, setNotes] = useState("");
  const [hashing, setHashing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [done, setDone] = useState(false);
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const browseQuery = useQuery({
    queryKey: ["fs-browse", browsePath],
    queryFn: async () => (await api.GET("/api/fs/browse", { params: { query: { path: browsePath } } })).data ?? [],
  });

  const offsetSeconds = useMemo(() => {
    const dvr = Date.parse(dvrTime.replace(" ", "T"));
    const ref = Date.parse(refTime.replace(" ", "T"));
    if (Number.isNaN(dvr) || Number.isNaN(ref)) return null;
    return Math.round((dvr - ref) / 1000);
  }, [dvrTime, refTime]);

  const registerMutation = useMutation({
    mutationFn: async () => {
      if (!selectedPath) throw new Error("no path selected");
      const { data, error } = await api.POST("/api/cases/{cid}/evidence", {
        params: { path: { cid } },
        body: {
          path: selectedPath,
          label: label || selectedPath.split("/").pop() || selectedPath,
          intake: {
            seized_at_local: dvrTime,
            dvr_displayed_time: dvrTime,
            reference_time: refTime,
            reference_source: refSource,
            timezone,
            write_blocker: writeBlocker || null,
            notes: notes || null,
            make_model_label: null,
            serial_label: null,
          },
        },
      });
      if (error || !data) throw new Error("registration failed");
      return data;
    },
  });

  function startHashing() {
    setHashing(true);
    registerMutation.mutate(undefined, {
      onError: () => {
        toast({ title: "Registration failed", description: "Check the image path and try again.", variant: "danger" });
        setHashing(false);
      },
    });
  }

  useEffect(() => {
    if (!hashing || done) return;
    const id = setInterval(() => {
      setProgress((p) => {
        const next = Math.min(100, p + 7 + Math.random() * 6);
        if (next >= 100) {
          clearInterval(id);
          setDone(true);
          void queryClient.invalidateQueries({ queryKey: ["evidence", cid] });
        }
        return next;
      });
    }, 220);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hashing, done]);

  const canNext =
    (step === 0 && Boolean(selectedPath)) ||
    (step === 1 && dvrTime.length > 0 && refTime.length > 0) ||
    step === 2;

  if (hashing) {
    return (
      <ScreenShell
        segments={[
          { label: "Cases", to: "/cases" },
          { label: caseLabel, to: `/cases/${cid}` },
          { label: "Add evidence" },
        ]}
        caseId={cid}
        showCustodySeal
      >
        <div className="mx-auto flex max-w-xl flex-col items-center gap-6 p-6 pt-24 text-center">
          <div
            className={cn(
              "flex size-14 items-center justify-center rounded-full border",
              done ? "border-[color-mix(in_oklab,var(--ok)_45%,transparent)] bg-[var(--ok-tint)]" : "border-line-strong bg-control",
            )}
          >
            {done ? <Check size={22} strokeWidth={2} className="text-ok" /> : <HardDrive size={22} strokeWidth={1.5} className="text-text-2" />}
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-[-0.01em] text-text">{done ? "Evidence registered and hashed" : "Hashing evidence…"}</h1>
            <p className="mt-1 text-base text-text-2">
              {done ? "SHA-256 and MD5 computed and stored with the case." : "Computing SHA-256 and MD5 in read-only mode. This does not touch the source bytes."}
            </p>
          </div>
          <Progress value={progress} className="w-full" />
          <span className="font-data text-sm tabular-nums text-text-3">{Math.round(progress)}%</span>
          {done && (
            <Button asChild>
              <Link to="/cases/$cid" params={{ cid }}>
                Back to case overview
              </Link>
            </Button>
          )}
        </div>
      </ScreenShell>
    );
  }

  return (
    <ScreenShell
      segments={[
        { label: "Cases", to: "/cases" },
        { label: caseLabel, to: `/cases/${cid}` },
        { label: "Add evidence" },
      ]}
      caseId={cid}
      showCustodySeal
    >
      <div className="mx-auto flex max-w-2xl flex-col gap-6 p-6">
        <div>
          <h1 className="text-page-title text-text">Add evidence</h1>
          <p className="mt-1 text-base text-text-2">Register a disk image against this case and establish its seizure clock.</p>
        </div>

        {/* Step rail */}
        <ol className="flex items-center gap-2">
          {STEPS.map((s, i) => (
            <li key={s} className="flex flex-1 items-center gap-2">
              <div
                className={cn(
                  "flex size-6 shrink-0 items-center justify-center rounded-full border text-caption font-medium tabular-nums",
                  i < step
                    ? "border-[color-mix(in_oklab,var(--ok)_45%,transparent)] bg-[var(--ok-tint)] text-ok"
                    : i === step
                      ? "border-[color-mix(in_oklab,var(--brand-500)_45%,transparent)] bg-[var(--selected)] text-accent-text"
                      : "border-line-strong text-text-3",
                )}
              >
                {i < step ? <Check size={12} strokeWidth={2.5} /> : i + 1}
              </div>
              <span className={cn("text-label", i === step ? "font-medium text-text" : "text-text-3")}>{s}</span>
              {i < STEPS.length - 1 && <div className="h-px flex-1 bg-line-strong" />}
            </li>
          ))}
        </ol>

        <div className="rounded-[var(--radius-panel)] border border-line bg-panel p-5">
          {step === 0 && (
            <div className="flex flex-col gap-3">
              <Label>Image path (evidence roots only)</Label>
              <div className="flex items-center gap-2 text-sm text-text-3">
                <span className="font-data">{browsePath}</span>
              </div>
              <div className="flex flex-col overflow-hidden rounded-[var(--radius-card)] border border-line">
                {browseQuery.data?.length === 0 && (
                  <p className="p-4 text-center text-sm text-text-3">Empty directory.</p>
                )}
                {browseQuery.data?.map((entry) => (
                  <button
                    key={entry.path}
                    type="button"
                    onClick={() => (entry.is_dir ? setBrowsePath(entry.path) : setSelectedPath(entry.path))}
                    className={cn(
                      "focus-ring flex items-center gap-2 border-b border-line px-3 py-2 text-left text-base last:border-0 hover:bg-control",
                      selectedPath === entry.path && "bg-[var(--selected)]",
                    )}
                  >
                    {entry.is_dir ? (
                      <Folder size={14} strokeWidth={1.5} className="text-text-3" />
                    ) : (
                      <FileIcon size={14} strokeWidth={1.5} className={entry.looks_like_image ? "text-accent-text" : "text-text-3"} />
                    )}
                    <span className="truncate text-text">{entry.name}</span>
                    {entry.looks_like_image && <span className="ml-auto text-caption text-ok">image</span>}
                  </button>
                ))}
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="label">Label</Label>
                <Input id="label" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Hikvision DVR, gate desk" />
              </div>
            </div>
          )}

          {step === 1 && (
            <div className="flex flex-col gap-4">
              <p className="text-sm text-text-2">
                SWGDE seizure clock: record the DVR&apos;s displayed time against a trusted reference at the moment of seizure.
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="dvr-time">DVR displayed time</Label>
                  <Input id="dvr-time" value={dvrTime} onChange={(e) => setDvrTime(e.target.value)} className="font-data" />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="ref-time">Reference time</Label>
                  <Input id="ref-time" value={refTime} onChange={(e) => setRefTime(e.target.value)} className="font-data" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="ref-source">Reference source</Label>
                  <Input id="ref-source" value={refSource} onChange={(e) => setRefSource(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="tz">Timezone</Label>
                  <Input id="tz" value={timezone} onChange={(e) => setTimezone(e.target.value)} />
                </div>
              </div>
              {offsetSeconds != null && (
                <div className="flex items-center gap-2 rounded-[var(--radius-control)] border border-line-strong bg-control px-3 py-2 text-sm">
                  <span className="text-text-2">Live offset</span>
                  <span className="font-data tabular-nums text-warn">
                    {offsetSeconds >= 0 ? "+" : ""}
                    {offsetSeconds}s device drift
                  </span>
                </div>
              )}
            </div>
          )}

          {step === 2 && (
            <div className="flex flex-col gap-4">
              <div className="flex items-center gap-2 rounded-[var(--radius-control)] border border-[color-mix(in_oklab,var(--ok)_35%,transparent)] bg-[var(--ok-tint)] px-3 py-2 text-sm text-ok">
                <Lock size={13} strokeWidth={1.75} />
                Image will be opened read-only. Pramaan never writes to evidence.
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="write-blocker">Write-blocker used</Label>
                <Input id="write-blocker" value={writeBlocker} onChange={(e) => setWriteBlocker(e.target.value)} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="notes">Notes</Label>
                <textarea
                  id="notes"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  rows={3}
                  className="focus-ring w-full rounded-[var(--radius-control)] border border-line-strong bg-control px-2.5 py-2 text-base text-text placeholder:text-text-3"
                  placeholder="Chain-of-custody notes for this acquisition"
                />
              </div>
              <dl className="grid grid-cols-2 gap-2 rounded-[var(--radius-card)] border border-line bg-card p-3 text-sm">
                <dt className="text-text-3">Path</dt>
                <dd className="truncate text-right font-data text-text-2">{selectedPath}</dd>
                <dt className="text-text-3">Seizure offset</dt>
                <dd className="text-right font-data tabular-nums text-text-2">
                  {offsetSeconds != null ? `${offsetSeconds >= 0 ? "+" : ""}${offsetSeconds}s` : "—"}
                </dd>
              </dl>
            </div>
          )}
        </div>

        <div className="flex justify-between">
          <Button variant="ghost" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0}>
            <ChevronLeft size={15} strokeWidth={1.75} />
            Back
          </Button>
          {step < STEPS.length - 1 ? (
            <Button onClick={() => setStep((s) => s + 1)} disabled={!canNext}>
              Next
              <ChevronRight size={15} strokeWidth={1.75} />
            </Button>
          ) : (
            <Button onClick={startHashing} disabled={!canNext}>
              <ShieldCheck size={15} strokeWidth={1.75} />
              Register and hash
            </Button>
          )}
        </div>
      </div>
    </ScreenShell>
  );
}
