export const locales = ["en", "bn"] as const;
export type Locale = (typeof locales)[number];
export const defaultLocale: Locale = "en";

export function isLocale(value: string | undefined | null): value is Locale {
  return value === "en" || value === "bn";
}

export const LOCALE_COOKIE = "cc_locale";
