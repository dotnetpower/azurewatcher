import { describe, expect, it } from "vitest";
import { decodeOnboarding } from "./onboarding";

const payload = {
  probe_mode: "configured",
  ready: false,
  blocked: true,
  missing_resources: ["event_bus"],
  missing_role_assignments: [["executor", "reader", "event_bus"]],
  present_resource_count: 0,
  present_role_count: 0,
};

describe("onboarding response", () => {
  it("preserves a configured probe failure", () => {
    expect(decodeOnboarding({ ...payload, error: "OnboardingProbeError:denied" }).error)
      .toBe("OnboardingProbeError:denied");
  });

  it("accepts legacy omission but rejects malformed probe errors", () => {
    expect(decodeOnboarding(payload).error).toBeNull();
    expect(() => decodeOnboarding({ ...payload, error: { message: "denied" } }))
      .toThrow(/string or null/);
  });
});
