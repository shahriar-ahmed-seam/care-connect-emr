import fc from "fast-check";
import { describe, expect, it } from "vitest";

import { contrastRatio, textColorPairs } from "./design-tokens";

describe("Property 53: design-token contrast", () => {
  it("every normal-text color pair meets WCAG AA (>= 4.5:1)", () => {
    fc.assert(
      fc.property(fc.constantFrom(...textColorPairs), (pair) => {
        const ratio = contrastRatio(pair.foreground, pair.background);
        expect(ratio).toBeGreaterThanOrEqual(4.5);
      }),
      { numRuns: 100 },
    );
  });

  it("contrast ratio is symmetric and bounded", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...textColorPairs),
        (pair) => {
          const ab = contrastRatio(pair.foreground, pair.background);
          const ba = contrastRatio(pair.background, pair.foreground);
          expect(Math.abs(ab - ba)).toBeLessThan(1e-9);
          expect(ab).toBeGreaterThanOrEqual(1);
          expect(ab).toBeLessThanOrEqual(21);
        },
      ),
      { numRuns: 100 },
    );
  });
});
