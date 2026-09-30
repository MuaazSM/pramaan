/**
 * /login — Sign in.
 * Primary action: Sign in. Reference products studied: Resend (restrained hero, centered card,
 * generous whitespace), Linear (calm auth form, subtle brand mark).
 */
import { useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { LoaderCircle, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";

export const Route = createFileRoute("/login")({
  component: LoginScreen,
});

function LoginScreen() {
  const [username, setUsername] = useState("examiner");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const setUser = useAuthStore((s) => s.setUser);
  const navigate = useNavigate();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const { data, error: apiError } = await api.POST("/api/auth/login", {
      body: { username, password },
    });
    setLoading(false);
    if (apiError || !data) {
      setError("Username or password is incorrect.");
      return;
    }
    setUser(data);
    void navigate({ to: "/cases" });
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-bg px-4">
      <div className="w-full max-w-[360px]">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <svg width="36" height="36" viewBox="0 0 32 32" fill="none" aria-hidden>
            <path d="M16 2 L28 9 V23 L16 30 L4 23 V9 Z" stroke="var(--brand-400)" strokeWidth="2" fill="none" />
            <rect x="10" y="12" width="10" height="1.6" fill="var(--brand-400)" />
            <rect x="10" y="15.2" width="7" height="1.6" fill="var(--brand-400)" />
            <rect x="10" y="18.4" width="4" height="1.6" fill="var(--brand-400)" />
            <circle cx="22" cy="20" r="1.6" fill="var(--ok)" />
          </svg>
          <div>
            <h1 className="text-[20px] font-semibold tracking-[-0.02em] text-text">pramaan</h1>
            <p className="mt-1 text-[13px] text-text-2">Proof from any DVR.</p>
          </div>
        </div>

        <form
          onSubmit={(e) => {
            void onSubmit(e);
          }}
          className="flex flex-col gap-4 rounded-[var(--radius-panel)] border border-line bg-panel p-6"
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="username">Username</Label>
            <Input
              id="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="examiner"
              required
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••"
              required
            />
          </div>

          {error && (
            <p role="alert" className="rounded-[var(--radius-control)] border border-[color-mix(in_oklab,var(--danger)_40%,transparent)] bg-[var(--danger-tint)] px-2.5 py-2 text-xs text-danger">
              {error}
            </p>
          )}

          <Button type="submit" disabled={loading} className="mt-1 w-full">
            {loading && <LoaderCircle size={14} className="animate-spin" />}
            Sign in
          </Button>

          {/* text-2, not text-3: text-3 (--ink-400) measures ~3.1-3.4:1 against these dark
              backgrounds — below WCAG AA's 4.5:1 for normal-size text (Lighthouse color-contrast,
              F5 fix). text-2 (--ink-300) measures ~6:1. */}
          <p className="text-center text-[11px] text-text-2">
            Seeded accounts: examiner/demo, reviewer/demo, admin/demo
          </p>
        </form>

        <div className="mt-4 flex items-center justify-center gap-1.5 text-[11px] text-text-2">
          <WifiOff size={12} strokeWidth={1.75} />
          Works offline once installed — evidence never leaves this workstation.
        </div>
      </div>
    </main>
  );
}
