"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { DashboardShell } from "@/components/dashboard-shell";
import { ServiceUnavailable } from "@/components/service-unavailable";
import { StatTile } from "@/components/ui/card";
import { useRequireAuth } from "@/hooks/use-require-auth";
import { ServiceUnavailableError } from "@/lib/api";
import { adminDashboard } from "@/lib/endpoints";

const nav = [
  { href: "/a/dashboard", label: "Dashboard" },
  { href: "/a/users", label: "Users" },
  { href: "/a/approvals", label: "Approvals" },
];

export default function AdminDashboard() {
  const { token } = useRequireAuth(["admin"]);
  const t = useTranslations("admin");
  const tc = useTranslations("common");

  const query = useQuery({
    queryKey: ["admin-dashboard"],
    queryFn: () => adminDashboard(token!),
    enabled: !!token,
  });

  if (query.error instanceof ServiceUnavailableError) {
    return (
      <DashboardShell nav={nav}>
        <ServiceUnavailable onRetry={() => query.refetch()} />
      </DashboardShell>
    );
  }

  const data = query.data;

  return (
    <DashboardShell nav={nav}>
      <h1 className="mb-6 text-2xl font-bold text-ink">{t("dashboardTitle")}</h1>
      {query.isLoading && <p className="text-ink-muted">{tc("loading")}</p>}
      {data && (
        <div className="grid gap-4 sm:grid-cols-3">
          <StatTile label={t("totalPatients")} value={data.total_patients} />
          <StatTile label={t("activeDoctors")} value={data.active_doctors} />
          <StatTile label={t("appointmentsToday")} value={data.appointments_today} />
        </div>
      )}
    </DashboardShell>
  );
}
