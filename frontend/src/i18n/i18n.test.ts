import fc from "fast-check";
import { describe, expect, it } from "vitest";

import en from "../../messages/en.json";
import bn from "../../messages/bn.json";
import { defaultLocale, isLocale, locales } from "./config";
import { loadMessages } from "./messages";

function flatten(obj: Record<string, unknown>, prefix = ""): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object") {
      Object.assign(out, flatten(value as Record<string, unknown>, path));
    } else {
      out[path] = String(value);
    }
  }
  return out;
}

const enFlat = flatten(en as Record<string, unknown>);
const bnFlat = flatten(bn as Record<string, unknown>);
const enKeys = Object.keys(enFlat);

// Feature: care-connect-emr, Property 50: Every referenced UI key resolves in
// the selected locale — for any user-facing message key referenced by the
// application, the catalog for the selected language (Bangla or English)
// contains a non-empty translation for that key.
// Validates: Requirements 18.1, 18.2
describe("Property 50: message key resolution", () => {
  it("every English key has a non-empty Bangla translation", () => {
    fc.assert(
      fc.property(fc.constantFrom(...enKeys), (key) => {
        expect(bnFlat).toHaveProperty([key]);
        expect(bnFlat[key]?.trim().length ?? 0).toBeGreaterThan(0);
      }),
      { numRuns: 100 },
    );
  });

  it("the two catalogs have identical key sets", () => {
    expect(Object.keys(bnFlat).sort()).toEqual(enKeys.slice().sort());
  });
});

// Feature: care-connect-emr, Property 51: Locale defaults to English when unset
// — for any user with no language preference set, the resolved display language
// is English.
// Validates: Requirements 18.4
describe("Property 51: default locale", () => {
  it("default locale is English", () => {
    expect(defaultLocale).toBe("en");
  });

  it("isLocale only accepts supported locales", () => {
    fc.assert(
      fc.property(fc.string(), (s) => {
        const supported = (locales as readonly string[]).includes(s);
        expect(isLocale(s)).toBe(supported);
      }),
      { numRuns: 100 },
    );
  });
});

// Unit (17.5): catalog-load fallback — when a locale cannot be loaded, English
// is returned and the fallback is signalled so the UI can show a notice (Req 18.5).
describe("Localization fallback (Req 18.5)", () => {
  it("falls back to English for an unloadable locale", async () => {
    const result = await loadMessages("xx" as never);
    expect(result.resolvedLocale).toBe("en");
    expect(result.fellBack).toBe(true);
  });

  it("loads the requested locale without falling back", async () => {
    const result = await loadMessages("bn");
    expect(result.resolvedLocale).toBe("bn");
    expect(result.fellBack).toBe(false);
  });
});
