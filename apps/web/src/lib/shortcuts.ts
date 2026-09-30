/**
 * Single source of truth for every keyboard shortcut in the app (docs/04-FRONTEND.md §1.4:
 * "shortcuts shown in menus and tooltips"). The shortcut sheet (`?`, shell/shortcut-sheet.tsx)
 * renders this list; individual screens can import `SHORTCUT_GROUPS` too instead of hard-coding
 * key labels in their own tooltips, so the two never drift apart.
 */
export interface ShortcutEntry {
  keys: string[];
  description: string;
}

export interface ShortcutGroup {
  title: string;
  shortcuts: ShortcutEntry[];
}

export const SHORTCUT_GROUPS: ShortcutGroup[] = [
  {
    title: "Global",
    shortcuts: [
      { keys: ["⌘", "K"], description: "Open the command palette (navigate anywhere, ask about this case)" },
      { keys: ["?"], description: "Show this shortcut sheet" },
      { keys: ["Esc"], description: "Close the command palette, this sheet, or the job drawer" },
    ],
  },
  {
    title: "Review workspace",
    shortcuts: [
      { keys: ["J"], description: "Shuttle backward (press again to speed up)" },
      { keys: ["K"], description: "Pause" },
      { keys: ["L"], description: "Shuttle forward (press again to speed up)" },
      { keys: ["Space"], description: "Play / pause" },
      { keys: ["→"], description: "Step forward one frame" },
      { keys: ["←"], description: "Step back one frame" },
      { keys: ["Shift", "→"], description: "Step forward one second" },
      { keys: ["Shift", "←"], description: "Step back one second" },
      { keys: ["G"], description: "Jump to a timecode, IST datetime, or #frame id" },
    ],
  },
];
