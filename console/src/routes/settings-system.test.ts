import { describe, expect, it } from "vitest";
import { isHealthy } from "./settings-system";

describe("Settings diagnostics health contract", () => {
  it("accepts only the explicit read API health response", () => {
    expect(isHealthy({ status: "ok" })).toBe(true);
    expect(isHealthy({ status: "degraded" })).toBe(false);
    expect(isHealthy({ status: true })).toBe(false);
    expect(isHealthy(null)).toBe(false);
  });
});
