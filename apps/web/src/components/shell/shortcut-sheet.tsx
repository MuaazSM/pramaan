import { useEffect } from "react";
import { Keyboard } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { useUiStore } from "@/store/ui";
import { isTypingTarget } from "@/lib/utils";
import { SHORTCUT_GROUPS } from "@/lib/shortcuts";

/**
 * Keyboard shortcut sheet — opens on `?` from anywhere in the app (docs/04-FRONTEND.md §1.4:
 * "shortcuts shown in menus and tooltips"; F5 task brief: "Keyboard shortcut sheet (`?`) listing
 * all shortcuts"). Mounted once, app-wide, in `_app/route.tsx` — same pattern as `CommandPalette`
 * owning its own `⌘K` listener.
 */
export function ShortcutSheet() {
  const open = useUiStore((s) => s.shortcutSheetOpen);
  const setOpen = useUiStore((s) => s.setShortcutSheetOpen);
  const commandPaletteOpen = useUiStore((s) => s.commandPaletteOpen);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== "?") return;
      if (isTypingTarget(e.target)) return;
      if (commandPaletteOpen) return; // don't fight ⌘K's own "?" typed into its search input
      e.preventDefault();
      setOpen(!open);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, setOpen, commandPaletteOpen]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-lg" aria-describedby="shortcut-sheet-description">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <Keyboard size={16} strokeWidth={1.75} className="text-text-3" />
            <DialogTitle>Keyboard shortcuts</DialogTitle>
          </div>
          <DialogDescription id="shortcut-sheet-description">
            Every action reachable without a mouse. Ignored while typing in a field.
          </DialogDescription>
        </DialogHeader>

        <div className="flex max-h-[60vh] flex-col gap-5 overflow-y-auto pr-1">
          {SHORTCUT_GROUPS.map((group) => (
            <div key={group.title}>
              <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-text-3">{group.title}</h3>
              <ul className="flex flex-col gap-2">
                {group.shortcuts.map((s) => (
                  <li key={s.description} className="flex items-center justify-between gap-4 text-[13px]">
                    <span className="text-text-2">{s.description}</span>
                    <span className="flex shrink-0 items-center gap-1">
                      {s.keys.map((k, i) => (
                        <span key={i} className="flex items-center gap-1">
                          {i > 0 && <span className="text-text-3">+</span>}
                          <kbd className="min-w-[1.5rem] rounded border border-line-strong bg-control px-1.5 py-0.5 text-center font-mono text-[11px] text-text">
                            {k}
                          </kbd>
                        </span>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
