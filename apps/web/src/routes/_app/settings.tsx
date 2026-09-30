/**
 * /settings — System health, LLM budget meter, users and roles, keys.
 * Primary action: none screen-wide; four independent panels (health, LLM, users, keys), the
 * latter two read-only because no management endpoint exists.
 * Reference products studied: Cal.com and Vercel (settings sections: one card per concern, quiet
 * hierarchy, honest empty/disabled states).
 */
import { createFileRoute } from "@tanstack/react-router";
import { ScreenShell } from "@/components/shell/screen-shell";
import { SettingsScreen } from "@/features/settings/settings-screen";

export const Route = createFileRoute("/_app/settings")({
  component: SettingsRoute,
});

function SettingsRoute() {
  return (
    <ScreenShell segments={[{ label: "Settings" }]}>
      <SettingsScreen />
    </ScreenShell>
  );
}
