/**
 * Console panel registry - the frontend half of the fork extension seam.
 *
 * The upstream console ships a deliberately minimal UI grouped by
 * operator intent (Now / History / Knowledge / Safety / Overview). A
 * fork that wants a vertical-specific surface (a FinOps cost dashboard,
 * a drift board, a DR-drill history) does NOT edit `app.tsx` or
 * `shell.tsx`. It appends a `ConsolePanel` to `EXTRA_PANELS` (or injects
 * one at build time) and, on the API side, registers a matching
 * `ReadPanel` (`src/fdai/delivery/read_api/panels.py`).
 *
 * Every panel is read-only. A panel renders data fetched through the
 * GET-only `ReadApiClient`; there is no mutating back-channel. Approvals
 * and actions still flow through ChatOps / remediation PRs, never a
 * console button (app-shape.instructions.md § Operator console).
 *
 * Groups reflect operator personas, not internal architecture layers:
 *  - `now`       - Live cockpit, waiting approvals, active attention
 *  - `history`   - Audit and post-hoc reconstruction
 *  - `knowledge` - What the system knows (ontology, agents, rules)
 *  - `safety`    - Promotion / blast-radius / what-if decisions
 *  - `overview`  - KPIs and cross-cutting summaries
 */

import type { ComponentType } from "preact";
import type { ReadApiClient } from "./api";
import { AuditRoute } from "./routes/audit";
import { BlastRadiusRoute } from "./routes/blast-radius";
import { DashboardRoute } from "./routes/dashboard";
import { HilQueueRoute } from "./routes/hil-queue";
import { LiveRoute } from "./routes/live";
import { OntologyRoute } from "./routes/ontology";
import { PantheonRoute } from "./routes/pantheon";
import { PromotionGatesRoute } from "./routes/promotion-gates";
import { RuleTraceRoute } from "./routes/rule-trace";

/** Props every panel component receives. Read-only client only. */
export interface PanelProps {
  readonly client: ReadApiClient;
}

/** The 5 operator-intent groups the upstream console ships. Fork
 * panels MUST pick one; the LeftRail groups by this key. Adding a new
 * group is a design decision (docs update required); do not extend
 * this union in a fork without upstreaming the change. */
export type PanelGroup = "now" | "history" | "knowledge" | "safety" | "overview";

export interface PanelGroupMeta {
  readonly id: PanelGroup;
  /** Display label on the rail, e.g. "Now". */
  readonly label: string;
  /** Short helper shown in the hover popover heading. */
  readonly hint: string;
}

export const PANEL_GROUPS: readonly PanelGroupMeta[] = [
  { id: "now", label: "Now", hint: "Real-time control-plane state" },
  { id: "history", label: "History", hint: "Audit and post-hoc traces" },
  { id: "knowledge", label: "Knowledge", hint: "What the system knows" },
  { id: "safety", label: "Safety", hint: "Promotion and blast-radius decisions" },
  { id: "overview", label: "Overview", hint: "KPIs and rolled-up summaries" },
];

export interface ConsolePanel {
  /** Hash-route segment and stable id, e.g. `"dashboard"`, `"finops"`.
   * IDs are permanent - existing links and audit references depend on
   * them. Renaming an id is a breaking change; add an alias route
   * instead. */
  readonly id: string;
  /** Operator-facing label shown in the rail popover and page header.
   * May be renamed freely. */
  readonly label: string;
  /** Optional one-line description shown in the hover popover as a
   * subtitle. */
  readonly subtitle?: string;
  /** Which of the 5 operator-intent groups this panel belongs to. */
  readonly group: PanelGroup;
  /** The view component, rendered with {@link PanelProps}. */
  readonly component: ComponentType<PanelProps>;
}

const DASHBOARD_PANEL: ConsolePanel = {
  id: "dashboard",
  label: "Dashboard",
  subtitle: "Rolled-up KPIs sourced from the audit log",
  group: "overview",
  component: DashboardRoute,
};

/** The panels the upstream console always ships, grouped by intent. */
export const CORE_PANELS: readonly ConsolePanel[] = [
  // ── Now ─────────────────────────────────────────────────────────────
  {
    id: "live",
    label: "Live",
    subtitle: "Real-time pipeline activity",
    group: "now",
    component: LiveRoute,
  },
  {
    id: "hil-queue",
    label: "Approvals",
    subtitle: "High-risk actions waiting for a human approver (HIL)",
    group: "now",
    component: HilQueueRoute,
  },
  // ── History ─────────────────────────────────────────────────────────
  {
    id: "audit",
    label: "Audit log",
    subtitle: "Append-only record of every terminal decision",
    group: "history",
    component: AuditRoute,
  },
  {
    id: "trace",
    label: "Trace",
    subtitle: "Reconstruct one correlation id end-to-end",
    group: "history",
    component: RuleTraceRoute,
  },
  // ── Knowledge ───────────────────────────────────────────────────────
  {
    id: "ontology",
    label: "Ontology",
    subtitle: "Resource + link graph (classDiagram)",
    group: "knowledge",
    component: OntologyRoute,
  },
  {
    id: "pantheon",
    label: "Agents",
    subtitle: "15 named autonomous agents (Pantheon)",
    group: "knowledge",
    component: PantheonRoute,
  },
  // ── Safety ──────────────────────────────────────────────────────────
  {
    id: "blast-radius",
    label: "Blast radius",
    subtitle: "Simulate reachable subgraph before a change",
    group: "safety",
    component: BlastRadiusRoute,
  },
  {
    id: "promotion-gates",
    label: "Promotion gates",
    subtitle: "Per-ActionType readiness for shadow → enforce",
    group: "safety",
    component: PromotionGatesRoute,
  },
  // ── Overview ────────────────────────────────────────────────────────
  DASHBOARD_PANEL,
];

/**
 * Fork extension point. Empty upstream so the UI stays minimal. A fork
 * appends its panels here - see `routes/example-finops.tsx` for a
 * copy-paste-ready reference (kept out of this list on purpose):
 *
 * ```ts
 * import { ExampleFinOpsPanel } from "./routes/example-finops";
 * export const EXTRA_PANELS: readonly ConsolePanel[] = [
 *   { id: "finops", label: "Cost", group: "overview", component: ExampleFinOpsPanel },
 * ];
 * ```
 */
export const EXTRA_PANELS: readonly ConsolePanel[] = [];

/** All panels the running console exposes (core first, then fork panels). */
export function resolvePanels(): readonly ConsolePanel[] {
  return [...CORE_PANELS, ...EXTRA_PANELS];
}

/** Panels filtered to a single group, in registration order. */
export function panelsInGroup(group: PanelGroup): readonly ConsolePanel[] {
  return resolvePanels().filter((p) => p.group === group);
}

/** The default panel id (first "now" panel = Live). */
export const DEFAULT_PANEL_ID = "live";

/** Resolve the panel for a hash-route segment, or the default panel. */
export function panelForId(id: string): ConsolePanel {
  return resolvePanels().find((p) => p.id === id) ?? DASHBOARD_PANEL;
}
