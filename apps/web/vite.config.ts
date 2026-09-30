import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import path from "node:path";

// Pramaan web — Vite config. See docs/04-FRONTEND.md §2 for the stack.
export default defineConfig({
  plugins: [
    tanstackRouter({ target: "react", autoCodeSplitting: true, routesDirectory: "./src/routes" }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      // `ws: true` additionally upgrades `/api/ws` (docs/02-BACKEND.md §7) — Vite's http-proxy
      // does not proxy WebSocket upgrades on a bare string target. Added by F2 (evidence detail's
      // pipeline panel binds to this socket in real mode too); see docs/progress/F2.md "Decisions".
      "/api": { target: "http://localhost:8000", ws: true },
    },
  },
  build: {
    sourcemap: true,
  },
});
