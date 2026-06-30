"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { LOCALE_COOKIE, type Locale } from "@/i18n/config";
import { cn } from "@/lib/cn";

export function LanguageToggle({ current }: { current: Locale }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  function setLocale(locale: Locale) {
    document.cookie = `${LOCALE_COOKIE}=${locale}; path=/; max-age=31536000`;
    startTransition(() => router.refresh());
  }

  return (
    <div
      className="inline-flex overflow-hidden rounded-lg border border-brand-200 text-sm"
      role="group"
      aria-label="Select language"
    >
      {(["en", "bn"] as const).map((locale) => (
        <button
          key={locale}
          type="button"
          onClick={() => setLocale(locale)}
          disabled={isPending}
          aria-pressed={current === locale}
          className={cn(
            "px-3 py-1.5 transition-colors",
            current === locale
              ? "bg-brand-500 text-white"
              : "bg-white text-brand-700 hover:bg-brand-50",
          )}
        >
          {locale === "en" ? "EN" : "বাংলা"}
        </button>
      ))}
    </div>
  );
}
