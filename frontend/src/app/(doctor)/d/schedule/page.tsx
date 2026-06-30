"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { DashboardShell } from "@/components/dashboard-shell";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { Notice } from "@/components/ui/notice";
import { useRequireAuth } from "@/hooks/use-require-auth";
import { ApiError } from "@/lib/api";
import {
  createSlot,
  deleteSlot,
  doctorSlots,
  getMyProfile,
  saveMyProfile,
  type SlotView,
} from "@/lib/endpoints";
import { formatDate } from "@/lib/format";

export default function DoctorSchedulePage() {
  const { token, user } = useRequireAuth(["doctor"]);
  const t = useTranslations("doctor");
  const tf = useTranslations("fields");
  const tc = useTranslations("common");

  const [specialty, setSpecialty] = useState("");
  const [qualifications, setQualifications] = useState("");
  const [fee, setFee] = useState("");
  const [date, setDate] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [slots, setSlots] = useState<SlotView[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  const profile = useQuery({
    queryKey: ["my-profile"],
    queryFn: () => getMyProfile(token!),
    enabled: !!token,
    retry: false,
  });

  useEffect(() => {
    if (profile.data) {
      setSpecialty(profile.data.specialty ?? "");
      setQualifications(profile.data.qualifications ?? "");
      setFee(profile.data.consultation_fee_bdt ?? "");
    }
  }, [profile.data]);

  async function refreshSlots() {
    if (!token || !user) return;
    try {
      const res = await doctorSlots(token, user.id);
      setSlots(res.slots);
    } catch {

    }
  }

  useEffect(() => {
    void refreshSlots();

  }, [token, user?.id]);

  async function onSaveProfile(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    setMessage(null);
    try {
      await saveMyProfile(token, {
        specialty,
        qualifications: qualifications || null,
        consultation_fee_bdt: Number(fee),
      });
      setMessage("Profile saved.");
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : tc("serviceUnavailable"));
    }
  }

  async function onAddSlot(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    setMessage(null);
    try {
      await createSlot(token, { date, start_time: start, end_time: end });
      setMessage("Slot added.");
      await refreshSlots();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : tc("serviceUnavailable"));
    }
  }

  async function onDeleteSlot(id: string) {
    if (!token) return;
    try {
      await deleteSlot(token, id);
      await refreshSlots();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : tc("serviceUnavailable"));
    }
  }

  const nav = [
    { href: "/d/dashboard", label: t("dashboardTitle") },
    { href: "/d/schedule", label: t("schedule") },
  ];

  return (
    <DashboardShell nav={nav}>
      <h1 className="mb-6 text-2xl font-bold text-ink">{t("schedule")}</h1>

      {message && (
        <Notice tone="info" className="mb-4">
          {message}
        </Notice>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Profile" />
          <form className="space-y-4" onSubmit={onSaveProfile}>
            <Field label={tf("specialty")} htmlFor="specialty">
              <Input
                id="specialty"
                value={specialty}
                onChange={(e) => setSpecialty(e.target.value)}
                required
              />
            </Field>
            <Field label={tf("qualifications")} htmlFor="qualifications">
              <Input
                id="qualifications"
                value={qualifications}
                onChange={(e) => setQualifications(e.target.value)}
              />
            </Field>
            <Field label={tf("fee")} htmlFor="fee">
              <Input
                id="fee"
                type="number"
                min="0"
                step="0.01"
                value={fee}
                onChange={(e) => setFee(e.target.value)}
                required
              />
            </Field>
            <Button type="submit">{tc("save")}</Button>
          </form>
        </Card>

        <Card>
          <CardHeader title="Availability" />
          <form className="space-y-4" onSubmit={onAddSlot}>
            <Field label="Date" htmlFor="date">
              <Input
                id="date"
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                required
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Start" htmlFor="start">
                <Input
                  id="start"
                  type="time"
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                  required
                />
              </Field>
              <Field label="End" htmlFor="end">
                <Input
                  id="end"
                  type="time"
                  value={end}
                  onChange={(e) => setEnd(e.target.value)}
                  required
                />
              </Field>
            </div>
            <Button type="submit" variant="secondary">
              Add slot
            </Button>
          </form>

          <ul className="mt-5 space-y-2">
            {slots.map((s) => (
              <li
                key={s.id}
                className="flex items-center justify-between rounded-lg bg-surface-sunken px-3 py-2 text-sm"
              >
                <span>
                  {formatDate(s.date)} · {s.start_time.slice(0, 5)}–
                  {s.end_time.slice(0, 5)}
                </span>
                <button
                  type="button"
                  className="text-danger hover:underline"
                  onClick={() => onDeleteSlot(s.id)}
                >
                  {tc("cancel")}
                </button>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </DashboardShell>
  );
}
