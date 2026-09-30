import * as React from "react";
import * as DropdownPrimitive from "@radix-ui/react-dropdown-menu";
import { Check, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

export const DropdownMenu = DropdownPrimitive.Root;
export const DropdownMenuTrigger = DropdownPrimitive.Trigger;
export const DropdownMenuGroup = DropdownPrimitive.Group;
export const DropdownMenuSub = DropdownPrimitive.Sub;
export const DropdownMenuSubTrigger = DropdownPrimitive.SubTrigger;
export const DropdownMenuRadioGroup = DropdownPrimitive.RadioGroup;

export function DropdownMenuContent({ className, sideOffset = 6, ...props }: DropdownPrimitive.DropdownMenuContentProps) {
  return (
    <DropdownPrimitive.Portal>
      <DropdownPrimitive.Content
        sideOffset={sideOffset}
        className={cn(
          "z-50 min-w-[180px] rounded-[var(--radius-card)] border border-line-strong bg-panel p-1 shadow-[var(--shadow-pop)]",
          "data-[state=open]:animate-in data-[state=open]:fade-in data-[state=open]:zoom-in-95 duration-[var(--dur-fast)]",
          className,
        )}
        {...props}
      />
    </DropdownPrimitive.Portal>
  );
}

export function DropdownMenuItem({ className, ...props }: DropdownPrimitive.DropdownMenuItemProps) {
  return (
    <DropdownPrimitive.Item
      className={cn(
        "focus-ring flex cursor-pointer items-center gap-2 rounded-[var(--radius-control)] px-2 py-1.5 text-base text-text outline-none",
        "data-[highlighted]:bg-control data-[disabled]:opacity-40 [&_svg]:size-4",
        className,
      )}
      {...props}
    />
  );
}

export function DropdownMenuCheckboxItem({
  className,
  children,
  checked,
  ...props
}: DropdownPrimitive.DropdownMenuCheckboxItemProps) {
  return (
    <DropdownPrimitive.CheckboxItem
      checked={checked}
      className={cn(
        "focus-ring relative flex cursor-pointer items-center gap-2 rounded-[var(--radius-control)] py-1.5 pl-7 pr-2 text-base text-text outline-none data-[highlighted]:bg-control",
        className,
      )}
      {...props}
    >
      <span className="absolute left-2 flex size-4 items-center justify-center">
        <DropdownPrimitive.ItemIndicator>
          <Check size={14} strokeWidth={1.5} />
        </DropdownPrimitive.ItemIndicator>
      </span>
      {children}
    </DropdownPrimitive.CheckboxItem>
  );
}

export function DropdownMenuLabel({ className, ...props }: DropdownPrimitive.DropdownMenuLabelProps) {
  return <DropdownPrimitive.Label className={cn("px-2 py-1 text-caption text-text-2", className)} {...props} />;
}

export function DropdownMenuSeparator({ className, ...props }: DropdownPrimitive.DropdownMenuSeparatorProps) {
  return <DropdownPrimitive.Separator className={cn("my-1 h-px bg-line-strong", className)} {...props} />;
}

export function DropdownMenuShortcut({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) {
  return <span className={cn("ml-auto font-data text-caption text-text-2", className)} {...props} />;
}

export { ChevronRight as DropdownMenuSubTriggerIcon };
