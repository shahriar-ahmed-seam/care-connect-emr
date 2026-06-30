"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { Notice } from "@/components/ui/notice";
import { ApiError, ServiceUnavailableError } from "@/lib/api";
import { dashboardPath, useAuthStore } from "@/lib/auth-store";
import { login } from "@/lib/endpoints";

export default function LoginPage() {
  const t = useTranslations("auth");
  const tc = useTranslations("common");
  const router = useRouter();
  const setAuth = useAuthStore((s) => s.setAuth);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
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
        <h1 className="text-2xl font-bold text-ink">{t("loginTitle")}</h1>
        <p className="text-sm text-ink-muted">{t("loginSubtitle")}</p>
      </div>

      {error && <Notice tone="error">{error}</Notice>}

      <form className="space-y-4" onSubmit={onSubmit}>
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
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <div className="flex justify-end">
          <Link
            href="/forgot-password"
            className="text-sm font-medium text-brand-700 hover:underline"
          >
            {t("forgotPassword")}
          </Link>
        </div>
        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? tc("loading") : t("loginButton")}
        </Button>
      </form>

      <p className="text-center text-sm text-ink-muted">
        {t("noAccount")}{" "}
        <Link href="/register" className="font-medium text-brand-700 hover:underline">
          {t("signUp")}
        </Link>
      </p>
    </Card>
  );
}
