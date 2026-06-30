"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { DashboardShell } from "@/components/dashboard-shell";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { Notice } from "@/components/ui/notice";
import { useRequireAuth } from "@/hooks/use-require-auth";
import { ApiError } from "@/lib/api";
import {
  createPrescription,
  getPatientRecord,
  recordDiagnosis,
  recordVitals,
  type MedicationInput,
} from "@/lib/endpoints";
import { formatDate } from "@/lib/format";

const nav = [
  { href: "/d/dashboard", label: "Dashboard" },
  { href: "/d/schedule", label: "Schedule" },
];

const emptyMed: MedicationInput = { name: "", dosage: "", frequency: "", duration: "" };

export default function DoctorPatientPage() {
  const { token } = useRequireAuth(["doctor"]);
  const params = useParams();
  const search = useSearchParams();
  const tf = useTranslations("fields");
  const tc = useTranslations("common");
  const qc = useQueryClient();

  const patientId = String(params.id);
  const appointmentId = search.get("appointment") ?? "";

  const [vitals, setVitals] = useState({ bp: "", hr: "", temp: "", weight: "" });
  const [diagnosis, setDiagnosis] = useState("");
  const [meds, setMeds] = useState<MedicationInput[]>([{ ...emptyMed }]);
  const [message, setMessage] = useState<{ tone: "info" | "error"; text: string } | null>(
    null,
  );

  const record = useQuery({
    queryKey: ["doctor-patient-record", patientId],
    queryFn: () => getPatientRecord(token!, patientId),
    enabled: !!token,
  });

  function note(tone: "info" | "error", text: string) {
    setMessage({ tone, text });
  }

  function errText(err: unknown) {
    return err instanceof ApiError ? err.message : tc("serviceUnavailable");
  }

  async function submitVitals(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !appointmentId) return;
    try {
      await recordVitals(token, patientId, {
        appointment_id: appointmentId,
        blood_pressure: vitals.bp ? Number(vitals.bp) : null,
        heart_rate: vitals.hr ? Number(vitals.hr) : null,
        temperature: vitals.temp ? Number(vitals.temp) : null,
        weight: vitals.weight ? Number(vitals.weight) : null,
      });
      note("info", "Vitals recorded.");
      setVitals({ bp: "", hr: "", temp: "", weight: "" });
      await qc.invalidateQueries({ queryKey: ["doctor-patient-record", patientId] });
    } catch (err) {
      note("error", errText(err));
    }
  }

  async function submitDiagnosis(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !appointmentId) return;
    try {
      await recordDiagnosis(token, appointmentId, {
        text: diagnosis,
        recorded_date: new Date().toISOString().slice(0, 10),
      });
      note("info", "Diagnosis recorded.");
      setDiagnosis("");
      await qc.invalidateQueries({ queryKey: ["doctor-patient-record", patientId] });
    } catch (err) {
      note("error", errText(err));
    }
  }

  async function submitPrescription(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !appointmentId) return;
    try {
      await createPrescription(token, appointmentId, meds);
      note("info", "Prescription created and emailed to the patient.");
      setMeds([{ ...emptyMed }]);
      await qc.invalidateQueries({ queryKey: ["doctor-patient-record", patientId] });
    } catch (err) {
      note("error", errText(err));
    }
  }

  function updateMed(i: number, field: keyof MedicationInput, value: string) {
    setMeds((prev) => prev.map((m, idx) => (idx === i ? { ...m, [field]: value } : m)));
  }

  return (
    <DashboardShell nav={nav}>
      <h1 className="mb-6 text-2xl font-bold text-ink">Patient record</h1>

      {message && (
        <Notice tone={message.tone} className="mb-4">
          {message.text}
        </Notice>
      )}
      {!appointmentId && (
        <Notice tone="warning" className="mb-4">
          Open this patient from a today&apos;s appointment to record clinical data.
        </Notice>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {}
        <div className="space-y-6">
          <Card>
            <CardHeader title="Record vitals" />
            <form className="grid grid-cols-2 gap-3" onSubmit={submitVitals}>
              <Field label={tf("bloodPressure")} htmlFor="bp">
                <Input id="bp" type="number" value={vitals.bp}
                  onChange={(e) => setVitals({ ...vitals, bp: e.target.value })} />
              </Field>
              <Field label={tf("heartRate")} htmlFor="hr">
                <Input id="hr" type="number" value={vitals.hr}
                  onChange={(e) => setVitals({ ...vitals, hr: e.target.value })} />
              </Field>
              <Field label={tf("temperature")} htmlFor="temp">
                <Input id="temp" type="number" value={vitals.temp}
                  onChange={(e) => setVitals({ ...vitals, temp: e.target.value })} />
              </Field>
              <Field label={tf("weight")} htmlFor="weight">
                <Input id="weight" type="number" value={vitals.weight}
                  onChange={(e) => setVitals({ ...vitals, weight: e.target.value })} />
              </Field>
              <div className="col-span-2">
                <Button type="submit" size="sm" disabled={!appointmentId}>
                  {tc("save")}
                </Button>
              </div>
            </form>
          </Card>

          <Card>
            <CardHeader title={tf("diagnosis")} />
            <form className="space-y-3" onSubmit={submitDiagnosis}>
              <textarea
                className="h-24 w-full rounded-xl border border-black/10 p-3 text-sm"
                value={diagnosis}
                onChange={(e) => setDiagnosis(e.target.value)}
                aria-label={tf("diagnosis")}
              />
              <Button type="submit" size="sm" disabled={!appointmentId || !diagnosis}>
                {tc("save")}
              </Button>
            </form>
          </Card>

          <Card>
            <CardHeader title="Prescription" />
            <form className="space-y-3" onSubmit={submitPrescription}>
              {meds.map((m, i) => (
                <div key={i} className="grid grid-cols-2 gap-2">
                  <Input placeholder={tf("medication")} value={m.name}
                    onChange={(e) => updateMed(i, "name", e.target.value)} />
                  <Input placeholder={tf("dosage")} value={m.dosage}
                    onChange={(e) => updateMed(i, "dosage", e.target.value)} />
                  <Input placeholder={tf("frequency")} value={m.frequency}
                    onChange={(e) => updateMed(i, "frequency", e.target.value)} />
                  <Input placeholder={tf("duration")} value={m.duration}
                    onChange={(e) => updateMed(i, "duration", e.target.value)} />
                </div>
              ))}
              <div className="flex gap-2">
                <Button type="button" size="sm" variant="ghost"
                  onClick={() => setMeds([...meds, { ...emptyMed }])}>
                  + Add medication
                </Button>
                <Button type="submit" size="sm" disabled={!appointmentId}>
                  Issue prescription
                </Button>
              </div>
            </form>
          </Card>
        </div>

        {}
        <Card>
          <CardHeader title="History" />
          {record.isLoading && <p className="text-ink-muted">{tc("loading")}</p>}
          {record.data && (
            <div className="space-y-4 text-sm">
              <section>
                <h3 className="mb-1 font-medium text-ink">Diagnoses</h3>
                {record.data.diagnoses.length === 0 ? (
                  <p className="text-ink-subtle">{tc("none")}</p>
                ) : (
                  record.data.diagnoses.map((d) => (
                    <p key={d.id} className="text-ink-muted">
                      {formatDate(d.recorded_date)} — {d.text}
                    </p>
                  ))
                )}
              </section>
              <section>
                <h3 className="mb-1 font-medium text-ink">Recent vitals</h3>
                {record.data.vitals.slice(0, 5).map((v) => (
                  <p key={v.id} className="text-ink-muted">
                    {formatDate(v.recorded_at)} — BP {v.blood_pressure ?? "—"}, HR{" "}
                    {v.heart_rate ?? "—"}
                  </p>
                ))}
              </section>
            </div>
          )}
        </Card>
      </div>
    </DashboardShell>
  );
}
