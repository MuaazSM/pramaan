/**
 * /settings — Designed placeholder for this wave (full build: users/roles, keys, LLM budget
 * meter, system health). System health data is already live via GET /system/health; shown here
 * as a preview so the placeholder isn't empty.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Settings as SettingsIcon, Check, X } from "lucide-react";
import { ScreenShell } from "@/components/shell/screen-shell";
import { api } from "@/api/client";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/_app/settings")({
  component: SettingsScreen,
});

function SettingsScreen() {
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: async () => (await api.GET("/api/system/health")).data,
  });

  const rows = health
    ? [
        ["Scanner backend", health.scanner_backend],
        ["ffmpeg", health.ffmpeg],
        ["pyewf", health.pyewf],
        ["weasyprint", health.weasyprint],
        ["Fabric anchoring", health.fabric],
        ["LLM enabled", health.llm_enabled],
        ["Stub mode", health.stub_mode],
      ] as const
    : [];

  return (
    <ScreenShell segments={[{ label: "Settings" }]}>
      <div className="mx-auto flex max-w-2xl flex-col items-center gap-6 p-10 text-center">
        <div className="flex size-12 items-center justify-center rounded-[var(--radius-card)] border border-line-strong bg-control">
          <SettingsIcon size={22} strokeWidth={1.5} className="text-text-3" />
        </div>
        <div className="max-w-md">
          <h1 className="text-[16px] font-semibold text-text">Settings</h1>
          <p className="mt-1.5 text-[13px] text-text-2">
            Users and roles, keys, the LLM budget meter, and system health will live here. System health is already
            wired to the real endpoint:
          </p>
        </div>
        {rows.length > 0 && (
          <dl className="grid w-full grid-cols-2 gap-x-6 gap-y-2 rounded-[var(--radius-card)] border border-line bg-card p-4 text-left text-xs">
            {rows.map(([label, value]) => (
              <div key={label} className="col-span-2 grid grid-cols-2 items-center border-b border-line py-1.5 last:border-0">
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
        <span className="rounded-full border border-line-strong bg-control px-2.5 py-1 text-[11px] text-text-3">
          Designed placeholder · built by WEB (Wave 2)
        </span>
      </div>
    </ScreenShell>
  );
}
