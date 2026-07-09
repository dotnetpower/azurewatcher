import { describe, expect, it } from "vitest";
import { relevantCitations, type Citation } from "./citations";

const SCREEN: Citation = { label: "screen", value: "Rules - 8548 rules (61 active)" };

describe("relevantCitations", () => {
  it("always keeps the screen context", () => {
    const out = relevantCitations([SCREEN], "anything");
    expect(out).toEqual([SCREEN]);
  });

  it("always keeps records.* collections", () => {
    const cites: Citation[] = [SCREEN, { label: "records.rules", value: "100 row(s)" }];
    const out = relevantCitations(cites, "there are 61 active rules");
    expect(out.map((c) => c.label)).toEqual(["screen", "records.rules"]);
  });

  it("keeps a fact only when the answer references its value", () => {
    const cites: Citation[] = [
      SCREEN,
      { label: "active_rules", value: "61" },
      { label: "tiles.empty", value: "60" },
    ];
    const out = relevantCitations(cites, "There are 61 active rules.");
    expect(out.map((c) => c.label)).toEqual(["screen", "active_rules"]);
    // tiles.empty (60) is not referenced -> dropped as noise.
    expect(out.some((c) => c.label === "tiles.empty")).toBe(false);
  });

  it("ignores single-character values to avoid spurious matches", () => {
    const cites: Citation[] = [SCREEN, { label: "depth", value: "3" }];
    // "3" would match almost any answer; require >= 2 chars.
    const out = relevantCitations(cites, "the value is 3 here");
    expect(out.map((c) => c.label)).toEqual(["screen"]);
  });

  it("matches case-insensitively", () => {
    const cites: Citation[] = [SCREEN, { label: "mode", value: "Enforce" }];
    const out = relevantCitations(cites, "the latest entry is in enforce mode");
    expect(out.map((c) => c.label)).toEqual(["screen", "mode"]);
  });

  it("falls back to the first citation when nothing qualifies", () => {
    const cites: Citation[] = [
      { label: "eps", value: "4.2" },
      { label: "tiles.empty", value: "60" },
    ];
    const out = relevantCitations(cites, "unrelated answer with no numbers");
    expect(out).toEqual([cites[0]]);
  });

  it("returns empty for no citations", () => {
    expect(relevantCitations([], "anything")).toEqual([]);
  });
});
