import { create } from "zustand";
import type { components } from "@/api/schema.gen";

type Me = components["schemas"]["Me"];

interface AuthState {
  user: Me | null;
  setUser: (user: Me | null) => void;
}

/** Current session user, hydrated by /api/me on app load and set on login. */
export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  setUser: (user) => set({ user }),
}));
