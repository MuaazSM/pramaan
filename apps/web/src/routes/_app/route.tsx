import { createFileRoute, Outlet, redirect, useParams } from "@tanstack/react-router";
import { Sidebar } from "@/components/shell/sidebar";
import { CommandPalette } from "@/components/shell/command-palette";
import { JobDrawer } from "@/components/shell/job-drawer";
import { useAuthStore } from "@/store/auth";
import { api } from "@/api/client";

/**
 * Pathless layout for every authenticated screen: sidebar + command palette + job drawer.
 * The top bar itself is rendered per-screen (it needs the screen's own lineage breadcrumb),
 * via the <ScreenShell> helper in src/components/shell/screen-shell.tsx.
 */
export const Route = createFileRoute("/_app")({
  beforeLoad: async () => {
    if (useAuthStore.getState().user) return;
    const { data, error } = await api.GET("/api/me");
    if (error || !data) {
      throw redirect({ to: "/login" });
    }
    useAuthStore.getState().setUser(data);
  },
  component: AppLayout,
});

function AppLayout() {
  // Best-effort case id from the URL, used to scope the sidebar nav + job drawer + palette.
  const params = useParams({ strict: false }) as { cid?: string };
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-bg text-text">
      <Sidebar caseId={params.cid} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Outlet />
      </div>
      <CommandPalette caseId={params.cid} />
      <JobDrawer caseId={params.cid} />
    </div>
  );
}
