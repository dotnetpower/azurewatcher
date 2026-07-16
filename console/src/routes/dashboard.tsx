import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { ReadApiError } from "../api";
import type {
  AutonomyPayload,
  DashboardKpi,
  FinOpsPayload,
} from "../types";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { routeHref } from "../router";
import {
  formatShare,
  formatUsd,
  overviewAttentionCount,
  overviewHealth,
  type GatesSummary,
} from "./dashboard.model";
import {
  AgentOrganization,
  ExecutiveStatus,
  LeadingIndicators,
  MeasurementUnavailable,
  SuccessMetrics,
} from "./dashboard.executive";
import { ExecutiveDecisionGrid } from "./dashboard.assurance";
import { LivingRules, TierBands, VerticalCards } from "./dashboard.signals";

interface Props {
  readonly client: ReadApiClient;
}

/**
 * Aggregate promotion-gate signal behind the release guard row. `null`
 * when the gate route is not wired on this deployment (404/501). A
 * `policy_escapes` sum > 0 blocks release per goals-and-metrics (escapes
 * MUST be exactly 0), so it also fails the health axis.
 */
interface OverviewData {
  readonly kpi: DashboardKpi;
  readonly finops: FinOpsPayload | null;
  readonly gates: GatesSummary | null;
  readonly autonomy: AutonomyPayload | null;
}

