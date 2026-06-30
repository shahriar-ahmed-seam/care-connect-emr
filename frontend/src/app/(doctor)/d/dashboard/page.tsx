"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { DashboardShell } from "@/components/dashboard-shell";
import { ServiceUnavailable } from "@/components/service-unavailable";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, StatTile } from "@/components/ui/card";
import { useRequireAuth } from "@/hooks/use-require-auth";
import { ServiceUnavailableError } from "@/lib/api";
import { doctorDashboard } from "@/lib/endpoints";
import { formatTime } from "@/lib/format";

export default function DoctorDashboard() {
  const { token } = useRequireAuth(["doctor"]);
  const t = useTranslations("doctor");
  const tc = useTranslations("common");

  const query = useQuery({
    queryKey: ["doctor-dashboard"],
    queryFn: () => doctorDashboard(token!),
    enabled: !!token,
  });

  const nav = [
    { href: "/d/dashboard", label: t("dashboardTitle") },
    { href: "/d/schedule", label: t("schedule") },
  ];

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
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-3">
            <StatTile label={t("pendingToday")} value={data.pending_today} />
          </div>

          <Card>
            <CardHeader title={t("today")} />
            {data.today_appointments.length === 0 ? (
              <p className="text-sm text-ink-subtle">{t("noToday")}</p>
            ) : (
              <ul className="divide-y divide-black/5">
                {data.today_appointments.map((a) => (
                  <li key={a.id} className="flex items-center justify-between py-3">
                    <div>
                      <p className="font-medium text-ink">{a.patient_name}</p>
                      <p className="text-sm text-ink-subtle">
                        {formatTime(a.start_time)} · {a.status}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <Button size="sm" variant="secondary" asChild>
                        <Link href={`/d/patients/${a.patient_id}?appointment=${a.id}`}>
                          Record
                        </Link>
                      </Button>
                      {a.can_join && (
                        <Button size="sm" asChild>
                          <Link href={`/d/consult/${a.id}`}>{tc("join")}</Link>
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
    </DashboardShell>
  );
}
