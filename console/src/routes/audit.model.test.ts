import { describe, expect, test } from "vitest";
import type { AuditItem } from "../types";
import { appendAuditPage, resolveAuditEntry } from "./audit.model";
import { auditFiltersFromSearch } from "./audit";

function item(seq: number): AuditItem {
  return { seq, event_id: `event-${seq}`, correlation_id: null, actor: "fdai", action_kind: "test", mode: "shadow", entry: {}, entry_hash: "hash", previous_hash: "previous", recorded_at: "2026-07-13T00:00:00Z" };
}

describe("audit pagination", () => {
  test("turns an exact entry link into immutable server-side sequence bounds", () => {
    const filters = auditFiltersFromSearch(new URLSearchParams("entry=42"));
    expect(filters.fromSeq).toBe(42);
    expect(filters.throughSeq).toBe(42);
    expect(filters.invalid).toEqual([]);
  });

  test("appends only the response for the current cursor", () => {
    const current = { items: [item(2)], nextCursor: "cursor-2" };
    expect(appendAuditPage(current, "stale", { items: [item(1)], next_cursor: null })).toBe(current);
    expect(appendAuditPage(current, "cursor-2", { items: [item(1)], next_cursor: null })).toEqual({ items: [item(2), item(1)], nextCursor: null });
  });

  test("deduplicates replayed audit rows", () => {
    const current = { items: [item(2)], nextCursor: "cursor-2" };
    expect(appendAuditPage(current, "cursor-2", { items: [item(2), item(1)], next_cursor: null }).items.map((row) => row.seq)).toEqual([2, 1]);
  });

  test("distinguishes selected, off-page, absent, and invalid entry links", () => {
    const page = { items: [item(2)], nextCursor: "cursor-2" };
    expect(resolveAuditEntry(page, "2")).toEqual({ status: "selected", seq: 2 });
    expect(resolveAuditEntry(page, "1")).toEqual({ status: "pending", seq: 1 });
    expect(resolveAuditEntry({ ...page, nextCursor: null }, "1")).toEqual({
      status: "unavailable",
      seq: 1,
    });
    expect(resolveAuditEntry(page, "not-a-seq")).toEqual({
      status: "invalid",
      value: "not-a-seq",
    });
  });
});
