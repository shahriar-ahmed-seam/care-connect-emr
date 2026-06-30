"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { DashboardShell } from "@/components/dashboard-shell";
import { ServiceUnavailable } from "@/components/service-unavailable";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { useRequireAuth } from "@/hooks/use-require-auth";
import { ServiceUnavailableError } from "@/lib/api";
import { downloadPrescriptionPdf } from "@/lib/download";
import { getPatientRecord } from "@/lib/endpoints";
import { formatDate } from "@/lib/format";

export default function PatientRecordsPage() {
  const { token, user } = useRequireAuth(["patient"]);
  const t = useTranslations("patient");
  const tc = useTranslations("common");

  const query = useQuery({
    queryKey: ["patient-record", user?.id],
    queryFn: () => getPatientRecord(token!, user!.id),
    enabled: !!token && !!user,
  });

  const nav = [
    { href: "/p/dashboard", label: t("dashboardTitle") },
    { href: "/p/doctors", label: t("findDoctor") },
    { href: "/p/records", label: "Records" },
  ];

  if (query.error instanceof ServiceUnavailableError) {
    return (
      <DashboardShell nav={nav}>
        <ServiceUnavailable onRetry={() => query.refetch()} />
      </DashboardShell>
    );
  }

  const r = query.data;

  return (
    <DashboardShell nav={nav}>
      <h1 className="mb-6 text-2xl font-bold text-ink">Medical records</h1>
      {query.isLoading && <p className="text-ink-muted">{tc("loading")}</p>}
      {r && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader title={t("prescriptions")} />
            {r.prescriptions.length === 0 ? (
              <p className="text-sm text-ink-subtle">{tc("none")}</p>
            ) : (
              <ul className="divide-y divide-black/5">
                {r.prescriptions.map((p) => (
                  <li key={p.id} className="flex items-center justify-between py-3">
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

          <Card>
            <CardHeader title="Diagnoses" />
            {r.diagnoses.length === 0 ? (
              <p className="text-sm text-ink-subtle">{tc("none")}</p>
            ) : (
              <ul className="space-y-2">
                {r.diagnoses.map((d) => (
                  <li key={d.id} className="rounded-lg bg-surface-sunken p-3 text-sm">
                    <p className="text-ink-subtle">{formatDate(d.recorded_date)}</p>
                    <p className="text-ink">{d.text}</p>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardHeader title={t("vitals")} />
            {r.vitals.length === 0 ? (
              <p className="text-sm text-ink-subtle">{tc("none")}</p>
            ) : (
              <ul className="space-y-2">
                {r.vitals.map((v) => (
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

          <Card>
            <CardHeader title="History" />
            {r.medical_history.length === 0 ? (
              <p className="text-sm text-ink-subtle">{tc("none")}</p>
            ) : (
              <ul className="space-y-2">
                {r.medical_history.map((h) => (
                  <li key={h.id} className="rounded-lg bg-surface-sunken p-3 text-sm">
                    <p className="text-ink-subtle">{formatDate(h.entry_date)}</p>
                    <p className="text-ink">{h.description}</p>
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
