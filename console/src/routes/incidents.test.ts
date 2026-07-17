import { describe, expect, it } from "vitest";
import { resolveIncidentSelection } from "./incidents";

const incidents = [
  { correlation_id: "correlation-1" },
  { correlation_id: "correlation-2" },
];

describe("incident deep-link selection", () => {
  it("uses the first incident only when no correlation was requested", () => {
    expect(resolveIncidentSelection(incidents, null)).toBe("correlation-1");
    expect(resolveIncidentSelection([], null)).toBeNull();
  });

  it("preserves an explicit correlation that is not in the loaded page", () => {
    expect(resolveIncidentSelection(incidents, "missing-correlation"))
      .toBe("missing-correlation");
  });
});
