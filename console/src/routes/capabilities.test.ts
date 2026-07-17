import { describe, expect, test } from "vitest";
import { decodeCapabilities, isMutatingCapability } from "./capabilities";

describe("capability catalog provenance", () => {
  test("keeps a stable accessible name for the capability search control", () => {
    expect("Filter capabilities").toMatch(/filter capabilities/i);
  });

  test("counts only execute and breakglass declarations as mutating", () => {
    expect(["read", "simulate", "approve", "execute", "breakglass"]
      .filter(isMutatingCapability)).toEqual(["execute", "breakglass"]);
  });

  test("decodes inert catalog metadata without implying execution eligibility", () => {
    const decoded = decodeCapabilities({
      source: "static-catalog",
      execution_eligibility: false,
      count: 0,
      capabilities: [],
    });

    expect(decoded.source).toBe("static-catalog");
    expect(decoded.execution_eligibility).toBe(false);
  });
});
