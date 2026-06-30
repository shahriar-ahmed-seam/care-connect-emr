import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { LanguageToggle } from "@/components/ui/language-toggle";
import { type Locale } from "@/i18n/config";

export async function SiteHeader() {
  const t = await getTranslations("nav");
  const locale = (await getLocale()) as Locale;

  return (
    <header className="border-b border-black/5 bg-surface/80 backdrop-blur">
      <div className="container-page flex h-16 items-center justify-between">
        <Link href="/" aria-label="Care-Connect home">
          <Logo />
        </Link>
        <div className="flex items-center gap-3">
          <LanguageToggle current={locale} />
          <Button variant="ghost" size="sm" asChild>
            <Link href="/login">{t("login")}</Link>
          </Button>
          <Button size="sm" asChild>
            <Link href="/register">{t("register")}</Link>
          </Button>
        </div>
      </div>
    </header>
  );
}
