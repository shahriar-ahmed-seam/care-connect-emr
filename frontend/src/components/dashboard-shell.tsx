"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/lib/auth-store";
import { logout as logoutEndpoint } from "@/lib/endpoints";

export interface NavItem {
  href: string;
  label: string;
}

export function DashboardShell({
  nav,
  children,
}: {
  nav: NavItem[];
  children: ReactNode;
}) {
  const t = useTranslations("nav");
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const token = useAuthStore((s) => s.token);
  const clear = useAuthStore((s) => s.clear);

  async function onLogout() {
    try {
      if (token) await logoutEndpoint(token);
    } catch {

    } finally {
      clear();
      router.replace("/login");
    }
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-black/5 bg-surface">
        <div className="container-page flex h-16 items-center justify-between gap-4">
          <div className="flex items-center gap-6">
            <Link href="/" aria-label="Care-Connect home">
              <Logo />
            </Link>
            <nav className="hidden items-center gap-1 md:flex" aria-label="Primary">
              {nav.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="rounded-lg px-3 py-2 text-sm font-medium text-ink-muted hover:bg-surface-sunken hover:text-ink"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            {user && (
              <span className="hidden text-sm text-ink-muted sm:block">
                {user.full_name}
              </span>
            )}
            <Button variant="secondary" size="sm" onClick={onLogout}>
              {t("logout")}
            </Button>
          </div>
        </div>
        {}
        <nav
          className="flex gap-1 overflow-x-auto border-t border-black/5 px-4 py-2 md:hidden"
          aria-label="Primary mobile"
        >
          {nav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium text-ink-muted hover:bg-surface-sunken"
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </header>
      <main className="container-page py-8">{children}</main>
    </div>
  );
}
