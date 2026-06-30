import { cookies } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { defaultLocale, isLocale, LOCALE_COOKIE, type Locale } from "./config";
import { loadMessages } from "./messages";

export default getRequestConfig(async () => {
  const cookieLocale = cookies().get(LOCALE_COOKIE)?.value;
  const locale: Locale = isLocale(cookieLocale) ? cookieLocale : defaultLocale;
  const { messages, resolvedLocale } = await loadMessages(locale);

  return {
    locale: resolvedLocale,
    messages,
    timeZone: "Asia/Dhaka",
    now: new Date(),
  };
});
