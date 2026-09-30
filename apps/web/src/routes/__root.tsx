import { createRootRoute, Outlet } from "@tanstack/react-router";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ToastProvider, ToastViewport, Toaster } from "@/components/ui/toast";
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
          {/* Renders the useToast() queue — see toast.tsx's Toaster for why this line matters
              (F2 found toast() was a silent no-op without it). */}
          <Toaster />
          <ToastViewport />
        </ToastProvider>
      </ToastQueueProvider>
    </TooltipProvider>
  );
}
