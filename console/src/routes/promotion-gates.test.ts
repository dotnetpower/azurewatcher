import { describe, expect, it } from "vitest";
import { filterPromotionRows, promotionReasonFromValue } from "./promotion-gates";

const rows = [
  {
    action_type_name: "safe-action",
    shadow_days_elapsed: 7,
    sample_count: 100,
    reviewed_count: 100,
    agreed_count: 100,
    policy_escapes: 0,
    accuracy: 1,
    ready: true,
    gaps: [],
  },
  {
    action_type_name: "escaped-action",
    shadow_days_elapsed: 3,
    sample_count: 20,
    reviewed_count: 10,
    agreed_count: 8,
    policy_escapes: 2,
    accuracy: 0.8,
    ready: false,
    gaps: ["zero policy escapes required"],
  },
] as const;

describe("promotion gate drilldown filters", () => {
  it("distinguishes a supported reason from an invalid explicit reason", () => {
    expect(promotionReasonFromValue(null)).toEqual({ reason: null, invalid: null });
    expect(promotionReasonFromValue("policy-escape")).toEqual({
      reason: "policy-escape",
      invalid: null,
    });
    expect(promotionReasonFromValue("missing")).toEqual({ reason: null, invalid: "missing" });
  });

  it("shows only blocked rows with recorded policy escapes", () => {
    expect(filterPromotionRows(rows, "blocked", "", "policy-escape").map((row) => row.action_type_name))
      .toEqual(["escaped-action"]);
  });

  it("combines status and free-text filters without policy escape mode", () => {
    expect(filterPromotionRows(rows, "ready", "safe", null).map((row) => row.action_type_name))
      .toEqual(["safe-action"]);
  });
});
