/**
 * /design — Component gallery (internal). Every primitive and signature component in every
 * state, used by the visual QA loop (docs/04-FRONTEND.md §8). Not part of the examiner's flow.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Download, Plus, Search, Mail } from "lucide-react";
import { ScreenShell } from "@/components/shell/screen-shell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input, Label } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Toast, ToastDescription, ToastTitle } from "@/components/ui/toast";
import { IntegrityChip } from "@/components/signature/integrity-chip";
import { LineageBreadcrumb } from "@/components/signature/lineage-breadcrumb";
import { CustodySeal } from "@/components/signature/custody-seal";
import { TierBadge } from "@/components/signature/tier-badge";
import { ClockStack } from "@/components/signature/clock-stack";
import { AIDraftBlock } from "@/components/signature/ai-draft-block";
import { JobLog } from "@/components/signature/job-log";

export const Route = createFileRoute("/_app/design")({
  component: DesignGallery,
});

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-[13px] font-semibold uppercase tracking-wide text-text-3">{title}</h2>
      <div className="rounded-[var(--radius-panel)] border border-line bg-panel p-5">{children}</div>
    </section>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-line py-3 last:border-0">
      <span className="w-32 shrink-0 text-xs text-text-3">{label}</span>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

function DesignGallery() {
  const [toastOpen, setToastOpen] = useState(false);

  return (
    <ScreenShell segments={[{ label: "Design gallery" }]}>
      <div className="mx-auto flex max-w-4xl flex-col gap-8 p-6 pb-24">
        <div>
          <h1 className="text-[20px] font-semibold tracking-[-0.02em] text-text">Design gallery</h1>
          <p className="text-[13px] text-text-2">
            Every primitive and signature component, every state, both themes. Internal QA surface.
          </p>
        </div>

        <Section title="Buttons">
          <Row label="Variants">
            <Button variant="primary">Primary</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="danger">Danger</Button>
            <Button variant="link">Link</Button>
          </Row>
          <Row label="Sizes">
            <Button size="sm">Small</Button>
            <Button size="md">Medium</Button>
            <Button size="lg">Large</Button>
            <Button size="icon" aria-label="Add">
              <Plus />
            </Button>
          </Row>
          <Row label="States">
            <Button>
              <Download /> With icon
            </Button>
            <Button disabled>Disabled</Button>
          </Row>
        </Section>

        <Section title="Badges & tier">
          <Row label="Badge">
            <Badge variant="neutral">Neutral</Badge>
            <Badge variant="ok">Verified</Badge>
            <Badge variant="warn">Pending</Badge>
            <Badge variant="danger">Mismatch</Badge>
            <Badge variant="recovered">Recovered</Badge>
            <Badge variant="ai">AI draft</Badge>
            <Badge variant="brand">Brand</Badge>
          </Row>
          <Row label="Tier badge">
            <TierBadge tier="A" />
            <TierBadge tier="B" />
            <TierBadge tier="C" />
          </Row>
        </Section>

        <Section title="Integrity chip">
          <Row label="States">
            <IntegrityChip state="verified" hash="a41f09c2b8d3e6710f4c9a2b5e8d1f0c3a6b9e2d5f8c1a4b7e0d3f6c9a2b5e1d9e1d" />
            <IntegrityChip state="pending" hash="7c21e0a4f6b9c2d5e8f1a4b7c0d3e6f9a2b5c8d1e4f7a0b3c6d9e2f5a8b1c419bd" />
            <IntegrityChip state="mismatch" hash="3f1a9c2e7b4d6810f2c5a8e1b4d7f0a3c6b9e2d5f8c1a4b7e0d3f6c9a2b5e1d1a3f" />
          </Row>
        </Section>

        <Section title="Lineage breadcrumb">
          <LineageBreadcrumb
            segments={[
              { label: "hiksim_disk01.e01", to: "/design" },
              { label: "Image", to: "/design" },
              { label: "Scan run #1", to: "/design" },
              { label: "CH3 Counter", to: "/design" },
              { label: "Frame 00182" },
            ]}
          />
        </Section>

        <Section title="Custody seal">
          <CustodySeal ok entryCount={131} headHash="7c21e0a4f6b9c2d5e8f1a4b7c0d3e6f919bd" anchoredAtIso="2026-03-18T08:52:00Z" className="rounded-[var(--radius-card)] border" />
          <div className="mt-2">
            <CustodySeal ok={false} entryCount={131} headHash="7c21e0a4f6b9c2d5e8f1a4b7c0d3e6f919bd" anchoredAtIso="2026-03-18T08:52:00Z" className="rounded-[var(--radius-card)] border" />
          </div>
        </Section>

        <Section title="Clock stack">
          <ClockStack
            chosenKey="normalised"
            readings={[
              { key: "header", label: "Frame header", iso: "2026-03-12T08:32:37.480Z", confidence: 0.99 },
              { key: "index", label: "Index", iso: "2026-03-12T08:32:37.000Z", confidence: 0.95 },
              { key: "osd", label: "On-screen OCR", iso: "2026-03-12T08:33:14.480Z", confidence: 0.82, offsetLabel: "+37s OSD drift" },
              { key: "normalised", label: "Normalised IST", iso: "2026-03-12T08:32:37.480Z", confidence: 0.97 },
            ]}
          />
        </Section>

        <Section title="AI draft block">
          <AIDraftBlock
            sentences={[
              {
                text: "Recovered 214 frames on channel 3 (14:02–14:47 IST) from unindexed space.",
                evidenceIds: ["find_format01", "rec_031"],
              },
            ]}
          />
        </Section>

        <Section title="Job log">
          <JobLog
            pct={62}
            stages={[
              { name: "hash_verify", status: "done", pct: 100, message: "sha256 + md5 match" },
              { name: "identify", status: "done", pct: 100, message: "hiksim, tier A" },
              { name: "carve", status: "running", pct: 44, message: "sector sweep 44%" },
              { name: "clips", status: "pending", pct: 0, message: null },
            ]}
            logLines={["[10:05:01] hash_verify: sha256 match", "[10:11:44] identify: matched hiksim"]}
          />
        </Section>

        <Section title="Form controls">
          <Row label="Input">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="gallery-input">Label</Label>
              <Input id="gallery-input" placeholder="Placeholder" />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="gallery-input-disabled">Disabled</Label>
              <Input id="gallery-input-disabled" placeholder="Disabled" disabled />
            </div>
          </Row>
          <Row label="Select">
            <Select defaultValue="a">
              <SelectTrigger className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="a">Tier A · parsed</SelectItem>
                <SelectItem value="b">Tier B · inferred</SelectItem>
                <SelectItem value="c">Tier C · carved</SelectItem>
              </SelectContent>
            </Select>
          </Row>
          <Row label="Tabs">
            <Tabs defaultValue="one" className="w-full">
              <TabsList>
                <TabsTrigger value="one">Overview</TabsTrigger>
                <TabsTrigger value="two">Evidence</TabsTrigger>
                <TabsTrigger value="three">Findings</TabsTrigger>
              </TabsList>
              <TabsContent value="one" className="text-xs text-text-2">
                Overview panel content.
              </TabsContent>
              <TabsContent value="two" className="text-xs text-text-2">
                Evidence panel content.
              </TabsContent>
              <TabsContent value="three" className="text-xs text-text-2">
                Findings panel content.
              </TabsContent>
            </Tabs>
          </Row>
          <Row label="Tooltip">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="secondary" size="sm">
                  Hover me
                </Button>
              </TooltipTrigger>
              <TooltipContent>Copy full hash</TooltipContent>
            </Tooltip>
          </Row>
          <Row label="Dropdown">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="secondary" size="sm">
                  Actions
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuLabel>Evidence</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem>
                  <Search /> View
                </DropdownMenuItem>
                <DropdownMenuItem>
                  <Mail /> Share
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </Row>
          <Row label="Dialog">
            <Dialog>
              <DialogTrigger asChild>
                <Button variant="secondary" size="sm">
                  Open dialog
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Confirm layout</DialogTitle>
                  <DialogDescription>Accept the Tier B inferred layout for this image.</DialogDescription>
                </DialogHeader>
                <DialogFooter>
                  <Button variant="ghost">Cancel</Button>
                  <Button>Confirm</Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </Row>
          <Row label="Toast">
            <Button variant="secondary" size="sm" onClick={() => setToastOpen(true)}>
              Show toast
            </Button>
            {toastOpen && (
              <Toast variant="ok" open={toastOpen} onOpenChange={setToastOpen} className="static w-72">
                <div>
                  <ToastTitle>Evidence verified</ToastTitle>
                  <ToastDescription>sha256 recomputed and matches.</ToastDescription>
                </div>
              </Toast>
            )}
          </Row>
        </Section>

        <Section title="Progress & skeleton">
          <Row label="Progress">
            <Progress value={62} className="w-48" />
          </Row>
          <Row label="Skeleton">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-8 w-8 rounded-full" />
          </Row>
        </Section>

        <Section title="Table">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Channel</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Duration</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell>CH1 Gate</TableCell>
                <TableCell>index</TableCell>
                <TableCell className="tabular-nums">4h 00m</TableCell>
              </TableRow>
              <TableRow>
                <TableCell>CH3 Counter</TableCell>
                <TableCell>carved</TableCell>
                <TableCell className="tabular-nums">3h 34m</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </Section>

        <Section title="Channel palette">
          <div className="flex flex-wrap gap-2">
            {["ch-1", "ch-2", "ch-3", "ch-4", "ch-5", "ch-6", "ch-7", "ch-8"].map((c) => (
              <div key={c} className="flex flex-col items-center gap-1">
                <div className="size-8 rounded-[var(--radius-control)]" style={{ background: `var(--${c})` }} />
                <span className="font-mono text-[10px] text-text-3">{c}</span>
              </div>
            ))}
          </div>
        </Section>
      </div>
    </ScreenShell>
  );
}
