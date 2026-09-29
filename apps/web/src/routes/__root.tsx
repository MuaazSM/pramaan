import { createRootRoute, Outlet } from "@tanstack/react-router";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ToastProvider, ToastViewport } from "@/components/ui/toast";
import { ToastQueueProvider } from "@/components/ui/use-toast";

export const Route = createRootRoute({
  component: RootComponent,
});

function RootComponent() {
  return (
    <TooltipProvider delayDuration={300}>
      <ToastQueueProvider>
        <ToastProvider>
          <Outlet />
          <ToastViewport />
        </ToastProvider>
      </ToastQueueProvider>
    </TooltipProvider>
  );
}
