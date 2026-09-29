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
      "/api": "http://localhost:8000",
    },
  },
  build: {
    sourcemap: true,
  },
});
