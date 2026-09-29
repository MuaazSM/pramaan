import * as React from "react";

interface ToastItem {
  id: string;
  title: string;
  description?: string;
  variant?: "default" | "ok" | "danger";
}

interface ToastContextValue {
  toasts: ToastItem[];
  toast: (t: Omit<ToastItem, "id">) => void;
  dismiss: (id: string) => void;
}

const ToastContext = React.createContext<ToastContextValue | null>(null);

/** Lightweight toast queue (shadcn "use-toast" pattern), backing src/components/ui/toast.tsx. */
export function ToastQueueProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<ToastItem[]>([]);
  const dismiss = React.useCallback((id: string) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);
  const toast = React.useCallback((t: Omit<ToastItem, "id">) => {
    const id = crypto.randomUUID();
    setToasts((s) => [...s, { ...t, id }]);
  }, []);
  return <ToastContext.Provider value={{ toasts, toast, dismiss }}>{children}</ToastContext.Provider>;
}

export function useToast(): ToastContextValue {
  const ctx = React.useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastQueueProvider");
  return ctx;
}
