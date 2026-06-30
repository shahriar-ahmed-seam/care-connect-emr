"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { DashboardShell } from "@/components/dashboard-shell";
import { ServiceUnavailable } from "@/components/service-unavailable";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useRequireAuth } from "@/hooks/use-require-auth";
import { ServiceUnavailableError } from "@/lib/api";
import { approveDoctor, pendingApprovals, rejectDoctor } from "@/lib/endpoints";

const nav = [
  { href: "/a/dashboard", label: "Dashboard" },
  { href: "/a/users", label: "Users" },
  { href: "/a/approvals", label: "Approvals" },
];

export default function AdminApprovalsPage() {
  const { token } = useRequireAuth(["admin"]);
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const qc = useQueryClient();

  const query = useQuery({
    queryKey: ["admin-approvals"],
    queryFn: () => pendingApprovals(token!),
    enabled: !!token,
  });

  async function act(fn: (token: string, id: string) => Promise<unknown>, id: string) {
    if (!token) return;
    await fn(token, id);
    await qc.invalidateQueries({ queryKey: ["admin-approvals"] });
  }

  if (query.error instanceof ServiceUnavailableError) {
    return (
      <DashboardShell nav={nav}>
        <ServiceUnavailable onRetry={() => query.refetch()} />
      </DashboardShell>
    );
  }

  const accounts = query.data?.accounts ?? [];

  return (
    <DashboardShell nav={nav}>
      <h1 className="mb-6 text-2xl font-bold text-ink">{t("approvals")}</h1>
      {query.isLoading && <p className="text-ink-muted">{tc("loading")}</p>}
      {!query.isLoading && accounts.length === 0 && (
        <p className="text-ink-subtle">{t("noPending")}</p>
      )}
      <div className="space-y-3">
        {accounts.map((a) => (
          <Card key={a.id} className="flex items-center justify-between">
            <div>
              <p className="font-medium text-ink">{a.full_name}</p>
              <p className="text-sm text-ink-subtle">{a.email}</p>
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={() => act(approveDoctor, a.id)}>
                {t("approve")}
              </Button>
              <Button size="sm" variant="danger" onClick={() => act(rejectDoctor, a.id)}>
                {t("reject")}
              </Button>
            </div>
          </Card>
        ))}
      </div>
    </DashboardShell>
  );
}
