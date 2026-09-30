import * as React from "react";
import { cn } from "@/lib/utils";

export function Table({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-auto rounded-[var(--radius-card)] border border-line">
      <table className={cn("w-full caption-bottom text-base", className)} {...props} />
    </div>
  );
}

export function TableHeader({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn("sticky top-0 z-10 bg-panel", className)} {...props} />;
}

export function TableBody({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn("[&_tr:last-child]:border-0", className)} {...props} />;
}

export function TableRow({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn(
        "border-b border-line transition-colors duration-[var(--dur-fast)] hover:bg-card data-[state=selected]:bg-[var(--selected)]",
        className,
      )}
      {...props}
    />
  );
}

export function TableHead({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  // F6: uppercase kept here only — the one deliberate exception to "no uppercase micro-labels"
  // (docs/progress/F6.md "BRAND.md conventions kept over the skill's advice" #1). A dense,
  // mixed-width data table needs its header row to read as structurally different from rows at a
  // glance; tracking-wide widens further than the caption role's default to carry that at 11px.
  return (
    <th
      className={cn(
        "h-9 whitespace-nowrap px-3 text-left align-middle text-caption uppercase tracking-[0.04em] text-text-2",
        className,
      )}
      {...props}
    />
  );
}

export function TableCell({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("whitespace-nowrap px-3 py-2.5 align-middle text-text", className)} {...props} />;
}
