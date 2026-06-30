"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { Notice } from "@/components/ui/notice";
import { ApiError, ServiceUnavailableError } from "@/lib/api";
import { dashboardPath, useAuthStore } from "@/lib/auth-store";
import { login, register } from "@/lib/endpoints";

export default function RegisterPage() {
  const t = useTranslations("auth");
  const tc = useTranslations("common");
  const router = useRouter();
  const setAuth = useAuthStore((s) => s.setAuth);

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"patient" | "doctor">("patient");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(false);
    setBusy(true);
    try {
      await register({ email, password, full_name: fullName, role });

      if (role === "doctor") {
        setPending(true);
        return;
      }
      const result = await login({ email, password });
      setAuth(result.access_token, result.user);
      router.push(dashboardPath(result.user.role));
    } catch (err) {
      if (err instanceof ApiError) setError(err.message);
      else if (err instanceof ServiceUnavailableError)
        setError(tc("serviceUnavailable"));
      else setError(tc("serviceUnavailable"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold text-ink">{t("registerTitle")}</h1>
        <p className="text-sm text-ink-muted">{t("registerSubtitle")}</p>
      </div>

      {error && <Notice tone="error">{error}</Notice>}
      {pending && <Notice tone="info">{t("doctorPendingNotice")}</Notice>}

      <form className="space-y-4" onSubmit={onSubmit}>
        <Field label={t("fullName")} htmlFor="fullName">
          <Input
            id="fullName"
            required
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
          />
        </Field>
        <Field label={t("email")} htmlFor="email">
          <Input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        <Field label={t("password")} htmlFor="password">
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            minLength={8}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <Field label={t("role")} htmlFor="role">
          <Select
            id="role"
            value={role}
            onChange={(e) => setRole(e.target.value as "patient" | "doctor")}
          >
            <option value="patient">{t("rolePatient")}</option>
            <option value="doctor">{t("roleDoctor")}</option>
          </Select>
        </Field>
        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? tc("loading") : t("registerButton")}
        </Button>
      </form>

      <p className="text-center text-sm text-ink-muted">
        {t("haveAccount")}{" "}
        <Link href="/login" className="font-medium text-brand-700 hover:underline">
          {t("signIn")}
        </Link>
      </p>
    </Card>
  );
}