export function DashboardRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<OverviewData>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // `/kpi` is the required backbone; `/finops` is a fork opt-in panel,
        // so a 404 degrades to a null cost axis instead of failing the page.
        const kpi = await client.dashboardMetrics();
        let finops: FinOpsPayload | null = null;
        try {
          finops = await client.finops();
        } catch (err) {
          if (!(err instanceof ReadApiError && err.status === 404)) throw err;
        }
        // Promotion-gate summary powers the release guard (policy escapes
        // MUST be 0). Opt-in like finops: 404/501 degrades to no guard row.
        let gates: GatesSummary | null = null;
        try {
          gates = await client.panel<GatesSummary>("/kpi/promotion-gates");
        } catch (err) {
          if (!(err instanceof ReadApiError && (err.status === 404 || err.status === 501)))
            throw err;
        }
        // Autonomy measurement summary (success vs baseline, guards,
        // verticals, tier, trend). Opt-in: 404/501 => audit-only fallback.
        let autonomy: AutonomyPayload | null = null;
        try {
          autonomy = await client.autonomy();
        } catch (err) {
          if (!(err instanceof ReadApiError && (err.status === 404 || err.status === 501 || err.status === 502)))
            throw err;
        }
        if (!cancelled) setState({ status: "ready", data: { kpi, finops, gates, autonomy } });
      } catch (err) {
        if (!cancelled) {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client]);

  return (
    <div class="stack overview-page">
      <PageHeader title={t("route.dashboard")} subtitle={<>{t("overview.subtitle")}</>} />
      <AsyncBoundary state={state} resourceLabel="overview">
        {(data) => <OverviewBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

function OverviewBody({ data }: { readonly data: OverviewData }) {
  const { kpi, finops, gates, autonomy } = data;

  const tierTotal = Object.values(kpi.by_tier).reduce((a, b) => a + b, 0);
  const t0Share = tierTotal > 0 ? Math.round(((kpi.by_tier.t0 ?? 0) / tierTotal) * 100) : 0;
  const policyEscapes = gates ? gates.rows.reduce((sum, r) => sum + r.policy_escapes, 0) : null;
  const readyCount = gates ? gates.ready_count : null;
  const gateTotal = gates ? gates.rows.length : null;
  // A policy escape blocks release (goals-and-metrics: escapes MUST be 0),
  // so it fails the health axis just like a pending human approval does.
  const health = overviewHealth(kpi, policyEscapes, autonomy);
  const attentionCount = overviewAttentionCount(kpi, policyEscapes, autonomy);
  const savings = finops ? finops.estimated_monthly_savings : null;

  usePublishViewContext(
    () => {
      // The Overview renders an autonomy hero, success-metrics-vs-baseline,
      // per-vertical cards, and guard bands from the /kpi/autonomy panel.
      // Publish that surface (not just the audit KPIs) so the deck can answer
      // "what is the auto-resolution rate / savings per vertical / are the
      // guards ok?". `synthetic` is surfaced so the deck can flag dev values.
      const autonomyFacts: {
        key: string;
        value: string | number | boolean | null;
        group?: string;
      }[] = autonomy
        ? [
            { key: "measurement_synthetic", value: autonomy.synthetic, group: "autonomy" },
            { key: "auto_resolution_rate", value: autonomy.success.auto_resolution_rate.value, group: "autonomy" },
            { key: "auto_resolution_baseline", value: autonomy.success.auto_resolution_rate.baseline, group: "autonomy" },
            { key: "human_touchpoints_per_100", value: autonomy.success.human_touchpoints_per_100.value, group: "autonomy" },
            { key: "mttr_seconds", value: autonomy.success.mttr_seconds.value, group: "autonomy" },
            { key: "change_lead_time_seconds", value: autonomy.success.change_lead_time_seconds.value, group: "autonomy" },
          ]
        : [];
      const autonomyRecords: Record<string, readonly Record<string, unknown>[]> = autonomy
        ? {
            success_metrics: (
              [
                ["auto_resolution_rate", autonomy.success.auto_resolution_rate],
                ["human_touchpoints_per_100", autonomy.success.human_touchpoints_per_100],
                ["mttr_seconds", autonomy.success.mttr_seconds],
                ["change_lead_time_seconds", autonomy.success.change_lead_time_seconds],
              ] as const
            ).map(([metric, m]) => ({
              metric,
              value: m.value,
              baseline: m.baseline,
              better_when: m.direction,
            })),
            verticals: autonomy.verticals.map((v) => ({
              vertical: v.key,
              events: v.events,
              auto_resolved: v.auto_resolved,
              open_risks: v.open_risks,
              monthly_savings: v.monthly_savings,
            })),
            guards: autonomy.guards.map((g) => ({
              key: g.key,
              value: g.value,
              baseline: g.baseline,
              threshold: g.threshold,
              ok: g.ok,
            })),
          }
        : {};
      return {
        routeId: "dashboard",
        routeLabel: t("route.dashboard"),
        purpose:
          "The at-a-glance health of the control plane: event volume, the " +
          "shadow/enforce split, T0 deterministic share, approval backlog, and " +
          "estimated monthly savings across the verticals. Read-only summary.",
        glossary: composeGlossary([
          TERMS.tier,
          TERMS.shadowMode,
          TERMS.mode,
          TERMS.hil,
          TERMS.gateDecision,
        ]),
        headline:
          `health ${health} - ` +
          `${kpi.hil_pending} approvals pending - ` +
          (savings !== null ? `${formatUsd(savings)}/mo saved` : "cost n/a"),
        capturedAt: new Date().toISOString(),
        facts: [
          { key: "health", value: health, group: "overview" },
          { key: "event_count", value: kpi.event_count, group: "overview" },
          { key: "shadow_share", value: formatShare(kpi.shadow_share), group: "overview" },
          { key: "t0_share", value: `${t0Share}%`, group: "overview" },
          { key: "hil_pending", value: kpi.hil_pending, group: "overview" },
          {
            key: "measurement_state",
            value: autonomy === null ? "unavailable" : autonomy.synthetic ? "simulated" : "measured",
            group: "autonomy",
          },
          {
            key: "measurement_source",
            value: autonomy?.source.name ?? "not connected",
            group: "autonomy",
          },
          {
            key: "monthly_savings",
            value: savings !== null ? formatUsd(savings) : "n/a",
            group: "cost",
          },
          { key: "cost_actions", value: finops ? finops.total_actions : 0, group: "cost" },
          { key: "policy_escapes", value: policyEscapes ?? "n/a", group: "guards" },
          {
            key: "promotion_ready",
            value: gateTotal !== null ? `${readyCount}/${gateTotal}` : "n/a",
            group: "guards",
          },
          ...autonomyFacts,
        ],
        records: {
          by_action_kind: Object.entries(kpi.by_action_kind)
            .sort(([, a], [, b]) => b - a)
            .map(([key, count]) => ({ key, count })),
          by_outcome: Object.entries(kpi.by_outcome)
            .sort(([, a], [, b]) => b - a)
            .map(([key, count]) => ({ key, count })),
          ...autonomyRecords,
        },
      };
    },
    [kpi, finops, gates, autonomy, health, savings, t0Share],
  );

  return (
    <div class="stack overview-report">
      <ExecutiveStatus
        health={health}
        kpi={kpi}
        autonomy={autonomy}
        attentionCount={attentionCount}
        policyEscapes={policyEscapes}
      />

      <OverviewSection
        number="1"
        title={t("overview.section.outcomes")}
        description={t("overview.section.outcomesHint")}
      >
        {autonomy ? (
          <div class="stack">
          <SuccessMetrics
            success={autonomy.success}
            synthetic={autonomy.synthetic}
            windowDays={autonomy.window_days}
            sourceName={autonomy.source.name}
          />
            <LeadingIndicators leading={autonomy.leading} sourceName={autonomy.source.name} />
          </div>
        ) : <MeasurementUnavailable />}
      </OverviewSection>

      <OverviewSection
        number="2"
        title={t("overview.section.assurance")}
        description={t("overview.section.assuranceHint")}
      >
        <ExecutiveDecisionGrid
          health={health}
          kpi={kpi}
          gates={gates}
          autonomy={autonomy}
          attentionCount={attentionCount}
          policyEscapes={policyEscapes}
        />
      </OverviewSection>

      <OverviewSection
        number="3"
        title={t("overview.section.organization")}
        description={t("overview.section.organizationHint")}
      >
        {autonomy ? (
          <AgentOrganization
            autonomy={autonomy}
            hilPending={kpi.hil_pending}
          />
        ) : <MeasurementUnavailable />}
      </OverviewSection>

      <OverviewSection
        number="4"
        title={t("overview.section.verticals")}
        description={t("overview.section.verticalsHint")}
      >
        {autonomy ? (
          <VerticalCards verticals={autonomy.verticals} />
        ) : <MeasurementUnavailable />}
      </OverviewSection>

      {autonomy ? (
        <section class="overview-operating-signals" aria-label={t("overview.operations.label")}>
          <TierBands tier={autonomy.tier} />
          <LivingRules rules={autonomy.rules} />
        </section>
      ) : (
        <section class="overview-operating-signals" aria-label={t("overview.operations.label")}>
          <MeasurementUnavailable />
        </section>
      )}

      <details class="advanced-details overview-details">
        <summary>
          <h3 class="section-title">{t("overview.detail")}</h3>
          <span class="muted">{t("overview.detailHint")}</span>
        </summary>
        <div class="stack overview-details-body">
          <KpiGrid>
            <a class="overview-kpi-link" href={routeHref("audit")}><KpiCard label="Events (audit)" value={kpi.event_count} hint="terminal audit entries" /></a>
            <a class="overview-kpi-link" href={routeHref("audit", { params: { mode: "shadow" } })}><KpiCard label="Shadow share" value={formatShare(kpi.shadow_share)} hint="judge-only, no mutation" tone={kpi.shadow_share > 0.95 ? "positive" : "default"} /></a>
            <a class="overview-kpi-link" href={routeHref("audit", { params: { mode: "enforce" } })}><KpiCard label="Enforce share" value={formatShare(kpi.enforce_share)} hint="promoted to production" /></a>
            <a class="overview-kpi-link" href={routeHref("hil-queue")}><KpiCard label={t("overview.detailMetric.approvals")} value={kpi.hil_pending} tone={kpi.hil_pending > 0 ? "warning" : "positive"} hint={kpi.hil_pending > 0 ? t("overview.detailMetric.approvalHint") : t("overview.detailMetric.approvalClear")} /></a>
          </KpiGrid>

          <div class="two-col">
            <section class="stack-section">
              <h3 class="section-title">Actions by kind</h3>
              <CountTable data={kpi.by_action_kind} keyLabel="Action kind" filterKey="action" />
            </section>
            <section class="stack-section">
              <h3 class="section-title">Outcomes</h3>
              <CountTable data={kpi.by_outcome} keyLabel="Outcome" filterKey="outcome" />
            </section>
          </div>
        </div>
      </details>
    </div>
  );
}

function OverviewSection({
  number,
  title,
  description,
  children,
}: {
  readonly number: string;
  readonly title: string;
  readonly description: string;
  readonly children: preact.ComponentChildren;
}) {
  return (
    <section class="overview-section">
      <header class="overview-section-head">
        <span class="overview-section-number" aria-hidden="true">{number}</span>
        <div>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
      </header>
      {children}
    </section>
  );
}

interface KeyCount {
  readonly key: string;
  readonly count: number;
}

function CountTable({
  data,
  keyLabel,
  filterKey,
}: {
  readonly data: Record<string, number>;
  readonly keyLabel: string;
  readonly filterKey: "action" | "outcome";
}) {
  const rows: readonly KeyCount[] = Object.entries(data)
    .sort(([, a], [, b]) => b - a)
    .map(([key, count]) => ({ key, count }));

  const columns: readonly Column<KeyCount>[] = [
    { key: "k", header: keyLabel, render: (r) => <a href={routeHref("audit", { params: { [filterKey]: r.key } })}>{r.key}</a>, cellClass: "mono" },
    { key: "c", header: "Count", render: (r) => r.count, cellClass: "num", headerClass: "num" },
  ];

  return (
    <DataTable
      columns={columns}
      rows={rows}
      keyOf={(r) => r.key}
      empty="No data yet."
    />
  );
}
