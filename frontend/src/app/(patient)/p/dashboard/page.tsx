"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { DashboardShell } from "@/components/dashboard-shell";
import { ServiceUnavailable } from "@/components/service-unavailable";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Notice } from "@/components/ui/notice";
import { useRequireAuth } from "@/hooks/use-require-auth";
import { ServiceUnavailableError } from "@/lib/api";
import { downloadPrescriptionPdf } from "@/lib/download";
import { patientDashboard } from "@/lib/endpoints";
import { formatDate, formatTime } from "@/lib/format";

export default function PatientDashboard() {
  const { token } = useRequireAuth(["patient"]);
  const t = useTranslations("patient");
  const tc = useTranslations("common");
  const ta = useTranslations("appointment");

  const query = useQuery({
    queryKey: ["patient-dashboard"],
    queryFn: () => patientDashboard(token!),
    enabled: !!token,
  });

  const nav = [
    { href: "/p/dashboard", label: t("dashboardTitle") },
    { href: "/p/doctors", label: t("findDoctor") },
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
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-ink">{t("dashboardTitle")}</h1>
        <Button asChild size="sm">
          <Link href="/p/doctors">{t("findDoctor")}</Link>
        </Button>
      </div>

      {query.isLoading && <p className="text-ink-muted">{tc("loading")}</p>}

      {data && (
        <div className="grid gap-6 lg:grid-cols-3">
          <section className="space-y-4 lg:col-span-2">
            <Card>
              <CardHeader title={t("upcoming")} />
              {data.upcoming_appointments.length === 0 ? (
                <p className="text-sm text-ink-subtle">{t("noUpcoming")}</p>
              ) : (
                <ul className="divide-y divide-black/5">
                  {data.upcoming_appointments.map((a) => (
                    <li
                      key={a.id}
                      className="flex items-center justify-between py-3"
                    >
                      <div>
                        <p className="font-medium text-ink">
                          {ta("with")} {a.doctor_name}
                        </p>
                        <p className="text-sm text-ink-subtle">
                          {formatDate(a.start_time)} · {formatTime(a.start_time)}
                        </p>
                      </div>
                      {a.can_join && (
                        <Button size="sm" asChild>
                          <Link href={`/p/consult/${a.id}`}>{tc("join")}</Link>
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card>
              <CardHeader title={t("prescriptions")} />
              {data.recent_prescriptions.length === 0 ? (
                <p className="text-sm text-ink-subtle">{t("noPrescriptions")}</p>
              ) : (
                <ul className="divide-y divide-black/5">
                  {data.recent_prescriptions.map((p) => (
                    <li
                      key={p.id}
                      className="flex items-center justify-between py-3"
                    >
                      <div>
                        <p className="font-medium text-ink">{p.doctor_name}</p>
                        <p className="text-sm text-ink-subtle">
                          {formatDate(p.issued_at)} · {p.medications.length} item(s)
                        </p>
                      </div>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => token && downloadPrescriptionPdf(token, p.id)}
                      >
                        {tc("download")}
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </section>

          <section>
            <Card>
              <CardHeader title={t("vitals")} />
              {data.vitals.length === 0 ? (
                <p className="text-sm text-ink-subtle">{tc("none")}</p>
              ) : (
                <ul className="space-y-3">
                  {data.vitals.slice(0, 6).map((v) => (
                    <li key={v.id} className="rounded-lg bg-surface-sunken p-3 text-sm">
                      <p className="text-ink-subtle">{formatDate(v.recorded_at)}</p>
                      <p className="text-ink">
                        BP {v.blood_pressure ?? "—"} · HR {v.heart_rate ?? "—"} · T{" "}
                        {v.temperature ?? "—"} · Wt {v.weight ?? "—"}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </section>
        </div>
      )}
    </DashboardShell>
  );
}
