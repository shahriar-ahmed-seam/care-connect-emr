import fc from "fast-check";
import { describe, expect, it } from "vitest";

import { BDT_SYMBOL, formatBDT, formatDate } from "./format";

describe("Property 52: currency and date formatting", () => {
  it("formats BDT with the symbol and exactly two decimals", () => {
    fc.assert(
      fc.property(
        fc.float({ min: 0, max: 9_999_999, noNaN: true, noDefaultInfinity: true }),
        (amount) => {
          const out = formatBDT(amount);
          expect(out.startsWith(BDT_SYMBOL)).toBe(true);

          expect(/\.\d{2}$/.test(out)).toBe(true);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("formats dates as DD/MM/YYYY with correct components", () => {
    fc.assert(
      fc.property(
        fc.date({
          min: new Date("2000-01-01T00:00:00Z"),
          max: new Date("2099-12-31T00:00:00Z"),
          noInvalidDate: true,
        }),
        (date) => {
          const out = formatDate(date);
          expect(/^\d{2}\/\d{2}\/\d{4}$/.test(out)).toBe(true);
          const [dd, mm, yyyy] = out.split("/").map(Number);
          expect(dd).toBe(date.getDate());
          expect(mm).toBe(date.getMonth() + 1);
          expect(yyyy).toBe(date.getFullYear());
        },
      ),
      { numRuns: 100 },
    );
  });
});
