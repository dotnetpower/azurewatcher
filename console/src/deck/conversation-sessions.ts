/**
 * Browser-side conversation index for the command deck.
 *
 * The audit log remains the conversation source of truth. This small index is
 * only a tab-scoped navigation aid: it remembers which cached transcripts are
 * available so the deck can render the same history + new-conversation shell
 * as the design mock.
 */

export const CONVERSATION_INDEX_KEY = "fdai.deck.conversations.v1";
export const GENERAL_CONVERSATION_KEY = "screen";
const DEFAULT_MAX_CONVERSATIONS = 24;

/** Produce a stable, non-identifying browser scope for one signed-in user. */
export function conversationUserScope(identity: string | null, devMode: boolean): string {
  const normalized = (identity?.trim().toLowerCase() || (devMode ? "dev" : "anonymous"));
  let hash = 0x811c9dc5;
  for (let index = 0; index < normalized.length; index += 1) {
    hash ^= normalized.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

/** Normalize a route pathname for conversation ownership; query is excluded. */
export function conversationPath(pathname: string): string {
  const pathOnly = pathname.split(/[?#]/, 1)[0] ?? "";
  const withLeadingSlash = pathOnly.startsWith("/") ? pathOnly : `/${pathOnly}`;
  const normalized = withLeadingSlash.replace(/\/+/g, "/").replace(/\/$/, "");
  return normalized === "" ? "/" : normalized.toLowerCase();
}

/** One default Command Deck conversation per user and canonical menu URL. */
export function screenConversationKey(userScope: string, pathname: string): string {
  return `screen:${userScope}:${conversationPath(pathname)}`;
}

export function isScreenConversationKey(key: string): boolean {
  return key === GENERAL_CONVERSATION_KEY || key.startsWith("screen:");
}

/** Scope explicit agent or manually-created conversation keys to one user. */
export function userConversationKey(userScope: string, key: string): string {
  const prefix = `user:${userScope}:`;
  return key.startsWith(prefix) ? key : `${prefix}${key}`;
}

/** Keep the browser conversation index isolated when accounts change in one tab. */
export function conversationIndexKeyFor(userScope: string): string {
  return `${CONVERSATION_INDEX_KEY}::${userScope}`;
}

export interface ConversationSummary {
  readonly key: string;
  readonly label: string;
  readonly kind: "general" | "agent";
  readonly agent?: string;
  readonly updatedAt: string;
}

/** Parse the tab-scoped index defensively. */
export function parseConversationIndex(raw: string | null): ConversationSummary[] {
  if (!raw) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  const out: ConversationSummary[] = [];
  for (const item of parsed) {
    if (item === null || typeof item !== "object" || Array.isArray(item)) continue;
    const record = item as Record<string, unknown>;
    if (typeof record.key !== "string" || record.key.length === 0) continue;
    if (typeof record.label !== "string" || record.label.length === 0) continue;
    if (record.kind !== "general" && record.kind !== "agent") continue;
    if (typeof record.updatedAt !== "string" || Number.isNaN(Date.parse(record.updatedAt))) {
      continue;
    }
    out.push({
      key: record.key,
      label: record.label,
      kind: record.kind,
      updatedAt: record.updatedAt,
      ...(typeof record.agent === "string" && record.agent.length > 0
        ? { agent: record.agent }
        : {}),
    });
  }
  return out;
}

/** Deduplicate, sort newest-first, and cap the tab-scoped index. */
export function upsertConversation(
  conversations: readonly ConversationSummary[],
  summary: ConversationSummary,
  maxConversations: number = DEFAULT_MAX_CONVERSATIONS,
): ConversationSummary[] {
  if (maxConversations <= 0) return [];
  const ordered = [summary, ...conversations.filter((item) => item.key !== summary.key)]
    .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));
  const retained = ordered.slice(0, maxConversations);
  const screen = ordered.find((item) => isScreenConversationKey(item.key));
  if (screen && !retained.some((item) => item.key === screen.key)) {
    retained[Math.max(0, retained.length - 1)] = screen;
  }
  return retained;
}

export function serializeConversationIndex(
  conversations: readonly ConversationSummary[],
): string {
  return JSON.stringify(conversations);
}

/** Build a concise title from the first operator turn. */
export function conversationTitle(prompt: string, maxLength: number = 44): string {
  const normalized = prompt.trim().replace(/\s+/g, " ");
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, Math.max(1, maxLength - 3)).trimEnd()}...`;
}
