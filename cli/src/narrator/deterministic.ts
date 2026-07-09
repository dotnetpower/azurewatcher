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
import { t as translate } from "../i18n/index.js";

export class DeterministicNarrator implements Narrator {
  readonly kind = "deterministic";

  async answer(query: string, ctx: NarratorContext): Promise<string> {
    const t = query.toLowerCase().trim();
    const num = Number(t);
    const locale = ctx.locale ?? "en";
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
        return translate("narrator.cardDetail", locale, {
          title: item.title,
          actionType: item.actionType,
          why: item.why,
          basis: item.basis,
          basisTech: item.basisTech,
          safety: item.safety,
          who: item.who,
        });
      }
      if (t === "a" || t === "approve") {
        return translate("narrator.approveHint", locale);
      }
      if (t === "r" || t === "decline") {
        return translate("narrator.declineHint", locale);
      }
      if (t === "w" || t === "explain") {
        return translate("narrator.explainHint", locale);
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
          return translate("narrator.samplePayments", locale);
        }
        if (t.includes("spend") || t.includes("cost") || t.includes("budget")) {
          return translate("narrator.sampleSpend", locale);
        }
        if (t.includes("rule") || t.includes("trial") || t.includes("shadow")) {
          return translate("narrator.sampleRules", locale, {
            shadow: p.shadowCandidates,
          });
        }
      }

      const kpi = await runTool("get_kpi", {}, ctx);
      return translate("narrator.fallback", locale, { kpi });
    } catch (err) {
      return translate("narrator.error", locale, {
        message: (err as Error).message,
      });
    }
  }
}
