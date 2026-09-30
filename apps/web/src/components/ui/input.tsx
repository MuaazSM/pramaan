import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type, ...props }, ref) => (
    <input
      type={type}
      ref={ref}
      className={cn(
        "focus-ring flex h-8 w-full rounded-[var(--radius-control)] border border-line-strong bg-control px-2.5 text-base text-text placeholder:text-text-3",
        "transition-colors duration-[var(--dur-fast)] ease-[var(--ease)]",
        "disabled:opacity-40 disabled:cursor-not-allowed",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export const Label = React.forwardRef<HTMLLabelElement, React.LabelHTMLAttributes<HTMLLabelElement>>(
  ({ className, ...props }, ref) => (
    <label ref={ref} className={cn("text-label text-text-2", className)} {...props} />
  ),
);
Label.displayName = "Label";
