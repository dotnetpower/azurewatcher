import { describe, expect, it } from "vitest";
import {
  formatMeasuredSavings,
  guardDisplayState,
  measuredTierValue,
  routingParamsForTier,
  searchParamsRecord,
  verticalResolutionRate,
} from "./analytics-hubs";

describe("trust-routing measurements", () => {
  it("preserves observed zero and negative monthly savings", () => {
    expect(formatMeasuredSavings(0)).toContain("0");
    expect(formatMeasuredSavings(-25)).toBe("-$25");
  });

  it("distinguishes an observed zero from a missing tier", () => {
    expect(measuredTierValue({ t0: 0 }, "t0")).toBe(0);
    expect(measuredTierValue({ t0: 0 }, "t1")).toBeNull();
  });

  it("does not infer a zero resolution rate from an empty vertical", () => {
    expect(verticalResolutionRate({
      key: "resilience",
      events: 0,
      auto_resolved: 0,
      open_risks: 0,
      monthly_savings: 0,
    })).toBeNull();
    expect(verticalResolutionRate({
      key: "resilience",
      events: 4,
      auto_resolved: 3,
      open_risks: 0,
      monthly_savings: 0,
    })).toBe(0.75);
  });

  it("never turns synthetic guard values into operational verdicts", () => {
    expect(guardDisplayState(true, true)).toBe("simulated");
    expect(guardDisplayState(true, false)).toBe("simulated");
    expect(guardDisplayState(false, true)).toBe("passing");
    expect(guardDisplayState(false, false)).toBe("blocked");
  });

  it("preserves active query state across analytical tabs", () => {
    const search = new URLSearchParams("window=30d&guard=rollback");
    expect(searchParamsRecord(search)).toEqual({ window: "30d", guard: "rollback" });
  });

  it("drops a T2-only indicator when navigating to another tier", () => {
    const search = new URLSearchParams("window=30d&indicator=verifier");
    expect(routingParamsForTier("t2", search)).toEqual({
      window: "30d",
      indicator: "verifier",
    });
    expect(routingParamsForTier("t0", search)).toEqual({ window: "30d" });
  });
});
