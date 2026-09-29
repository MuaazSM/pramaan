import { Link, useMatchRoute } from "@tanstack/react-router";
import {
  LayoutGrid,
  HardDrive,
  PlaySquare,
  Video,
  ShieldAlert,
  FileText,
  PackageCheck,
  Landmark,
  Settings,
  ChevronsLeft,
  ChevronsRight,
  CircleDot,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/store/ui";
import { useAuthStore } from "@/store/auth";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useNavigate } from "@tanstack/react-router";
import { api } from "@/api/client";

const NAV_ITEMS = [
  { to: "/cases/$cid", label: "Overview", icon: LayoutGrid },
  { to: "/cases/$cid/evidence", label: "Evidence", icon: HardDrive },
  { to: "/cases/$cid/review", label: "Review", icon: PlaySquare },
  { to: "/cases/$cid/recordings", label: "Recordings", icon: Video },
  { to: "/cases/$cid/findings", label: "Findings", icon: ShieldAlert },
  { to: "/cases/$cid/reports", label: "Reports", icon: FileText },
  { to: "/cases/$cid/exports", label: "Exports", icon: PackageCheck },
  { to: "/cases/$cid/custody", label: "Custody", icon: Landmark },
] as const;

export function Sidebar({ caseId }: { caseId?: string }) {
  const collapsed = useUiStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUiStore((s) => s.toggleSidebar);
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const matchRoute = useMatchRoute();
  const navigate = useNavigate();

  async function logout() {
    await api.POST("/api/auth/logout");
    setUser(null);
    void navigate({ to: "/login" });
  }

  return (
    <aside
      className={cn(
        "flex h-full shrink-0 flex-col border-r border-line bg-panel transition-[width] duration-[var(--dur-base)] ease-[var(--ease)]",
        collapsed ? "w-14" : "w-60",
      )}
    >
      <div className="flex h-12 items-center gap-2 border-b border-line px-3">
        <Link to="/cases" className="focus-ring flex items-center gap-2 overflow-hidden rounded px-1">
          <svg width="20" height="20" viewBox="0 0 32 32" fill="none" className="shrink-0" aria-hidden>
            <path
              d="M16 2 L28 9 V23 L16 30 L4 23 V9 Z"
              stroke="var(--brand-400)"
              strokeWidth="2"
              fill="none"
            />
            <rect x="10" y="12" width="10" height="1.6" fill="var(--brand-400)" />
            <rect x="10" y="15.2" width="7" height="1.6" fill="var(--brand-400)" />
            <rect x="10" y="18.4" width="4" height="1.6" fill="var(--brand-400)" />
            <circle cx="22" cy="20" r="1.6" fill="var(--ok)" />
          </svg>
          {!collapsed && <span className="truncate text-[14px] font-semibold tracking-[-0.02em] text-text">pramaan</span>}
        </Link>
      </div>

      <nav className="flex-1 overflow-y-auto p-2">
        {caseId ? (
          <ul className="flex flex-col gap-0.5">
            {NAV_ITEMS.map((item) => {
              const to = item.to.replace("$cid", caseId);
              const active = Boolean(matchRoute({ to: item.to, params: { cid: caseId } as never, fuzzy: item.to !== "/cases/$cid" }));
              const Icon = item.icon;
              return (
                <li key={item.to}>
                  <Link
                    to={to}
                    className={cn(
                      "focus-ring flex items-center gap-2.5 rounded-[var(--radius-control)] px-2.5 py-1.5 text-[13px] transition-colors duration-[var(--dur-fast)]",
                      active ? "bg-[var(--selected)] text-accent-text" : "text-text-2 hover:bg-control hover:text-text",
                    )}
                    title={collapsed ? item.label : undefined}
                  >
                    <Icon size={16} strokeWidth={1.5} className="shrink-0" />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                  </Link>
                </li>
              );
            })}
          </ul>
        ) : (
          !collapsed && <p className="px-2.5 py-1.5 text-xs text-text-3">Open a case to see its navigation.</p>
        )}
      </nav>

      <div className="flex flex-col gap-0.5 border-t border-line p-2">
        <Link
          to="/settings"
          className="focus-ring flex items-center gap-2.5 rounded-[var(--radius-control)] px-2.5 py-1.5 text-[13px] text-text-2 hover:bg-control hover:text-text"
        >
          <Settings size={16} strokeWidth={1.5} />
          {!collapsed && <span>Settings</span>}
        </Link>
        <div className="flex items-center gap-2 px-2.5 py-1.5 text-xs text-text-3">
          <CircleDot size={12} strokeWidth={2} className="text-ok" />
          {!collapsed && <span>System healthy</span>}
        </div>
        {user && (
          <DropdownMenu>
            <DropdownMenuTrigger
              className="focus-ring flex items-center gap-2 rounded-[var(--radius-control)] px-2.5 py-1.5 text-left text-[13px] text-text hover:bg-control"
            >
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-[var(--brand-900)] text-[11px] font-medium text-[var(--brand-300)]">
                {user.display_name.slice(0, 1)}
              </span>
              {!collapsed && (
                <span className="flex min-w-0 flex-col">
                  <span className="truncate">{user.display_name}</span>
                  <span className="truncate text-[10px] text-text-3">{user.role}</span>
                </span>
              )}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" side="top">
              <DropdownMenuLabel>{user.username}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => void logout()}>Sign out</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
        <button
          type="button"
          onClick={toggleSidebar}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="focus-ring mt-1 flex items-center gap-2.5 rounded-[var(--radius-control)] px-2.5 py-1.5 text-text-3 hover:bg-control hover:text-text"
        >
          {collapsed ? <ChevronsRight size={16} strokeWidth={1.5} /> : <ChevronsLeft size={16} strokeWidth={1.5} />}
          {!collapsed && <span className="text-xs">Collapse</span>}
        </button>
      </div>
    </aside>
  );
}
