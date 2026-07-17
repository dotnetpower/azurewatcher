import type { AutonomyPayload, DashboardKpi } from "../types";
import { getLocale } from "../i18n";

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

export function auditSampleParams(
  kpi: DashboardKpi,
): Readonly<Record<string, number>> {
  const sample = kpi.audit_sample;
  return sample !== null && sample.from_seq !== null && sample.through_seq !== null
    ? { from_seq: sample.from_seq, through_seq: sample.through_seq }
    : {};
}

export function formatShare(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function formatUsd(value: number): string {
  return value.toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export function overviewCostActions(
  finops: { readonly total_actions: number } | null,
): number | "n/a" {
  return finops?.total_actions ?? "n/a";
}

export function overviewT0Share(byTier: Readonly<Record<string, number>>): string {
  const total = Object.values(byTier).reduce((sum, count) => sum + count, 0);
  if (!Object.hasOwn(byTier, "t0") || total <= 0) return "unavailable";
  return `${Math.round((byTier["t0"]! / total) * 100)}%`;
}

export function overviewHealth(
  kpi: DashboardKpi,
  policyEscapes: number | null,
  autonomy: Pick<AutonomyPayload, "guards" | "synthetic"> | null,
): OverviewHealth {
  const measuredGuards = autonomy !== null && !autonomy.synthetic;
  const knownFailure =
    kpi.shadow_share < 0.95 ||
    kpi.hil_pending > 0 ||
    (policyEscapes !== null && policyEscapes > 0) ||
    (measuredGuards && autonomy.guards.some((guard) => !guard.ok));
  if (knownFailure) return "attention";
  if (policyEscapes === null || autonomy === null || autonomy.synthetic) return "unknown";
  return "healthy";
}

export function overviewAttentionCount(
  kpi: DashboardKpi,
  policyEscapes: number | null,
  autonomy: Pick<AutonomyPayload, "guards" | "synthetic"> | null,
): number {
  const failedGuards = autonomy !== null && !autonomy.synthetic
    ? autonomy.guards.filter((guard) => !guard.ok).length
    : 0;
  return kpi.hil_pending + (policyEscapes ?? 0) + failedGuards;
}
