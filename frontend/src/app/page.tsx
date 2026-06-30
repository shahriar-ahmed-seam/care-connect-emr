import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Logo } from "@/components/brand/logo";
import { SiteHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export default async function LandingPage() {
  const t = await getTranslations("landing");
  const tb = await getTranslations("brand");

  const features = [
    { title: t("feature1Title"), body: t("feature1Body") },
    { title: t("feature2Title"), body: t("feature2Body") },
    { title: t("feature3Title"), body: t("feature3Body") },
    { title: t("feature4Title"), body: t("feature4Body") },
  ];

  return (
    <div className="min-h-screen">
      <SiteHeader />

      {}
      <section className="relative overflow-hidden">
        <div
          aria-hidden
          className="absolute inset-0 -z-10 bg-gradient-to-br from-brand-50 via-surface to-surface"
        />
        <div className="container-page grid items-center gap-10 py-16 lg:grid-cols-2 lg:py-24">
          <div className="space-y-6">
            <span className="inline-flex items-center rounded-full bg-brand-100 px-3 py-1 text-sm font-medium text-brand-700">
              {tb("tagline")}
            </span>
            <h1 className="text-4xl font-bold leading-tight tracking-tight text-ink sm:text-5xl">
              {t("heroTitle")}
            </h1>
            <p className="max-w-xl text-lg text-ink-muted">{t("heroSubtitle")}</p>
            <div className="flex flex-wrap gap-3">
              <Button size="lg" asChild>
                <Link href="/register">{t("ctaPrimary")}</Link>
              </Button>
              <Button size="lg" variant="secondary" asChild>
                <Link href="/register">{t("ctaSecondary")}</Link>
              </Button>
            </div>
          </div>

          {}
          <div className="relative">
            <Card className="space-y-4 border-brand-100">
              <div className="flex items-center gap-3">
                <Logo showWordmark={false} />
                <div className="h-2 w-24 rounded-full bg-brand-100" />
              </div>
              <div className="aspect-video rounded-xl bg-gradient-to-br from-brand-500 to-brand-700" />
              <div className="grid grid-cols-3 gap-3">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="h-16 rounded-lg bg-surface-sunken" />
                ))}
              </div>
            </Card>
          </div>
        </div>
      </section>

      {}
      <section className="container-page py-16">
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {features.map((f) => (
            <Card key={f.title} className="space-y-2">
              <h3 className="text-base font-semibold text-brand-700">{f.title}</h3>
              <p className="text-sm text-ink-muted">{f.body}</p>
            </Card>
          ))}
        </div>
      </section>

      <footer className="border-t border-black/5 py-8">
        <div className="container-page flex items-center justify-between text-sm text-ink-subtle">
          <Logo showWordmark={false} />
          <span>© {new Date().getFullYear()} Care-Connect</span>
        </div>
      </footer>
    </div>
  );
}
