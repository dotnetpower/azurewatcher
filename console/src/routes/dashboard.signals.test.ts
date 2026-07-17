import { describe, expect, test } from "vitest";
import { livingRulesProvenance, measuredTierMix } from "./dashboard.signals";

describe("Tier evidence", () => {
  test("distinguishes a missing tier from a measured zero", () => {
    expect(measuredTierMix({}, "t0")).toBeNull();
    expect(measuredTierMix({ t0: 0 }, "t0")).toBe(0);
  });
});

describe("Living Rules provenance", () => {
  test("preserves synthetic source and as-of metadata", () => {
    expect(livingRulesProvenance({
      synthetic: true,
      source: {
        name: "synthetic-dev-harness",
        kind: "synthetic",
        as_of: "2026-07-15T00:00:00Z",
      },
    })).toEqual({
      kind: "simulated",
      source: "synthetic-dev-harness",
      asOf: "2026-07-15T00:00:00Z",
    });
  });
});
