import { describe, expect, it } from "vitest";
import { mergeIncidentItems, parseIncidentVertical, resolveIncidentSelection } from "./incidents";

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

describe("incident route filters", () => {
  it("normalizes the four server-supported vertical values", () => {
    expect(parseIncidentVertical("change-safety")).toBe("change_safety");
    expect(parseIncidentVertical("COST_GOVERNANCE")).toBe("cost_governance");
    expect(parseIncidentVertical("resilience")).toBe("resilience");
    expect(parseIncidentVertical("unknown")).toBe("unknown");
  });

  it("drops unsupported or empty vertical values", () => {
    expect(parseIncidentVertical("../../other")).toBeNull();
    expect(parseIncidentVertical("")).toBeNull();
    expect(parseIncidentVertical(null)).toBeNull();
  });
});

describe("incident pagination", () => {
  it("keeps roster order and removes duplicate correlation ids", () => {
    const current = [{ correlation_id: "a" }, { correlation_id: "b" }];
    const incoming = [{ correlation_id: "b" }, { correlation_id: "c" }];
    expect(mergeIncidentItems(current as never, incoming as never).map((item) => item.correlation_id))
      .toEqual(["a", "b", "c"]);
  });

  it("can prepend one exact deep-link result without duplicating the roster", () => {
    const current = [{ correlation_id: "a" }, { correlation_id: "b" }];
    const exact = [{ correlation_id: "b" }];
    expect(mergeIncidentItems(exact as never, current as never).map((item) => item.correlation_id))
      .toEqual(["b", "a"]);
  });
});
