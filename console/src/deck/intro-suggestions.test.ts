import { describe, expect, it } from "vitest";
import { introSuggestions } from "./intro-suggestions";
import type { ViewFact, ViewSnapshot } from "./context";

function snap(facts: ViewFact[]): ViewSnapshot {
  return {
    routeId: "live",
    routeLabel: "Live cockpit",
    headline: "test",
    facts,
    capturedAt: "2026-07-10T00:00:00Z",
  };
}

describe("introSuggestions", () => {
  it("offers route discovery when there is no snapshot", () => {
    expect(introSuggestions(null)).toEqual(["what routes are available?"]);
  });

  it("falls back to evergreen prompts when nothing notable is on screen", () => {
    const s = introSuggestions(snap([{ key: "eps", value: 4 }]));
    expect(s).toEqual([
      "what do you see on this screen?",
      "what is the tier mix right now?",
    ]);
  });

  it("surfaces failed actions first when present", () => {
    const s = introSuggestions(snap([{ key: "attention.failed", value: 3 }]));
    expect(s[0]).toBe("why did the failed actions fail?");
  });

  it("surfaces approvals from either attention.hil or gate.hil", () => {
    expect(introSuggestions(snap([{ key: "gate.hil", value: 2 }]))).toContain(
      "what is waiting for approval?",
    );
    expect(introSuggestions(snap([{ key: "attention.hil", value: 1 }]))).toContain(
      "what is waiting for approval?",
    );
  });

  it("caps to five suggestions and de-duplicates", () => {
    const s = introSuggestions(
      snap([
        { key: "attention.failed", value: 1 },
        { key: "attention.hil", value: 1 },
        { key: "gate.hil", value: 1 },
        { key: "gate.deny", value: 1 },
        { key: "attention.stuck", value: 1 },
      ]),
    );
    expect(s.length).toBe(5);
    expect(new Set(s).size).toBe(5);
    // Situational prompts win the cap over the trailing evergreen ones.
    expect(s).toContain("why did the failed actions fail?");
    expect(s).toContain("which actions are stuck?");
  });

  it("treats numeric strings as counts and ignores zero", () => {
    expect(introSuggestions(snap([{ key: "attention.failed", value: "0" }]))).not.toContain(
      "why did the failed actions fail?",
    );
    expect(introSuggestions(snap([{ key: "attention.failed", value: "2" }]))).toContain(
      "why did the failed actions fail?",
    );
  });
});
