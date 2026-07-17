import { describe, expect, it } from "vitest";
import { architectureResourceFromValue } from "./architecture-map";

describe("architecture resource navigator", () => {
  it("selects only an exact resource id", () => {
    const resources = [
      { id: "Run_A", name: "Worker", type: "compute.vm" },
    ] as never;
    expect(architectureResourceFromValue(resources, "Run_A")).toMatchObject({ id: "Run_A" });
    expect(architectureResourceFromValue(resources, "run-a")).toBeNull();
  });
});
