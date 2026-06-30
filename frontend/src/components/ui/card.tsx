import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-black/5 bg-surface p-5 shadow-card",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({
  title,
  action,
}: {
  title: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3">
      <h2 className="text-lg font-semibold text-ink">{title}</h2>
      {action}
    </div>
  );
}

export function StatTile({
  label,
  value,
}: {
  label: ReactNode;
  value: ReactNode;
}) {
  return (
    <Card className="flex flex-col gap-1">
      <span className="text-sm text-ink-subtle">{label}</span>
      <span className="text-3xl font-semibold text-brand-700">{value}</span>
    </Card>
  );
}
