import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-caption",
  {
    variants: {
      variant: {
        neutral: "bg-control text-text-2 border-line-strong",
        ok: "bg-[var(--ok-tint)] text-ok border-[color-mix(in_oklab,var(--ok)_40%,transparent)]",
        warn: "bg-[var(--warn-tint)] text-warn border-[color-mix(in_oklab,var(--warn)_40%,transparent)]",
        danger: "bg-[var(--danger-tint)] text-danger border-[color-mix(in_oklab,var(--danger)_40%,transparent)]",
        recovered:
          "bg-[var(--recovered-tint)] text-recovered border-[color-mix(in_oklab,var(--recovered)_40%,transparent)]",
        ai: "bg-[var(--ai-tint)] text-ai border-[color-mix(in_oklab,var(--ai)_40%,transparent)]",
        brand:
          "bg-[var(--brand-900)] text-[var(--brand-400)] border-[color-mix(in_oklab,var(--brand-500)_40%,transparent)]",
      },
    },
    defaultVariants: { variant: "neutral" },
  },
);

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
