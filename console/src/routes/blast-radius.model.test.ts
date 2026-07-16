import { describe, expect, test } from "vitest";
import { blastRadiusHref, blastRadiusQueryFromSearch } from "./blast-radius.model";

describe("blast-radius route query", () => {
  test("decodes a shareable simulation query", () => {
    expect(blastRadiusQueryFromSearch(
      "?target=web-api&depth=4&links=contains,attached_to&view=production",
    )).toEqual({
      target: "web-api",
      depth: 4,
      links: ["contains", "attached_to"],
      architectureView: "production",
    });
  });

  test("bounds depth and removes unsupported links", () => {
    expect(blastRadiusQueryFromSearch("?depth=99&links=unknown")).toEqual({
      target: null,
      depth: 2,
      links: ["contains", "depends_on"],
      architectureView: null,
    });
  });

  test("builds a clean URL that round-trips", () => {
    const href = blastRadiusHref({
      target: "database-primary",
      depth: 3,
      links: ["depends_on"],
      architectureView: null,
    });
    expect(href).toBe("/blast-radius?target=database-primary&depth=3&links=depends_on");
    expect(blastRadiusQueryFromSearch(new URL(href, "http://localhost").search).target)
      .toBe("database-primary");
  });
});
