/**
 * Draft history - shell-style Up/Down recall for the command deck input.
 *
 * Pure and UI-agnostic so it is unit-tested directly. The deck keeps a list of
 * previously submitted operator prompts (oldest first, newest last) and a
 * recall cursor. Arrow-Up walks toward older entries; Arrow-Down walks back
 * toward the live draft. The in-progress draft is stashed the moment recall
 * starts and restored when the cursor returns past the newest entry - exactly
 * like a terminal history buffer.
 *
 * Single responsibility: model the recall state transitions. No I/O, no DOM,
 * no privileged calls.
 */

export interface DraftHistory {
  /** Submitted prompts, oldest first, newest last. Capped to the record limit. */
  readonly entries: readonly string[];
  /**
   * Recall position. ``null`` means "editing the live draft" (not recalling);
   * otherwise an index into ``entries``.
   */
  readonly cursor: number | null;
  /** The live draft stashed when recall began, restored on Down past newest. */
  readonly stashedDraft: string;
}

export const EMPTY_HISTORY: DraftHistory = {
  entries: [],
  cursor: null,
  stashedDraft: "",
};

const DEFAULT_LIMIT = 50;

/**
 * Record a submitted prompt. Resets the recall cursor, drops an immediate
 * duplicate of the newest entry, ignores blank prompts, and caps the buffer.
 */
export function record(
  history: DraftHistory,
  prompt: string,
  limit: number = DEFAULT_LIMIT,
): DraftHistory {
  const trimmed = prompt.trim();
  if (trimmed.length === 0) {
    return { ...history, cursor: null, stashedDraft: "" };
  }
  const newest = history.entries[history.entries.length - 1];
  const base = newest === trimmed ? history.entries.slice(0, -1) : history.entries;
  const next = [...base, trimmed].slice(-limit);
  return { entries: next, cursor: null, stashedDraft: "" };
}

export interface RecallResult {
  readonly history: DraftHistory;
  /** The text the input should now show, or ``null`` to leave the draft as-is. */
  readonly draft: string | null;
}

/** Arrow-Up: step to an older entry, stashing the live draft on the first step. */
export function recallOlder(history: DraftHistory, liveDraft: string): RecallResult {
  if (history.entries.length === 0) return { history, draft: null };
  if (history.cursor === null) {
    const cursor = history.entries.length - 1;
    return {
      history: { ...history, cursor, stashedDraft: liveDraft },
      draft: history.entries[cursor] ?? "",
    };
  }
  if (history.cursor === 0) {
    return { history, draft: history.entries[0] ?? "" };
  }
  const cursor = history.cursor - 1;
  return { history: { ...history, cursor }, draft: history.entries[cursor] ?? "" };
}

/** Arrow-Down: step to a newer entry, restoring the stashed draft past newest. */
export function recallNewer(history: DraftHistory): RecallResult {
  if (history.cursor === null) return { history, draft: null };
  const nextCursor = history.cursor + 1;
  if (nextCursor >= history.entries.length) {
    const draft = history.stashedDraft;
    return { history: { ...history, cursor: null, stashedDraft: "" }, draft };
  }
  return {
    history: { ...history, cursor: nextCursor },
    draft: history.entries[nextCursor] ?? "",
  };
}
