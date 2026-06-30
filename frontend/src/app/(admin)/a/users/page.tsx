"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { DashboardShell } from "@/components/dashboard-shell";
import { ServiceUnavailable } from "@/components/service-unavailable";
import { Card } from "@/components/ui/card";
import { useRequireAuth } from "@/hooks/use-require-auth";
import { ServiceUnavailableError } from "@/lib/api";
import { adminUsers, deactivateUser } from "@/lib/endpoints";

const nav = [
  { href: "/a/dashboard", label: "Dashboard" },
  { href: "/a/users", label: "Users" },
  { href: "/a/approvals", label: "Approvals" },
];

export default function AdminUsersPage() {
  const { token } = useRequireAuth(["admin"]);
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const qc = useQueryClient();

  const query = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => adminUsers(token!),
    enabled: !!token,
  });

  async function onDeactivate(id: string) {
    if (!token) return;
    await deactivateUser(token, id);
    await qc.invalidateQueries({ queryKey: ["admin-users"] });
  }

  if (query.error instanceof ServiceUnavailableError) {
    return (
      <DashboardShell nav={nav}>
        <ServiceUnavailable onRetry={() => query.refetch()} />
      </DashboardShell>
    );
  }

  return (
    <DashboardShell nav={nav}>
      <h1 className="mb-6 text-2xl font-bold text-ink">{t("users")}</h1>
      {query.isLoading && <p className="text-ink-muted">{tc("loading")}</p>}
      {query.data && (
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="bg-surface-sunken text-left text-ink-muted">
              <tr>
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">Email</th>
                <th className="px-4 py-3 font-medium">Role</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-black/5">
              {query.data.users.map((u) => (
                <tr key={u.id}>
                  <td className="px-4 py-3 text-ink">{u.full_name}</td>
                  <td className="px-4 py-3 text-ink-muted">{u.email}</td>
                  <td className="px-4 py-3 text-ink-muted">{u.role}</td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-surface-sunken px-2 py-0.5 text-xs text-ink-muted">
                      {u.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {u.status === "active" && (
                      <button
                        type="button"
                        className="text-danger hover:underline"
                        onClick={() => onDeactivate(u.id)}
                      >
                        {t("deactivate")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </DashboardShell>
  );
}
