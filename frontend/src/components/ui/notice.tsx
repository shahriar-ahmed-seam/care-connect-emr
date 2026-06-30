import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

type Tone = "info" | "warning" | "error" | "success";

const tones: Record<Tone, string> = {
  info: "bg-brand-50 text-brand-800 border-brand-200",
  warning: "bg-amber-50 text-amber-900 border-amber-200",
  error: "bg-red-50 text-danger border-red-200",
  success: "bg-emerald-50 text-success border-emerald-200",
};

export function Notice({
  tone = "info",
  children,
  className,
  role,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
  role?: string;
}) {
  return (
    <div
      role={role ?? (tone === "error" ? "alert" : "status")}
      className={cn("rounded-xl border px-4 py-3 text-sm", tones[tone], className)}
    >
      {children}
    </div>
  );
}
