/**
 * Field decoder: lists every annotated region (docs/04-FRONTEND.md §5 route table: "vendor header
 * fields, start code, NAL header, payload") with its offset/length/sector and, where the bytes
 * support an honest decode (Annex-B start code, NAL unit header — public H.264/H.265 structure,
 * not vendor-specific), the decoded value. The vendor header itself is never fabricated a field
 * map for — see codec-decode.ts's module comment and CLAUDE.md rule 7.
 */
import { Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { decodeStartCode, decodeNalHeader } from "../lib/codec-decode";
import { bytesToHex, sliceAnnotation, sectorForOffset, type HexAnnotation } from "../lib/hex-annotate";

const KIND_LABEL: Record<HexAnnotation["kind"], string> = {
  header: "Vendor header",
  start_code: "Start code",
  payload: "Payload",
  field: "Field",
};

const KIND_DOT: Record<HexAnnotation["kind"], string> = {
  header: "var(--ch-1)",
  start_code: "var(--ch-6)",
  payload: "var(--ch-2)",
  field: "var(--ch-8)",
};

export function FieldDecoder({
  bytes,
  annotations,
  codec,
  hoveredName,
  onHover,
}: {
  bytes: Uint8Array;
  annotations: HexAnnotation[];
  codec: "h264" | "h265";
  hoveredName: string | null;
  onHover: (name: string | null) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      {annotations.map((a) => (
        <button
          key={a.name}
          type="button"
          onMouseEnter={() => onHover(a.name)}
          onMouseLeave={() => onHover(null)}
          onFocus={() => onHover(a.name)}
          onBlur={() => onHover(null)}
          className={cn(
            "focus-ring flex flex-col gap-1 rounded-[var(--radius-control)] border px-2.5 py-2 text-left transition-colors duration-[var(--dur-fast)]",
            hoveredName === a.name ? "border-[color-mix(in_oklab,var(--brand-500)_45%,transparent)] bg-[var(--selected)]" : "border-line bg-card",
          )}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-sm font-medium text-text">
              <span className="size-2 rounded-sm" style={{ backgroundColor: KIND_DOT[a.kind] }} aria-hidden />
              {KIND_LABEL[a.kind]}
            </span>
            <span className="font-data text-caption tabular-nums text-text-3">{a.length}B</span>
          </div>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5 font-data text-caption text-text-2">
            <Row label="Offset" value={`0x${a.absoluteStart.toString(16)} (${a.absoluteStart.toLocaleString()})`} />
            <Row label="Sector" value={`${sectorForOffset(a.absoluteStart)}`} />
          </dl>
          <FieldDecode annotation={a} bytes={bytes} codec={codec} />
        </button>
      ))}
    </div>
  );
}

function FieldDecode({ annotation, bytes, codec }: { annotation: HexAnnotation; bytes: Uint8Array; codec: "h264" | "h265" }) {
  if (annotation.kind === "start_code") {
    const raw = sliceAnnotation(bytes, annotation);
    const decoded = decodeStartCode(raw);
    return (
      <p className={cn("mt-0.5 flex items-start gap-1 text-sm", decoded.isAnnexB ? "text-text" : "text-text-3")}>
        <Info size={11} strokeWidth={1.75} className="mt-0.5 shrink-0" />
        {decoded.label}
      </p>
    );
  }
  if (annotation.kind === "payload") {
    const raw = sliceAnnotation(bytes, annotation);
    const nal = decodeNalHeader(raw, codec);
    return (
      <p className="mt-0.5 flex items-start gap-1 text-sm text-text">
        <Info size={11} strokeWidth={1.75} className="mt-0.5 shrink-0 text-text-3" />
        {nal
          ? `First payload byte(s) (${nal.bytes}) decode as NAL unit type ${nal.nalUnitType} — ${nal.typeName}, per Annex-B convention.`
          : "Payload too short to decode a NAL unit header."}
      </p>
    );
  }
  if (annotation.kind === "header") {
    return (
      <p className="mt-0.5 flex items-start gap-1 text-sm text-text-3">
        <Info size={11} strokeWidth={1.75} className="mt-0.5 shrink-0" />
        {"Vendor-specific layout — offsets are known from the format parser; individual field semantics are not exposed by this endpoint. First bytes: "}
        <span className="font-data">{bytesToHex(sliceAnnotation(bytes, annotation).slice(0, 8))}</span>
      </p>
    );
  }
  return null;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="contents">
      <dt className="text-text-3">{label}</dt>
      <dd className="text-right text-text">{value}</dd>
    </div>
  );
}
