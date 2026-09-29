import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createRouter } from "@tanstack/react-router";
import "./styles/app.css";
import { routeTree } from "./routeTree.gen";
import { useUiStore } from "@/store/ui";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 10_000 } },
});

const router = createRouter({ routeTree, context: { queryClient } });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

// Apply persisted theme before first paint.
document.documentElement.setAttribute("data-theme", useUiStore.getState().theme);

async function bootstrap() {
  if (import.meta.env.VITE_MOCK === "1") {
    const { worker } = await import("./mocks/browser");
    await worker.start({ onUnhandledRequest: "bypass" });
  }

  const rootEl = document.getElementById("root");
  if (!rootEl) throw new Error("#root not found");
  createRoot(rootEl).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StrictMode>,
  );
}

void bootstrap();
