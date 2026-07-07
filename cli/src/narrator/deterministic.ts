/**
 * DeterministicNarrator - keyword routing over the read-only console tools.
 *
 * No model, always available. Handles card selection, the a/r/w hints, and the
 * kpi / hil / audit intents by calling the same tools the LLM narrator uses.
 * Free-form natural language (including Korean) falls back to a live-state
 * summary plus a pointer to configure the LLM narrator.
 */

import type { Narrator, NarratorContext } from "./types.js";
import { runTool } from "./tools.js";

export class DeterministicNarrator implements Narrator {
  readonly kind = "deterministic";

  async answer(query: string, ctx: NarratorContext): Promise<string> {
    const t = query.toLowerCase().trim();
    const num = Number(t);
    try {
      // Card selection (sample mode carries rich HIL detail).
      const p = ctx.payload;
      if (
        p &&
        p.hil.length > 0 &&
        Number.isInteger(num) &&
        num >= 1 &&
        num <= p.hil.length
      ) {
        const item = p.hil[num - 1]!;
        return (
          `${item.title} (${item.actionType}). ${item.why} ` +
          `Confidence: ${item.basis} (${item.basisTech}). Safety: ${item.safety} ` +
          `Approving opens a pull request - ${item.who}`
        );
      }
      if (t === "a" || t === "approve") {
        return "(read-only) Approving opens a pull request; nothing changes until it is merged, and you cannot approve your own request.";
      }
      if (t === "r" || t === "decline") {
        return "(read-only) Declined and logged. Nothing changes.";
      }
      if (t === "w" || t === "explain") {
        return "Pick a card number to see the reasoning behind it.";
      }

      if (/(kpi|status|metric|dashboard|health|summary|how many)/.test(t)) {
        return await runTool("get_kpi", {}, ctx);
      }
      if (/(hil|queue|decision|approv|pending|awaiting)/.test(t)) {
        return await runTool("get_hil_queue", {}, ctx);
      }
      if (/(audit|log|history|recent|activity|happened)/.test(t)) {
        return await runTool("get_recent_audit", { limit: 5 }, ctx);
      }

      // Sample-only narrative intents (nice-to-have colour in the mock).
      if (!ctx.apiUrl && p) {
        if (t.includes("payment") || t.includes("restart")) {
          return "payments-api restarted after two out-of-memory events in the last hour (incident #1204). There is a pending proposal to raise its memory 512 MB -> 1 GB (card 1), 91% similar to incident #0847.";
        }
        if (t.includes("spend") || t.includes("cost") || t.includes("budget")) {
          return "Spending is flat versus last week in this synthetic dataset. One cost rule ('idle disk cleanup') is finishing a 30-day trial with 41/41 correct (card 3).";
        }
        if (t.includes("rule") || t.includes("trial") || t.includes("shadow")) {
          return `${p.shadowCandidates} rules are in trial (shadow mode) - they watch and log but do not act yet. One is ready to promote to live (card 3).`;
        }
      }

      const kpi = await runTool("get_kpi", {}, ctx);
      return (
        `I match keywords like kpi / hil queue / recent audit, or a card number. ` +
        `Right now: ${kpi}. Free-form natural language (including Korean) is answered ` +
        `by the LLM narrator - set FDAI_NARRATOR_* to enable it.`
      );
    } catch (err) {
      return `(error) ${(err as Error).message}`;
    }
  }
}
