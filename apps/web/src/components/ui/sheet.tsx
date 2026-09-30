import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const Sheet = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;
export const SheetClose = DialogPrimitive.Close;

interface SheetContentProps extends DialogPrimitive.DialogContentProps {
  side?: "right" | "left";
  widthClassName?: string;
}

/** Right/left side panel (shadcn "Sheet"). Used by the job drawer and inspector panels. */
export function SheetContent({
  className,
  children,
  side = "right",
  widthClassName = "w-[420px]",
  ...props
}: SheetContentProps) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/50" />
      <DialogPrimitive.Content
        className={cn(
          "fixed top-0 z-50 h-full border-line-strong bg-panel p-5 shadow-[var(--shadow-pop)] focus-ring flex flex-col",
          side === "right" ? "right-0 border-l" : "left-0 border-r",
          widthClassName,
          "data-[state=open]:animate-in data-[state=closed]:animate-out duration-[var(--dur-base)]",
          side === "right"
            ? "data-[state=open]:slide-in-from-right data-[state=closed]:slide-out-to-right"
            : "data-[state=open]:slide-in-from-left data-[state=closed]:slide-out-to-left",
          className,
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close className="focus-ring absolute right-4 top-4 rounded-[var(--radius-control)] p-1 text-text-3 hover:bg-control hover:text-text">
          <X size={16} strokeWidth={1.5} />
          <span className="sr-only">Close</span>
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export function SheetHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mb-4 flex flex-col gap-1 pr-6", className)} {...props} />;
}

export function SheetTitle({ className, ...props }: DialogPrimitive.DialogTitleProps) {
  return <DialogPrimitive.Title className={cn("text-section text-text", className)} {...props} />;
}
