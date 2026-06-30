"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";

export function ServiceUnavailable({ onRetry }: { onRetry: () => void }) {
  const t = useTranslations("common");
  return (
    <div className="mx-auto max-w-md space-y-4 py-12 text-center">
      <Notice tone="error">{t("serviceUnavailable")}</Notice>
      <Button onClick={onRetry}>{t("retry")}</Button>
    </div>
  );
}
