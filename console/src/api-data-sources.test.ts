import { describe, expect, test } from "vitest";

import {
  decodeReadDataSources,
  sourceForRoute,
  unavailableSourceReason,
} from "./api-data-sources";

const payload = {
  surface: "read-data-sources",
  sources: [
    {
      key: "operational-state",
      source: "empty-local-memory",
      routes: ["/audit", "/kpi"],
      availability: "unavailable",
      configured: true,
      reachable: true,
      authoritative: false,
      durable: false,
      synthetic: false,
      reason: "Authoritative operational state is not connected.",
      last_observed_at: null,
    },
  ],
};

describe("read data sources", () => {
  test("decodes provenance and finds the owner of a route", () => {
    const decoded = decodeReadDataSources(payload);
    expect(sourceForRoute(decoded, "/kpi")?.source).toBe("empty-local-memory");
    expect(unavailableSourceReason(decoded, "/audit"))
      .toBe("Authoritative operational state is not connected.");
    expect(unavailableSourceReason(decoded, "/models/settings")).toBeNull();
  });

  test("rejects malformed and duplicate source contracts", () => {
    expect(() => decodeReadDataSources({ ...payload, surface: "other" })).toThrow();
    expect(() => decodeReadDataSources({
      ...payload,
      sources: [...payload.sources, payload.sources[0]],
    })).toThrow(/unique/);
    expect(() => decodeReadDataSources({
      ...payload,
      sources: [{ ...payload.sources[0], routes: ["audit"] }],
    })).toThrow(/absolute paths/);
  });
});
