import { describe, expect, test } from "vitest";
import { currentIncidentStepIndex, isAgentEventExpanded } from "./agents.detail";

describe("agent focus event selection", () => {
  test("expands only the selected event", () => {
    expect(isAgentEventExpanded("corr-selected", "corr-selected")).toBe(true);
    expect(isAgentEventExpanded("corr-other", "corr-selected")).toBe(false);
    expect(isAgentEventExpanded("corr-selected", null)).toBe(false);
  });
});

describe("incident workflow progress", () => {
  test.each([
    [[true, false, false, false], 0],
    [[true, true, false, false], 1],
    [[true, true, true, false], 2],
    [[true, true, true, true], 3],
  ])("marks the latest completed stage as current", (done, expected) => {
    expect(currentIncidentStepIndex(done.map((value) => ({ done: value })))).toBe(expected);
  });
});
