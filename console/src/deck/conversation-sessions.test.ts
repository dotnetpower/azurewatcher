import { describe, expect, it } from "vitest";
import {
  conversationIndexKeyFor,
  conversationPath,
  conversationUserScope,
  conversationTitle,
  isScreenConversationKey,
  parseConversationIndex,
  screenConversationKey,
  serializeConversationIndex,
  upsertConversation,
  userConversationKey,
  type ConversationSummary,
} from "./conversation-sessions";

const GENERAL: ConversationSummary = {
  key: "screen",
  label: "General",
  kind: "general",
  updatedAt: "2026-07-14T09:00:00Z",
};

describe("conversation index", () => {
  it("round-trips valid summaries and skips malformed entries", () => {
    const raw = JSON.stringify([
      GENERAL,
      { key: "missing-label", kind: "general", updatedAt: GENERAL.updatedAt },
      { key: "bad-date", label: "Bad", kind: "general", updatedAt: "not-a-date" },
    ]);

    expect(parseConversationIndex(raw)).toEqual([GENERAL]);
    expect(parseConversationIndex(serializeConversationIndex([GENERAL]))).toEqual([GENERAL]);
  });

  it("deduplicates and orders the newest conversation first", () => {
    const updated = { ...GENERAL, label: "General updated", updatedAt: "2026-07-14T10:00:00Z" };
    const agent: ConversationSummary = {
      key: "agent:Forseti",
      label: "Forseti",
      kind: "agent",
      agent: "Forseti",
      updatedAt: "2026-07-14T09:30:00Z",
    };

    expect(upsertConversation([GENERAL, agent], updated)).toEqual([updated, agent]);
  });

  it("caps the index while retaining the general conversation", () => {
    const conversations = [
      GENERAL,
      { ...GENERAL, key: "conversation:1", label: "One", updatedAt: "2026-07-14T10:00:00Z" },
      { ...GENERAL, key: "conversation:2", label: "Two", updatedAt: "2026-07-14T11:00:00Z" },
    ];

    expect(upsertConversation(conversations, conversations[2]!, 2).map((item) => item.key))
      .toEqual(["conversation:2", "screen"]);
  });
});

describe("user and route conversation ownership", () => {
  it("isolates users without exposing their identity in storage keys", () => {
    const first = conversationUserScope("first@example.com", false);
    const second = conversationUserScope("second@example.com", false);

    expect(first).not.toBe(second);
    expect(first).toMatch(/^[0-9a-f]{8}$/);
    expect(conversationIndexKeyFor(first)).not.toContain("example.com");
  });

  it("creates a distinct default session per canonical pathname", () => {
    const scope = conversationUserScope("operator@example.com", false);

    expect(screenConversationKey(scope, "/overview"))
      .not.toBe(screenConversationKey(scope, "/operating-outcomes/mttr"));
    expect(screenConversationKey(scope, "//OVERVIEW/"))
      .toBe(screenConversationKey(scope, "/overview"));
    expect(conversationPath("/overview?window=30d")).toBe("/overview");
    expect(isScreenConversationKey(screenConversationKey(scope, "/overview"))).toBe(true);
    expect(isScreenConversationKey("conversation:1")).toBe(false);
  });

  it("scopes explicit agent sessions once per user", () => {
    const scope = conversationUserScope("operator@example.com", false);
    const key = userConversationKey(scope, "agent:Forseti");

    expect(userConversationKey(scope, key)).toBe(key);
    expect(key).toContain("agent:Forseti");
  });
});

describe("conversationTitle", () => {
  it("normalizes whitespace and truncates long first prompts", () => {
    expect(conversationTitle("  Explain   this incident  ")).toBe("Explain this incident");
    expect(conversationTitle("abcdefghij", 8)).toBe("abcde...");
  });
});
