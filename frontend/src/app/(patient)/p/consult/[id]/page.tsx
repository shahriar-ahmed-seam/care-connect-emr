"use client";

import { useParams } from "next/navigation";

import { ConsultRoom } from "@/components/consult-room";
import { DashboardShell } from "@/components/dashboard-shell";
import { useRequireAuth } from "@/hooks/use-require-auth";

export default function PatientConsultPage() {
  const { token } = useRequireAuth(["patient"]);
  const params = useParams();
  const id = String(params.id);

  const nav = [{ href: "/p/dashboard", label: "Dashboard" }];

  return (
    <DashboardShell nav={nav}>
      <h1 className="mb-6 text-2xl font-bold text-ink">Video consultation</h1>
      {token && <ConsultRoom appointmentId={id} initiator />}
    </DashboardShell>
  );
}
