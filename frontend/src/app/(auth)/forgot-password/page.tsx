"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { Notice } from "@/components/ui/notice";
import { ServiceUnavailableError } from "@/lib/api";
import { requestPasswordReset } from "@/lib/endpoints";

export default function ForgotPasswordPage() {
  const t = useTranslations("auth");
  const tc = useTranslations("common");
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await requestPasswordReset(email);
      setSent(true);
    } catch (err) {

      if (err instanceof ServiceUnavailableError) setError(tc("serviceUnavailable"));
      else setSent(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold text-ink">{t("resetTitle")}</h1>
        <p className="text-sm text-ink-muted">{t("resetSubtitle")}</p>
      </div>

      {error && <Notice tone="error">{error}</Notice>}
      {sent ? (
        <Notice tone="success">{t("resetSent")}</Notice>
      ) : (
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
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? tc("loading") : t("resetButton")}
          </Button>
        </form>
      )}

      <p className="text-center text-sm text-ink-muted">
        <Link href="/login" className="font-medium text-brand-700 hover:underline">
          {t("signIn")}
        </Link>
      </p>
    </Card>
  );
}
