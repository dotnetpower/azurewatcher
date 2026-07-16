import { describe, expect, it } from "vitest";
import { decodeUserContext } from "./user-context-client";

const payload = {
  preference: {
    principal_id: "user-1",
    locale: "en",
    verbosity: "concise",
    timezone: "UTC",
    share_with_learner: false,
    revision: 1,
  },
  memories: [],
  policies: [],
  subscriptions: [],
  briefing_runs: [],
  conversations: [],
};

describe("user-context decoder", () => {
  it("decodes a complete account context", () => {
    const decoded = decodeUserContext(payload);
    expect(decoded.preference?.timezone).toBe("UTC");
    expect(decoded.memories).toEqual([]);
  });

  it.each([
    { ...payload, memories: null },
    { ...payload, preference: { ...payload.preference, share_with_learner: "false" } },
    { ...payload, preference: { ...payload.preference, revision: -1 } },
    { ...payload, preference: { ...payload.preference, locale: "fr" } },
  ])("rejects malformed account context %#", (value) => {
    expect(() => decodeUserContext(value)).toThrow();
  });
});
