/**
 * Read-only console tools shared by both narrators.
 *
 * Each tool works against the live read API when `ctx.apiUrl` is set, and
 * against the synthetic sample payload otherwise - so the narrator answers from
 * real data in both modes. Tools are strictly read-only; none can mutate state.
 */

import {
  fetchAuditItems,
  fetchHilItems,
  fetchKpi,
} from "../data/read-api.js";
import type { ConsoleTool, NarratorContext } from "./types.js";

const getKpi: ConsoleTool = {
  name: "get_kpi",
  description:
    "Current KPI snapshot: total events, shadow/enforce split, how many are awaiting a human decision, trust-tier shares, and the last recorded time.",
  parameters: { type: "object", properties: {}, additionalProperties: false },
  async run(_args, ctx: NarratorContext): Promise<string> {
    if (ctx.apiUrl) {
      const kpi = await fetchKpi(ctx.apiUrl);
      const tiers = Object.entries(kpi.by_tier)
        .map(([t, n]) => `${t.toUpperCase()}=${n}`)
        .join(" ");
      return (
        `events=${kpi.event_count} shadow=${Math.round(kpi.shadow_share * 100)}% ` +
        `enforce=${Math.round(kpi.enforce_share * 100)}% awaiting_decision=${kpi.hil_pending} ` +
        `tiers[${tiers}] last_recorded=${kpi.last_recorded_at ?? "none"}`
      );
    }
    const p = ctx.payload;
    if (!p) return "no data available";
    const tiers = p.tiers.map((t) => `${t.tier}=${t.pct}%`).join(" ");
    return (
      `events=${p.events} auto_resolved=${p.autoResolved} rolled_back=${p.rollbacks} ` +
      `paused_rules=${p.overridesActive} in_trial=${p.shadowCandidates} tiers[${tiers}]`
    );
  },
};

const getHilQueue: ConsoleTool = {
  name: "get_hil_queue",
  description:
    "The human-in-the-loop (HIL) queue: items the risk gate escalated to a human for approval. Approval is PR-native and read-only from here.",
  parameters: { type: "object", properties: {}, additionalProperties: false },
  async run(_args, ctx: NarratorContext): Promise<string> {
    if (ctx.apiUrl) {
      const items = await fetchHilItems(ctx.apiUrl);
      if (items.length === 0) return "hil_queue: empty";
      return items
        .map((h, i) => `#${i + 1} ${h.action_kind} reason="${h.reason}" ref=${h.idempotency_key}`)
        .join(" | ");
    }
    const p = ctx.payload;
    if (!p || p.hil.length === 0) return "hil_queue: empty";
    return p.hil
      .map((h, i) => `#${i + 1} ${h.title} (${h.actionType}) risk=${h.risk} reason="${h.why}"`)
      .join(" | ");
  },
};

const getRecentAudit: ConsoleTool = {
  name: "get_recent_audit",
  description:
    "The most recent audit-log entries (append-only). Each entry has a sequence number, action kind, mode (shadow/enforce), and actor.",
  parameters: {
    type: "object",
    properties: {
      limit: { type: "integer", minimum: 1, maximum: 20 },
    },
    additionalProperties: false,
  },
  async run(args, ctx: NarratorContext): Promise<string> {
    const limit = typeof args.limit === "number" ? args.limit : 5;
    if (ctx.apiUrl) {
      const items = await fetchAuditItems(ctx.apiUrl, limit);
      if (items.length === 0) return "audit: empty";
      return items
        .map((a) => `#${a.seq} ${a.action_kind}/${a.mode} by ${a.actor}`)
        .join(" | ");
    }
    return "audit: not available in sample mode (run with --source=api for the live audit log)";
  },
};

export const CONSOLE_TOOLS: readonly ConsoleTool[] = [
  getKpi,
  getHilQueue,
  getRecentAudit,
];

export function toolByName(name: string): ConsoleTool | undefined {
  return CONSOLE_TOOLS.find((t) => t.name === name);
}

/** Run a tool by name, throwing on an unknown tool. */
export async function runTool(
  name: string,
  args: Record<string, unknown>,
  ctx: NarratorContext,
): Promise<string> {
  const tool = toolByName(name);
  if (!tool) throw new Error(`unknown console-tool: ${name}`);
  return tool.run(args, ctx);
}
