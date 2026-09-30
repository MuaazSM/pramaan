import { CircleAlert, Lock, SearchX, ServerCrash, ShieldAlert, WifiOff } from "lucide-react";
import { cn } from "@/lib/utils";
import { classifyError } from "@/lib/api-error";

/**
 * Shared error state for a failed screen/panel query (F5 empty/error/loading audit —
 * docs/04-FRONTEND.md §1.6 "every state designed"). Renders distinct, honest copy per
 * `classifyError` outcome instead of one generic "could not be found" message for every failure
 * mode — see `src/lib/api-error.ts`'s module comment for why that was actively misleading.
 *
 * `subject` is a lowercase noun phrase completing "couldn't load ___" / "don't have access to
 * ___" (e.g. "this case", "the audit log", "recordings").
 */
export function QueryErrorState({
  error,
  subject,
  onRetry,
  className,
}: {
  error: unknown;
  subject: string;
  onRetry?: () => void;
  className?: string;
}) {
  const kind = classifyError(error);
  const { Icon, title, detail } = COPY[kind](subject);
  return (
    <div className={cn("flex flex-col items-center gap-3 py-16 text-center", className)}>
      <Icon size={22} strokeWidth={1.5} className="text-text-3" />
      <div className="flex flex-col gap-1">
        <p className="text-[13px] font-medium text-text">{title}</p>
        <p className="max-w-sm text-xs text-text-2">{detail}</p>
      </div>
      {onRetry && kind !== "forbidden" && kind !== "not_found" && (
        <button
          type="button"
          onClick={onRetry}
          className="focus-ring mt-1 rounded-[var(--radius-control)] border border-line-strong px-2.5 py-1 text-xs text-text-2 hover:bg-control hover:text-text"
        >
          Try again
        </button>
      )}
    </div>
  );
}

const COPY: Record<ReturnType<typeof classifyError>, (subject: string) => { Icon: typeof CircleAlert; title: string; detail: string }> = {
  network: (subject) => ({
    Icon: WifiOff,
    title: "Can't reach the Pramaan API",
    detail: `The backend didn't respond while loading ${subject}. Check that it's running and try again.`,
  }),
  unauthorized: () => ({
    Icon: Lock,
    title: "Session expired",
    detail: "Sign in again to continue — you'll be sent to the login screen.",
  }),
  forbidden: (subject) => ({
    Icon: ShieldAlert,
    title: "Not permitted",
    detail: `Your role doesn't have access to ${subject}.`,
  }),
  not_found: (subject) => ({
    Icon: SearchX,
    title: "Not found",
    detail: `${capitalize(subject)} could not be found. It may have been removed, or the link is wrong.`,
  }),
  server: (subject) => ({
    Icon: ServerCrash,
    title: "Server error",
    detail: `Something went wrong on the server while loading ${subject}. Try again shortly.`,
  }),
  unknown: (subject) => ({
    Icon: CircleAlert,
    title: "Something went wrong",
    detail: `Couldn't load ${subject}. Try again.`,
  }),
};

function capitalize(s: string): string {
  return s.length ? s[0].toUpperCase() + s.slice(1) : s;
}
