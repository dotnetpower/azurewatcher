import { describe, expect, test } from "vitest";
import {
  mergeObservationSource,
  normalizeObservationSource,
  observationSourceLabel,
} from "./observation-source";

describe("observation source", () => {
  test("normalizes legacy and unknown values without environment inference", () => {
    expect(normalizeObservationSource(undefined)).toBe("unknown");
    expect(normalizeObservationSource("future-source")).toBe("unknown");
    expect(normalizeObservationSource("replay")).toBe("replay");
  });

  test("promotes known source and marks conflicting known sources mixed", () => {
    expect(mergeObservationSource("unknown", "synthetic-dev")).toBe("synthetic-dev");
    expect(mergeObservationSource("synthetic-dev", "unknown")).toBe("synthetic-dev");
    expect(mergeObservationSource("synthetic-dev", "replay")).toBe("mixed");
    expect(observationSourceLabel("runtime-observed")).toBe("Runtime observed");
  });
});
