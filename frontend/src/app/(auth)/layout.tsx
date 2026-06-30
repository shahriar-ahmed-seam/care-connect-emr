import Link from "next/link";
import { getLocale } from "next-intl/server";
import type { ReactNode } from "react";

import { Logo } from "@/components/brand/logo";
import { LanguageToggle } from "@/components/ui/language-toggle";
import { type Locale } from "@/i18n/config";

export default async function AuthLayout({ children }: { children: ReactNode }) {
  const locale = (await getLocale()) as Locale;
  return (
    <div className="flex min-h-screen flex-col bg-gradient-to-br from-brand-50 via-surface-muted to-surface-muted">
      <header className="container-page flex h-16 items-center justify-between">
        <Link href="/" aria-label="Care-Connect home">
          <Logo />
        </Link>
        <LanguageToggle current={locale} />
      </header>
      <main className="flex flex-1 items-center justify-center px-4 py-10">
        <div className="w-full max-w-md">{children}</div>
      </main>
    </div>
  );
}
