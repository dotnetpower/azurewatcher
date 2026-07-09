/**
 * Unit tests for the cockpit's pure, localizable text functions.
 *
 * `tierLabel`, `viewBadge`, and `parseScreenCommand` were extracted to module
 * scope precisely so the live TUI's user-facing strings are testable without a
 * terminal. English is the source of truth and renders byte-identical to the
 * pre-i18n cockpit; Korean is asserted structurally (no Hangul literals in this
 * .ts file, per the english-only gate) plus the mandatory English fallback.
 */

import { describe, expect, it } from "vitest";

import { localAnswer, parseScreenCommand, tierLabel, viewBadge } from "../src/cockpit.js";

const STATS = {
  handled: 10,
  byTier: { t0: 5, t1: 2, t2: 1, abstain: 2 },
  awaitingYou: 1,
  autoApplied: 4,
  undone: 0,
  activity: [{ resource: "vm-1", text: "stepped back - no matching rule yet" }],
};

describe("cockpit.tierLabel", () => {
  it("renders the English tier labels byte-identically", () => {
    expect(tierLabel("t0", "en")).toBe("fixed rules");
    expect(tierLabel("t1", "en")).toBe("past match");
    expect(tierLabel("t2", "en")).toBe("reasoning");
    expect(tierLabel("anything-else", "en")).toBe("unrouted");
  });

  it("localizes to ko where translated", () => {
    expect(tierLabel("t0", "ko")).not.toBe("fixed rules");
    expect(tierLabel("t0", "ko").length).toBeGreaterThan(0);
  });

  it("falls back to English for a lagging ko key (unrouted)", () => {
    expect(tierLabel("mystery", "ko")).toBe("unrouted");
  });
});

describe("cockpit.viewBadge", () => {
  it("renders the English badges byte-identically", () => {
    expect(viewBadge({ mode: "stream", paused: false }, "en")).toBe("STREAM");
    expect(viewBadge({ mode: "overview", paused: false }, "en")).toBe("OVERVIEW");
    expect(viewBadge({ mode: "focus", focus: "network", paused: false }, "en")).toBe(
      "FOCUS NETWORK",
    );
    expect(viewBadge({ mode: "stream", paused: true }, "en")).toBe("PAUSED");
  });

  it("localizes to ko where translated", () => {
    expect(viewBadge({ mode: "stream", paused: false }, "ko")).not.toBe("STREAM");
    expect(viewBadge({ mode: "stream", paused: true }, "ko")).not.toBe("PAUSED");
  });

  it("falls back to English for the lagging ko focus badge", () => {
    expect(viewBadge({ mode: "focus", focus: "network", paused: false }, "ko")).toBe(
      "FOCUS NETWORK",
    );
  });
});

describe("cockpit.parseScreenCommand", () => {
  it("maps English commands to a view patch + reply", () => {
    const pause = parseScreenCommand("pause", "en");
    expect(pause?.patch.paused).toBe(true);
    expect(pause?.reply).toContain("Paused");

    const focus = parseScreenCommand("focus network", "en");
    expect(focus?.patch.mode).toBe("focus");
    expect(focus?.patch.focus).toBe("network");
    expect(focus?.reply).toBe("Focusing on network resources.");

    const vague = parseScreenCommand("focus", "en");
    expect(vague?.patch.mode).toBe("stream");
    expect(vague?.reply).toBe("Which resource type? e.g. 'focus network'.");
  });

  it("accepts Korean input and still returns the (en) reply by default", () => {
    // "\uba48\ucdb0" = a Korean 'pause' verb; input parses, reply is en source.
    const pause = parseScreenCommand("\uba48\ucdb0", "en");
    expect(pause?.patch.paused).toBe(true);
    expect(pause?.reply).toContain("Paused");
  });

  it("localizes the reply when locale is ko", () => {
    const en = parseScreenCommand("pause", "en");
    const ko = parseScreenCommand("pause", "ko");
    expect(ko?.patch.paused).toBe(true); // same patch
    expect(ko?.reply).not.toBe(en?.reply); // localized reply
    expect((ko?.reply ?? "").length).toBeGreaterThan(0);
  });

  it("returns null when nothing matches", () => {
    expect(parseScreenCommand("hello there", "en")).toBeNull();
  });
});

describe("cockpit.localAnswer", () => {
  it("renders the KPI answer byte-identically in English", () => {
    expect(localAnswer("status", STATS, "en")).toBe(
      "Handled 10 events live so far - 5 with fixed rules (T0), 2 by past match (T1), " +
        "1 by reasoning (T2), 2 stepped back. 4 were auto-applied as shadow pull requests, " +
        "1 awaiting your approval, 0 undone. Nothing changes until you merge a PR.",
    );
  });

  it("answers the approval queue (some vs none)", () => {
    expect(localAnswer("awaiting approval", STATS, "en")).toContain(
      "awaiting your approval",
    );
    const none = localAnswer("approval", { ...STATS, awaitingYou: 0 }, "en");
    expect(none).toBe(
      "Nothing is awaiting your approval right now. Everything resolved automatically or was safely stepped back.",
    );
  });

  it("summarizes recent activity, or says nothing yet", () => {
    expect(localAnswer("recent activity", STATS, "en")).toBe(
      "Most recent: vm-1 stepped back.",
    );
    expect(localAnswer("recent", { ...STATS, activity: [] }, "en")).toBe(
      "Most recent: nothing yet.",
    );
  });

  it("localizes to ko, and falls back to English for the lagging trust answer", () => {
    const en = localAnswer("status", STATS, "en");
    const ko = localAnswer("status", STATS, "ko");
    expect(ko).not.toBe(en); // localized
    expect((ko ?? "").length).toBeGreaterThan(0);
    // `cockpit.answer.trust` is not translated in ko -> English fallback.
    expect(localAnswer("is this safe?", STATS, "ko")).toContain("read-only");
  });

  it("returns null for a question outside live state", () => {
    expect(localAnswer("tell me a joke", STATS, "en")).toBeNull();
  });
});
