import { describe, expect, it } from "vitest";
import {
  EMPTY_HISTORY,
  record,
  recallNewer,
  recallOlder,
  type DraftHistory,
} from "./draft-history";

describe("draft-history record", () => {
  it("appends a trimmed prompt and resets the cursor", () => {
    const h = record(EMPTY_HISTORY, "  what is the tier mix?  ");
    expect(h.entries).toEqual(["what is the tier mix?"]);
    expect(h.cursor).toBeNull();
    expect(h.stashedDraft).toBe("");
  });

  it("ignores a blank prompt but clears any recall state", () => {
    const seeded: DraftHistory = { entries: ["a"], cursor: 0, stashedDraft: "x" };
    const h = record(seeded, "   ");
    expect(h.entries).toEqual(["a"]);
    expect(h.cursor).toBeNull();
    expect(h.stashedDraft).toBe("");
  });

  it("drops an immediate duplicate of the newest entry", () => {
    let h = record(EMPTY_HISTORY, "same");
    h = record(h, "same");
    expect(h.entries).toEqual(["same"]);
  });

  it("keeps non-adjacent duplicates", () => {
    let h = record(EMPTY_HISTORY, "a");
    h = record(h, "b");
    h = record(h, "a");
    expect(h.entries).toEqual(["a", "b", "a"]);
  });

  it("caps the buffer to the limit, keeping the newest", () => {
    let h = EMPTY_HISTORY;
    for (const p of ["a", "b", "c", "d"]) h = record(h, p, 2);
    expect(h.entries).toEqual(["c", "d"]);
  });
});

describe("draft-history recall", () => {
  const seed = (): DraftHistory => {
    let h = EMPTY_HISTORY;
    for (const p of ["first", "second", "third"]) h = record(h, p);
    return h;
  };

  it("Up from a live draft stashes it and jumps to the newest entry", () => {
    const r = recallOlder(seed(), "half-typed");
    expect(r.draft).toBe("third");
    expect(r.history.cursor).toBe(2);
    expect(r.history.stashedDraft).toBe("half-typed");
  });

  it("successive Ups walk toward older entries and stop at the oldest", () => {
    let r = recallOlder(seed(), "draft");
    r = recallOlder(r.history, "draft");
    r = recallOlder(r.history, "draft");
    expect(r.draft).toBe("first");
    expect(r.history.cursor).toBe(0);
    // One more Up stays pinned to the oldest.
    r = recallOlder(r.history, "draft");
    expect(r.draft).toBe("first");
    expect(r.history.cursor).toBe(0);
  });

  it("Down walks back toward newer entries and restores the stashed draft", () => {
    let r = recallOlder(seed(), "draft"); // -> third
    r = recallOlder(r.history, "draft"); // -> second
    r = recallNewer(r.history); // -> third
    expect(r.draft).toBe("third");
    r = recallNewer(r.history); // past newest -> restore draft
    expect(r.draft).toBe("draft");
    expect(r.history.cursor).toBeNull();
    expect(r.history.stashedDraft).toBe("");
  });

  it("Down while not recalling is a no-op that leaves the draft unchanged", () => {
    const r = recallNewer(seed());
    expect(r.draft).toBeNull();
    expect(r.history.cursor).toBeNull();
  });

  it("Up on empty history leaves the draft unchanged", () => {
    const r = recallOlder(EMPTY_HISTORY, "draft");
    expect(r.draft).toBeNull();
  });
});
