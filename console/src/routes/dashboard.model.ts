import type { AutonomyPayload, DashboardKpi } from "../types";

export type OverviewHealth = "healthy" | "attention" | "unknown";

export interface GateRow {
  readonly policy_escapes: number;
  readonly ready: boolean;
}

export interface GatesSummary {
  readonly rows: readonly GateRow[];
  readonly ready_count: number;
  readonly blocked_count: number;
}

export function formatShare(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function formatUsd(value: number): string {
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export function overviewHealth(
  kpi: DashboardKpi,
  policyEscapes: number | null,
  autonomy: Pick<AutonomyPayload, "guards"> | null,
): OverviewHealth {
  const knownFailure =
    kpi.shadow_share < 0.95 ||
    kpi.hil_pending > 0 ||
    (policyEscapes !== null && policyEscapes > 0) ||
    (autonomy !== null && autonomy.guards.some((guard) => !guard.ok));
  if (knownFailure) return "attention";
  if (policyEscapes === null || autonomy === null) return "unknown";
  return "healthy";
}

export function overviewAttentionCount(
  kpi: DashboardKpi,
  policyEscapes: number | null,
  autonomy: Pick<AutonomyPayload, "guards"> | null,
): number {
  const failedGuards = autonomy?.guards.filter((guard) => !guard.ok).length ?? 0;
  return kpi.hil_pending + (policyEscapes ?? 0) + failedGuards;
}