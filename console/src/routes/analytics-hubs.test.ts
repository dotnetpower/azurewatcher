import { describe, expect, it } from "vitest";
import { formatMeasuredSavings, measuredTierValue } from "./analytics-hubs";

describe("trust-routing measurements", () => {
  it("preserves observed zero and negative monthly savings", () => {
    expect(formatMeasuredSavings(0)).toContain("0");
    expect(formatMeasuredSavings(-25)).toBe("-$25");
  });

  it("distinguishes an observed zero from a missing tier", () => {
    expect(measuredTierValue({ t0: 0 }, "t0")).toBe(0);
    expect(measuredTierValue({ t0: 0 }, "t1")).toBeNull();
  });
});
