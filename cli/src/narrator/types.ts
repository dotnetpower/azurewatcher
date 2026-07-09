/**
 * Narrator seam - the console's natural-language surface.
 *
 * The narrator is a TRANSLATOR, not a judge (architecture.instructions.md -
 * Action Ontology and Console Vocabulary): it turns an operator's question into
 * read-only `console-tool` calls and answers ONLY from their results. It never
 * takes actions (the console is read-only; approvals are PR-native) and never
 * invents numbers.
 *
 * Two implementations share this interface:
 * - `DeterministicNarrator` - keyword routing, no model, always available.
 * - `LlmNarrator` - an OpenAI-compatible model that understands free-form
 *   natural language (any language, including Korean) and calls the same tools.
 *
 * `createNarrator()` picks the LLM when `FDAI_NARRATOR_*` env is configured,
 * else falls back to deterministic - so the CLI works with zero config.
 */

import type { BriefingPayload } from "../view-model/contract.js";
import type { Locale } from "../i18n/index.js";

/** What the narrator can see: a live read API, or the synthetic sample. */
export interface NarratorContext {
  /** Base URL of the live read API, or null when running on sample data. */
  apiUrl: string | null;
  /** Sample payload when `apiUrl` is null; null when live. */
  payload: BriefingPayload | null;
  /** Operator locale for rendered answers (L3). Defaults to `en`; a lagging
   * key falls back to English. Data values (ids, counts) are never translated. */
  locale?: Locale;
  /** Optional screen controller (CLI cockpit only). Lets the narrator switch
   * the on-screen view/component from natural language. Read-only: it changes
   * only what is displayed, never a cloud resource. */
  screen?: ScreenController | null;
  /** Optional live-state provider (CLI cockpit only): a compact snapshot of the
   * cockpit's own counters (handled, tiers, outcomes, resource-type mix), so
   * the narrator answers from what is on screen, not the mock seed. */
  live?: { overview: () => string } | null;
  /** Optional recent conversation (most recent last), so follow-up questions
   * ("the biggest one?", "why?") resolve against what was just discussed. */
  history?: Array<{ role: "user" | "assistant"; content: string }> | null;
}

/** A read-only handle to the cockpit's on-screen view (CLI only). */
export interface ScreenController {
  /** Switch the visible component; returns a short confirmation string. */
  setView(patch: {
    mode?: "stream" | "overview" | "focus";
    focus?: string;
    paused?: boolean;
  }): string;
}

/** One read-only console tool the narrator may call. */
export interface ConsoleTool {
  name: string;
  description: string;
  /** JSON Schema for the tool's arguments (empty object = no args). */
  parameters: Record<string, unknown>;
  /** Execute the tool read-only and return a compact factual string. */
  run(args: Record<string, unknown>, ctx: NarratorContext): Promise<string>;
}

export interface Narrator {
  /** "deterministic" | "llm" - for status display and tests. */
  readonly kind: string;
  /** Answer a question read-only, grounded in tool results. */
  answer(query: string, ctx: NarratorContext): Promise<string>;
}
