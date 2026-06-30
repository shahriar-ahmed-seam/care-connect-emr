"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { DashboardShell } from "@/components/dashboard-shell";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Notice } from "@/components/ui/notice";
import { useRequireAuth } from "@/hooks/use-require-auth";
import { ApiError } from "@/lib/api";
import {
  bookAppointment,
  doctorSlots,
  searchDoctors,
  type DoctorResult,
  type SlotView,
} from "@/lib/endpoints";
import { formatBDT, formatDate, formatTime } from "@/lib/format";

export default function FindDoctorsPage() {
  const { token } = useRequireAuth(["patient"]);
  const t = useTranslations("patient");
  const tc = useTranslations("common");
  const tf = useTranslations("fields");

  const [term, setTerm] = useState("");
  const [doctors, setDoctors] = useState<DoctorResult[]>([]);
  const [slots, setSlots] = useState<Record<string, SlotView[]>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await searchDoctors(token, term);
      setDoctors(res.doctors);
      if (res.doctors.length === 0) setMessage(tc("none"));
    } catch {
      setMessage(tc("serviceUnavailable"));
    } finally {
      setBusy(false);
    }
  }

  async function loadSlots(doctorId: string) {
    if (!token) return;
    const res = await doctorSlots(token, doctorId);
    setSlots((prev) => ({ ...prev, [doctorId]: res.slots }));
  }

  async function onBook(slotId: string) {
    if (!token) return;
    setMessage(null);
    try {
      await bookAppointment(token, slotId);
      setMessage("Appointment booked. Check your dashboard.");
      setSlots({});
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : tc("serviceUnavailable"));
    }
  }

  const nav = [
    { href: "/p/dashboard", label: t("dashboardTitle") },
    { href: "/p/doctors", label: t("findDoctor") },
  ];

  return (
    <DashboardShell nav={nav}>
      <h1 className="mb-6 text-2xl font-bold text-ink">{t("findDoctor")}</h1>

      <form onSubmit={onSearch} className="mb-6 flex max-w-xl gap-3">
        <Input
          placeholder={tf("specialty")}
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          aria-label={tf("specialty")}
        />
        <Button type="submit" disabled={busy}>
          {tc("search")}
        </Button>
      </form>

      {message && (
        <Notice tone="info" className="mb-4">
          {message}
        </Notice>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {doctors.map((d) => (
          <Card key={d.id} className="space-y-3">
            <CardHeader
              title={d.full_name}
              action={
                <span className="text-sm font-medium text-brand-700">
                  {formatBDT(d.consultation_fee_bdt)}
                </span>
              }
            />
            <p className="text-sm text-ink-muted">
              {d.specialty}
              {d.qualifications ? ` · ${d.qualifications}` : ""}
            </p>
            <Button size="sm" variant="secondary" onClick={() => loadSlots(d.id)}>
              {t("book")}
            </Button>

            {slots[d.id] && (
              <ul className="flex flex-wrap gap-2 pt-2">
                {slots[d.id].length === 0 && (
                  <li className="text-sm text-ink-subtle">{tc("none")}</li>
                )}
                {slots[d.id].map((s) => (
                  <li key={s.id}>
                    <button
                      type="button"
                      onClick={() => onBook(s.id)}
                      className="rounded-lg border border-brand-200 px-3 py-1.5 text-sm text-brand-700 hover:bg-brand-50"
                    >
                      {formatDate(s.date)} {s.start_time.slice(0, 5)}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        ))}
      </div>
    </DashboardShell>
  );
}
