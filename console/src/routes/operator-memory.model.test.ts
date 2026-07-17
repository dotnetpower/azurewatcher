import { describe, expect, test } from "vitest";
import {
  decodeOperatorMemory,
  nextOperatorMemoryExpiryDelay,
  operatorMemoryDisplayState,
} from "./operator-memory.model";

describe("operator memory review contract", () => {
  test("expires an active memory at its TTL boundary", () => {
    const view = decodeOperatorMemory({ items: [{
      id: "memory-1",
      scope_kind: "resource-group",
      scope_ref: "resource-group:example",
      category: "preference",
      body: "Use the approved window.",
      source_event: "hil.reject",
      source_ref: "hil.reject:1",
      author: "operator-a",
      approved_by: "operator-b",
      approval_state: "approved",
      created_at: "2026-07-17T10:00:00+00:00",
      expires_at: "2026-07-17T10:05:00+00:00",
      expired: false,
      superseded_by: null,
      active: true,
    }], compactions: [] });
    const item = view.items[0]!;
    const before = Date.parse(item.expiresAt!) - 1_000;
    expect(operatorMemoryDisplayState(item, before)).toBe("active");
    expect(nextOperatorMemoryExpiryDelay([item], before)).toBe(1_020);
    expect(operatorMemoryDisplayState(item, before + 1_000)).toBe("expired");
  });

  test("decodes provenance scope approval expiry and supersession", () => {
    const view = decodeOperatorMemory({ items: [{
      id: "memory-1",
      scope_kind: "resource-group",
      scope_ref: "resource-group:example",
      category: "preference",
      body: "Use the approved window.",
      source_event: "hil.reject",
      source_ref: "hil.reject:1",
      author: "operator-a",
      approved_by: "operator-b",
      approval_state: "approved",
      created_at: "2026-07-17T10:00:00+00:00",
      expires_at: null,
      expired: false,
      superseded_by: null,
      active: true,
    }], compactions: [{
      candidate_id: "memory-compaction:1",
      scope_kind: "resource-group",
      scope_ref: "resource-group:example",
      category: "preference",
      body: "Compacted guidance.",
      source_refs: ["hil.reject:1", "hil.reject:2"],
      proposed_by_agent: "Norns",
      state: "approved",
      reviewed_by: "owner-a",
      review_reason: "Grounded.",
    }] });

    expect(view.items[0]?.sourceRef).toBe("hil.reject:1");
    expect(view.items[0]?.approvalState).toBe("approved");
    expect(view.items[0]?.active).toBe(true);
    expect(view.compactions[0]?.sourceRefs).toEqual(["hil.reject:1", "hil.reject:2"]);
  });
});
