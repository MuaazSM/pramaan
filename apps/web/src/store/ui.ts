import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Density = "comfortable" | "compact";
export type Theme = "dark" | "light";

interface UiState {
  theme: Theme;
  density: Density;
  sidebarCollapsed: boolean;
  commandPaletteOpen: boolean;
  jobDrawerOpen: boolean;
  shortcutSheetOpen: boolean;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  setDensity: (density: Density) => void;
  toggleSidebar: () => void;
  setCommandPaletteOpen: (open: boolean) => void;
  setJobDrawerOpen: (open: boolean) => void;
  setShortcutSheetOpen: (open: boolean) => void;
}

/** Shell-wide UI state: theme, density, sidebar, command palette, job drawer. Persisted locally. */
export const useUiStore = create<UiState>()(
  persist(
    (set, get) => ({
      theme: "dark",
      density: "comfortable",
      sidebarCollapsed: false,
      commandPaletteOpen: false,
      jobDrawerOpen: false,
      shortcutSheetOpen: false,
      setTheme: (theme) => {
        set({ theme });
        document.documentElement.setAttribute("data-theme", theme);
      },
      toggleTheme: () => {
        get().setTheme(get().theme === "dark" ? "light" : "dark");
      },
      setDensity: (density) => set({ density }),
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),
      setJobDrawerOpen: (open) => set({ jobDrawerOpen: open }),
      setShortcutSheetOpen: (open) => set({ shortcutSheetOpen: open }),
    }),
    { name: "pramaan-ui" },
  ),
);
