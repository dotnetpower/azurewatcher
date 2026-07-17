import type { AuditPage } from "../types";

export interface AuditData {
  readonly items: AuditPage["items"];
  readonly nextCursor: string | null;
}

export type AuditEntrySelection =
  | { readonly status: "none" }
  | { readonly status: "invalid"; readonly value: string }
  | { readonly status: "selected"; readonly seq: number }
  | { readonly status: "pending"; readonly seq: number }
  | { readonly status: "unavailable"; readonly seq: number };

export function resolveAuditEntry(
  data: AuditData,
  requested: string | null,
): AuditEntrySelection {
  if (requested === null) return { status: "none" };
  if (!/^[1-9][0-9]*$/.test(requested)) {
    return { status: "invalid", value: requested };
  }
  const seq = Number(requested);
  if (!Number.isSafeInteger(seq)) return { status: "invalid", value: requested };
  if (data.items.some((item) => item.seq === seq)) return { status: "selected", seq };
  return data.nextCursor === null
    ? { status: "unavailable", seq }
    : { status: "pending", seq };
}

export function appendAuditPage(
  current: AuditData,
  requestedCursor: string,
  page: AuditPage,
): AuditData {
  if (current.nextCursor !== requestedCursor) return current;
  const seen = new Set(current.items.map((item) => item.seq));
  return {
    items: [...current.items, ...page.items.filter((item) => !seen.has(item.seq))],
    nextCursor: page.next_cursor,
  };
}
