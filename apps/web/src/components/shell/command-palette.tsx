import { useEffect, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { useUiStore } from "@/store/ui";
import { AssistantPanel } from "@/features/assistant/assistant-panel";
import { LayoutGrid, HardDrive, PlaySquare, FileText, Sun, Moon, FolderKanban, Settings, Sparkles } from "lucide-react";

/**
 * Global command palette (⌘K / Ctrl K): navigation + actions, matches every object the examiner
 * needs to reach without a mouse (UI_REFERENCES.md — Raycast/Linear pattern).
 */
export function CommandPalette({ caseId }: { caseId?: string }) {
  const open = useUiStore((s) => s.commandPaletteOpen);
  const setOpen = useUiStore((s) => s.setCommandPaletteOpen);
  const toggleTheme = useUiStore((s) => s.toggleTheme);
  const navigate = useNavigate();
  // "nav" = the command list; "assistant" = the "Ask about this case" panel swapped in place of it.
  const [view, setView] = useState<"nav" | "assistant">("nav");

  // Always reopen on the command list, however the dialog was closed (Esc, item, ⌘K toggle, click-out).
  useEffect(() => {
    if (!open) setView("nav");
  }, [open]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(!open);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, setOpen]);

  function go(to: string) {
    setOpen(false);
    void navigate({ to });
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        className="max-w-xl translate-y-[-30%] p-0"
        aria-describedby={undefined}
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        {view === "assistant" && caseId ? (
          <AssistantPanel caseId={caseId} onClose={() => setOpen(false)} onBack={() => setView("nav")} />
        ) : (
          <Command shouldFilter>
            <CommandInput placeholder="Search cases, evidence, recordings, or jump to a timecode…" autoFocus />
            <CommandList>
              <CommandEmpty>No results.</CommandEmpty>
              <CommandGroup heading="Navigate">
                <CommandItem onSelect={() => go("/cases")}>
                  <FolderKanban /> All cases
                </CommandItem>
                {caseId && (
                  <>
                    <CommandItem onSelect={() => go(`/cases/${caseId}`)}>
                      <LayoutGrid /> Case overview
                    </CommandItem>
                    <CommandItem onSelect={() => go(`/cases/${caseId}/evidence/new`)}>
                      <HardDrive /> Add evidence
                    </CommandItem>
                    <CommandItem onSelect={() => go(`/cases/${caseId}/review`)}>
                      <PlaySquare /> Open review workspace
                    </CommandItem>
                    <CommandItem onSelect={() => go(`/cases/${caseId}/reports`)}>
                      <FileText /> Reports
                    </CommandItem>
                  </>
                )}
                <CommandItem onSelect={() => go("/settings")}>
                  <Settings /> Settings
                </CommandItem>
              </CommandGroup>
              {caseId && (
                <CommandGroup heading="Assistant">
                  <CommandItem onSelect={() => setView("assistant")}>
                    <Sparkles /> Ask about this case
                  </CommandItem>
                </CommandGroup>
              )}
              <CommandGroup heading="Actions">
                <CommandItem
                  onSelect={() => {
                    toggleTheme();
                    setOpen(false);
                  }}
                >
                  <Sun className="dark:hidden" />
                  <Moon className="hidden dark:block" />
                  Toggle theme
                </CommandItem>
              </CommandGroup>
            </CommandList>
          </Command>
        )}
      </DialogContent>
    </Dialog>
  );
}
