import * as React from "react";
import * as ToastPrimitive from "@radix-ui/react-toast";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useToast } from "./use-toast";

export const ToastProvider = ToastPrimitive.Provider;
export const ToastViewport = React.forwardRef<
  React.ElementRef<typeof ToastPrimitive.Viewport>,
  React.ComponentPropsWithoutRef<typeof ToastPrimitive.Viewport>
>(({ className, ...props }, ref) => (
  <ToastPrimitive.Viewport
    ref={ref}
    className={cn("fixed bottom-0 right-0 z-[100] flex w-[380px] max-w-full flex-col gap-2 p-4", className)}
    {...props}
  />
));
ToastViewport.displayName = "ToastViewport";

const VARIANT_BORDER: Record<string, string> = {
  default: "border-line-strong",
  ok: "border-[color-mix(in_oklab,var(--ok)_50%,transparent)]",
  danger: "border-[color-mix(in_oklab,var(--danger)_50%,transparent)]",
};

export const Toast = React.forwardRef<
  React.ElementRef<typeof ToastPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ToastPrimitive.Root> & { variant?: "default" | "ok" | "danger" }
>(({ className, variant = "default", ...props }, ref) => (
  <ToastPrimitive.Root
    ref={ref}
    className={cn(
      "relative flex items-start gap-3 rounded-[var(--radius-card)] border bg-panel p-3 shadow-[var(--shadow-pop)]",
      "data-[state=open]:animate-in data-[state=open]:slide-in-from-bottom-2 data-[state=closed]:animate-out data-[state=closed]:fade-out duration-[var(--dur-base)]",
      VARIANT_BORDER[variant],
      className,
    )}
    {...props}
  />
));
Toast.displayName = "Toast";

export function ToastTitle({ className, ...props }: ToastPrimitive.ToastTitleProps) {
  return <ToastPrimitive.Title className={cn("text-base font-medium text-text", className)} {...props} />;
}
export function ToastDescription({ className, ...props }: ToastPrimitive.ToastDescriptionProps) {
  return <ToastPrimitive.Description className={cn("text-sm text-text-2", className)} {...props} />;
}
export function ToastClose({ className, ...props }: ToastPrimitive.ToastCloseProps) {
  return (
    <ToastPrimitive.Close className={cn("focus-ring absolute right-2 top-2 text-text-3 hover:text-text", className)} {...props}>
      <X size={14} strokeWidth={1.5} />
    </ToastPrimitive.Close>
  );
}

/**
 * Renders the `useToast()` queue as actual `<Toast>` instances. Added by F2: `useToast()`/`toast()`
 * existed (used by F1's intake wizard and now F2's scan/confirm-layout mutations) but nothing ever
 * consumed the queue and rendered it — calling `toast()` was a silent no-op app-wide. Mounted once
 * in `src/routes/__root.tsx` alongside `<ToastViewport>`. See docs/progress/F2.md "Decisions".
 */
export function Toaster() {
  const { toasts, dismiss } = useToast();
  return (
    <>
      {toasts.map((t) => (
        <Toast
          key={t.id}
          variant={t.variant}
          open
          onOpenChange={(open) => {
            if (!open) dismiss(t.id);
          }}
        >
          <div className="flex-1">
            <ToastTitle>{t.title}</ToastTitle>
            {t.description && <ToastDescription>{t.description}</ToastDescription>}
          </div>
          <ToastClose />
        </Toast>
      ))}
    </>
  );
}
