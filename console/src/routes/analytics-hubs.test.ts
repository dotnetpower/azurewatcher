import { describe, expect, it } from "vitest";
import type { AutonomyPayload } from "../types";
import {
  formatMeasuredSavings,
  guardDisplayState,
  measuredTierValue,
  routingParamsForTier,
  searchParamsRecord,
  verticalResolutionRate,
} from "./analytics-hubs";
import { buildOperatingOutcomeViewSnapshot } from "./analytics-hubs.view";

const AUTONOMY: AutonomyPayload = {
  synthetic: false,
  window_days: 30,
  sample_size: 34,
  confidence: null,
  source: {
    name: "postgres-audit",
    kind: "audit",
    as_of: "2026-07-23T01:25:21Z",
  },
  rules: { active: 0, candidates_30d: 0, promoted_30d: 0 },
  success: {
    auto_resolution_rate: { value: 14 / 34, baseline: null, direction: "higher" },
    human_touchpoints_per_100: { value: null, baseline: null, direction: "lower" },
    mttr_seconds: { value: null, baseline: null, direction: "lower" },
    change_lead_time_seconds: { value: null, baseline: null, direction: "lower" },
    cost_per_resolved_event_usd: { value: null, baseline: null, direction: "lower" },
  },
  leading: {
    mixed_model_disagreement_rate: { value: null, baseline: null, direction: "lower" },
    verifier_failure_rate: { value: null, baseline: null, direction: "lower" },
    shadow_divergence_rate: { value: null, baseline: null, direction: "lower" },
  },
  guards: [],
  verticals: [
    { key: "resilience", events: 0, auto_resolved: 0, open_risks: 0, monthly_savings: 0 },
    { key: "change-safety", events: 34, auto_resolved: 14, open_risks: 0, monthly_savings: 0 },
    { key: "cost-governance", events: 0, auto_resolved: 0, open_risks: 0, monthly_savings: 0 },
  ],
  tier: { mix: {}, bands: {} },
  trend: {},
};

describe("trust-routing measurements", () => {
  it("publishes visible outcome evidence for Command Deck grounding", () => {
    const snapshot = buildOperatingOutcomeViewSnapshot({
      autonomy: AUTONOMY,
      metric: AUTONOMY.success.cost_per_resolved_event_usd,
      metricKey: "cost-per-resolved-event",
      metricLabel: "Cost per resolved event",
      unavailableLabel: "Unavailable",
      routeLabel: "Operating outcomes",
    });

    expect(snapshot).toMatchObject({
      routeId: "operating-outcomes",
      routeLabel: "Operating outcomes",
      capturedAt: "2026-07-23T01:25:21Z",
      explanations: {
        provenance: { authority: "audit", refs: ["postgres-audit"] },
      },
    });
    expect(snapshot.headline).toContain("current Unavailable, baseline Unavailable");
    expect(snapshot.facts).toEqual(expect.arrayContaining([
      expect.objectContaining({ key: "current_value", value: null }),
      expect.objectContaining({ key: "window_days", value: 30 }),
      expect.objectContaining({ key: "sample_size", value: 34 }),
    ]));
    expect(snapshot.records?.verticals).toContainEqual(expect.objectContaining({
      key: "change-safety",
      events: 34,
      auto_resolved: 14,
    }));
  });

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
