import type { AbstractIntlMessages } from "next-intl";

import { defaultLocale, type Locale } from "./config";

export interface LoadMessagesResult {
  messages: AbstractIntlMessages;
  resolvedLocale: Locale;

  fellBack: boolean;
}

export async function loadMessages(locale: Locale): Promise<LoadMessagesResult> {
  try {
    const messages = (await import(`../../messages/${locale}.json`)).default;
    return { messages, resolvedLocale: locale, fellBack: false };
  } catch {
    if (locale !== defaultLocale) {
      const messages = (await import(`../../messages/${defaultLocale}.json`)).default;
      return { messages, resolvedLocale: defaultLocale, fellBack: true };
    }
    throw new Error("Failed to load the default English message catalog.");
  }
}
