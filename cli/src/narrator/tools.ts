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
import { queryInventory } from "./inventory.js";
import { getMetrics } from "./metrics.js";
import { getActivityLog } from "./activity.js";
import { getCost } from "./cost.js";
import { getQuota } from "./quota.js";
import { toolSpec } from "./tool-store.js";
import type { ConsoleTool, NarratorContext } from "./types.js";

const getKpi: ConsoleTool = {
  name: "get_kpi",
  ...toolSpec("get_kpi"),
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
  ...toolSpec("get_hil_queue"),
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
  ...toolSpec("get_recent_audit"),
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

/** Screen-control tool (CLI cockpit only). Changes what is displayed - the
 * view/component - never a cloud resource. No-op when no screen is attached. */
const setView: ConsoleTool = {
  name: "set_view",
  description:
    "Change what the operator SEES on screen (CLI cockpit only, read-only DISPLAY control). " +
    "Use ONLY when the operator asks to change the view or focus the display - never to act on, " +
    "fix, or remediate a resource. " +
    "mode: 'overview' (calm dashboard: routing mix, throughput, outcomes, top resources), " +
    "'stream' (live scrolling op feed), or 'focus' (feed filtered to one resource type). " +
    "Set focus to a resource-type substring like 'network', 'compute', 'disk', 'sql', " +
    "'object-storage', 'kubernetes', 'cache', 'secret'. Set paused true to freeze the feed.",
  parameters: {
    type: "object",
    properties: {
      mode: { type: "string", enum: ["stream", "overview", "focus"] },
      focus: { type: "string" },
      paused: { type: "boolean" },
    },
    additionalProperties: false,
  },
  async run(args, ctx: NarratorContext): Promise<string> {
    if (!ctx.screen) return "set_view: no screen attached (not the CLI cockpit)";
    const patch: { mode?: "stream" | "overview" | "focus"; focus?: string; paused?: boolean } = {};
    if (args.mode === "stream" || args.mode === "overview" || args.mode === "focus") {
      patch.mode = args.mode;
    }
    if (typeof args.focus === "string") patch.focus = args.focus;
    if (typeof args.paused === "boolean") patch.paused = args.paused;
    return ctx.screen.setView(patch);
  },
};

/** Live-state snapshot from the CLI cockpit's own counters: events handled, the
 * trust-tier mix, outcomes, and the resource-TYPE breakdown seen on the stream.
 * Answers "what resources / types have you handled" from what is on screen. */
const getLiveOverview: ConsoleTool = {
  name: "get_live_overview",
  ...toolSpec("get_live_overview"),
  async run(_args, ctx: NarratorContext): Promise<string> {
    return ctx.live?.overview() ?? "live overview: not available (not the CLI cockpit)";
  },
};

/** Real Azure inventory via Azure Resource Graph (read-only). Answers questions
 * the event stream cannot - resource-group lists, running/stopped VMs, actual
 * resources in the subscription - by running a read-only Kusto query. */
const queryInventoryTool: ConsoleTool = {
  name: "query_inventory",
  ...toolSpec("query_inventory"),
  async run(args): Promise<string> {
    const kql = typeof args.kql === "string" ? args.kql.trim() : "";
    if (!kql) return "query_inventory: provide a 'kql' query string";
    try {
      return await queryInventory(kql);
    } catch (err) {
      return `inventory unavailable: ${(err as Error).message}`;
    }
  },
};

/** Real Azure Monitor metrics for a resource (read-only). Diagnoses performance
 * symptoms with real numbers. */
const getMetricsTool: ConsoleTool = {
  name: "get_metrics",
  ...toolSpec("get_metrics"),
  async run(args): Promise<string> {
    const resourceId = typeof args.resourceId === "string" ? args.resourceId : "";
    const metrics = typeof args.metrics === "string" ? args.metrics : "";
    const hours = typeof args.hours === "number" ? args.hours : 1;
    try {
      return await getMetrics(resourceId, metrics, hours);
    } catch (err) {
      return `metrics unavailable: ${(err as Error).message}`;
    }
  },
};

/** Read-only Azure Activity Log: recent management operations. Diagnoses "why
 * did the deploy fail", "who did something", "recent errors". */
const getActivityLogTool: ConsoleTool = {
  name: "get_activity_log",
  ...toolSpec("get_activity_log"),
  async run(args): Promise<string> {
    const hours = typeof args.hours === "number" ? args.hours : 24;
    const filter = typeof args.filter === "string" ? args.filter : "";
    try {
      return await getActivityLog(hours, filter);
    } catch (err) {
      return `activity log unavailable: ${(err as Error).message}`;
    }
  },
};

/** Read-only Azure cost via Cost Management. Answers spend questions - the Cost
 * Governance vertical's live data. */
const getCostTool: ConsoleTool = {
  name: "get_cost",
  ...toolSpec("get_cost"),
  async run(args): Promise<string> {
    const timeframe = typeof args.timeframe === "string" ? args.timeframe : "MonthToDate";
    const groupBy = typeof args.groupBy === "string" ? args.groupBy : "ResourceGroupName";
    try {
      return await getCost(timeframe, groupBy);
    } catch (err) {
      return `cost unavailable: ${(err as Error).message}`;
    }
  },
};

/** Read-only Azure compute quota / capacity headroom via the Compute usages
 * API. Answers 'is there quota left', 'vCPU headroom', 'near a limit'. */
const getQuotaTool: ConsoleTool = {
  name: "get_quota",
  ...toolSpec("get_quota"),
  async run(args): Promise<string> {
    const location = typeof args.location === "string" ? args.location : "";
    try {
      return await getQuota(location);
    } catch (err) {
      return `quota unavailable: ${(err as Error).message}`;
    }
  },
};

/** Grounded description of the control plane's guaranteed behaviors. Sourced
 * from the architecture contract so the narrator answers "how does it work / is
 * it safe / can you roll back / what can you do / who executes" from documented
 * guarantees, not invention. */
const GUARANTEES = [
  "Trust routing (3 tiers): every event is routed by a computed confidence to the lowest sufficient tier - T0 deterministic rules/policy (the large majority of events), T1 lightweight similarity to past resolved incidents, or T2 frontier-LLM reasoning for novel or ambiguous cases only. T2 output must pass a quality gate (two or more distinct models cross-checked, a deterministic verifier that re-validates the action against policy-as-code and a what-if dry-run, and rule-citation grounding) before it is eligible to execute. On model disagreement the judgment escalates to HIL and is never auto-resolved. The model generates; deterministic verification grants execution, never the model alone.",
  "Detection (anomaly detection, predictive/forecast, and root-cause analysis) feeds the same control loop: it is deterministic-first, ships in shadow mode, and never auto-acts on its own - a prediction, anomaly, or config-drift finding raises a finding that the risk gate governs, then is delivered as a reviewed pull request. Change Safety (drift remediation) works the same way: detected, judged, and delivered as a PR, never a silent change.",
  "Risk-gated autonomy: low-risk actions auto-execute; high-risk actions require human-in-the-loop (HIL) approval. Approval and execution are always distinct principals - no self-approval.",
  "Shadow-first: new capabilities ship in shadow mode (judge and log only, no execution) and are promoted to enforce explicitly, per action, only after measured accuracy with zero policy-violation escapes. A regression demotes back to shadow automatically.",
  "Four safety invariants on every autonomous action: a stop-condition, a tested rollback path, a blast-radius limit (scope/batch/rate cap), and an append-only audit entry. Each action also runs a what-if/dry-run and holds a per-resource lock before applying, and is idempotent so retries never double-apply. So yes - every change is reversible by design; missing any invariant means the action does not ship.",
  "PR-native delivery (GitOps): actions are delivered as remediation pull requests, so review, audit, and rollback come for free. The operator console is strictly read-only - it never executes; approvals happen via pull request or ChatOps.",
  "Rule catalog: a versioned, CSP-neutral catalog continuously collected from sources (Azure WAF/AKS Baseline/MCSB/Policy/Advisor, CIS Benchmarks, OPA/Gatekeeper, IaC scanners such as Checkov/tfsec/KICS/Trivy, kube-bench). Operators may override a rule within a bounded scope (disable, severity-downgrade, or parameter-relaxation) via scoped policy-as-code; overrides require a distinct approver, are audited, never edit rule text, and never disable detection (shadow keeps recording).",
  "Verticals (initial): Resilience (disaster recovery + chaos/resilience testing), Change Safety (safe change + drift remediation), and Cost Governance (FinOps).",
  "Agent roles (the loop is owned by named agents): Forseti judges and issues the verdict (auto/hil/deny) after the quality gate; Var is the HIL approver; Thor is the sole privileged executor and never judges; Vidar handles rollback and DR failover; Saga writes the append-only audit log. Judge, approver, and executor are always distinct principals.",
].join("\n");

const describeGuarantees: ConsoleTool = {
  name: "describe_guarantees",
  ...toolSpec("describe_guarantees"),
  async run(): Promise<string> {
    return GUARANTEES;
  },
};

/** Tools available to the CLI cockpit (adds screen control + inventory to the
 * read tools). */
export const CLI_CONSOLE_TOOLS: readonly ConsoleTool[] = [
  ...CONSOLE_TOOLS,
  setView,
  getLiveOverview,
  queryInventoryTool,
  getMetricsTool,
  getActivityLogTool,
  getCostTool,
  getQuotaTool,
  describeGuarantees,
];

export function toolByName(name: string): ConsoleTool | undefined {
  return CLI_CONSOLE_TOOLS.find((t) => t.name === name);
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
