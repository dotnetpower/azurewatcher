/**
 * citations - pick the "grounded on" sources worth showing under a deck reply.
 *
 * The backend grounds a reply on the whole screen snapshot (the screen, its
 * facts, its record collections). Most of those facts are not what the answer
 * actually used - showing them all (e.g. tiles.empty) is noise. This module
 * narrows the list: keep the `screen` context and any `records.*` collection
 * (structural - what was grounded on and what was searchable), and keep an
 * individual fact only when the answer text references its value.
 *
 * Pure and dependency-free so it is unit-testable; grounded-reply.tsx imports
 * `relevantCitations` from here.
 */

/** One cited source (label + optional value), matching the deck Turn shape. */
export interface Citation {
  readonly label: string;
  readonly value?: string;
}

/**
 * Narrow raw snapshot citations to the relevant ones for `text`. `screen` and
 * `records.*` are always kept; a fact is kept only when its value (>=2 chars)
 * appears in the answer. Falls back to the first citation so the strip is never
 * empty when the backend supplied any.
 */
export function relevantCitations(cites: readonly Citation[], text: string): Citation[] {
  const lower = text.toLowerCase();
  const kept = cites.filter((c) => {
    if (c.label === "screen" || c.label.startsWith("records.")) return true;
    const v = c.value;
    return v !== undefined && v.length >= 2 && lower.includes(v.toLowerCase());
  });
  return kept.length > 0 ? kept : cites.slice(0, 1);
}
