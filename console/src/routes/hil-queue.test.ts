import { describe, expect, test } from "vitest";
import type { HilQueueItem } from "../types";
import { nextApprovalExpiryDelay } from "./hil-queue";

function item(expiresAt: string | null): HilQueueItem {
  return { ttl_expires_at: expiresAt } as HilQueueItem;
}

describe("approval expiry clock", () => {
  test("schedules the nearest future expiry and ignores expired or missing TTLs", () => {
    const now = Date.parse("2026-07-17T09:00:00Z");
    expect(nextApprovalExpiryDelay([
      item(null),
      item("2026-07-17T08:59:00Z"),
      item("2026-07-17T09:00:05Z"),
      item("2026-07-17T09:00:20Z"),
    ], now)).toBe(5_020);
    expect(nextApprovalExpiryDelay([item(null), item("2026-07-17T08:59:00Z")], now))
      .toBeNull();
  });
});
