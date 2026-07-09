import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import type { DashboardKpi } from "../types";
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
import { t } from "../i18n";

interface Props {
  readonly client: ReadApiClient;
}

function formatShare(x: number): string {
  return `${(x * 100).toFixed(1)}%`;
}

export function DashboardRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<DashboardKpi>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const kpi = await client.dashboardMetrics();
        if (!cancelled) setState({ status: "ready", data: kpi });
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
    <div class="stack">
      <PageHeader
        title={t("route.dashboard")}
        subtitle={
          <>
            Rolled-up control-plane KPIs sourced from the append-only audit log.
            Numbers refresh on panel reload; no polling.
          </>
        }
      />
      <AsyncBoundary state={state} resourceLabel="dashboard KPIs">
        {(kpi) => <DashboardBody kpi={kpi} />}
      </AsyncBoundary>
    </div>
  );
}

function DashboardBody({ kpi }: { readonly kpi: DashboardKpi }) {
  usePublishViewContext(
    () => ({
      routeId: "dashboard",
      routeLabel: "Dashboard",
      headline: `${kpi.event_count} events - shadow ${formatShare(kpi.shadow_share)} - HIL pending ${kpi.hil_pending}`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "event_count", value: kpi.event_count, group: "kpi" },
        { key: "shadow_share", value: formatShare(kpi.shadow_share), group: "kpi" },
        { key: "enforce_share", value: formatShare(kpi.enforce_share), group: "kpi" },
        { key: "hil_pending", value: kpi.hil_pending, group: "kpi" },
        { key: "last_recorded_at", value: kpi.last_recorded_at, group: "kpi" },
      ],
      records: {
        by_action_kind: Object.entries(kpi.by_action_kind)
          .sort(([, a], [, b]) => b - a)
          .map(([key, count]) => ({ key, count })),
        by_outcome: Object.entries(kpi.by_outcome)
          .sort(([, a], [, b]) => b - a)
          .map(([key, count]) => ({ key, count })),
      },
    }),
    [kpi],
  );
  return (
    <div class="stack">
      <KpiGrid>
        <KpiCard
          label="Events (audit)"
          value={kpi.event_count}
          hint="terminal audit entries"
        />
        <KpiCard
          label="Shadow share"
          value={formatShare(kpi.shadow_share)}
          hint="judge-only, no mutation"
          tone={kpi.shadow_share > 0.95 ? "positive" : "default"}
        />
        <KpiCard
          label="Enforce share"
          value={formatShare(kpi.enforce_share)}
          hint="promoted to production"
        />
        <KpiCard
          label="HIL pending"
          value={kpi.hil_pending}
          tone={kpi.hil_pending > 0 ? "warning" : "positive"}
          hint={kpi.hil_pending > 0 ? "needs a human approver" : "no waiting approvals"}
        />
      </KpiGrid>

      <div class="two-col">
        <section class="stack-section">
          <h3 class="section-title">Actions by kind</h3>
          <CountTable data={kpi.by_action_kind} keyLabel="Action kind" />
        </section>
        <section class="stack-section">
          <h3 class="section-title">Outcomes</h3>
          <CountTable data={kpi.by_outcome} keyLabel="Outcome" />
        </section>
      </div>

      {kpi.last_recorded_at !== null ? (
        <p class="muted footnote">Last audit entry: {kpi.last_recorded_at}</p>
      ) : null}
    </div>
  );
}

interface KeyCount {
  readonly key: string;
  readonly count: number;
}

function CountTable({
  data,
  keyLabel,
}: {
  readonly data: Record<string, number>;
  readonly keyLabel: string;
}) {
  const rows: readonly KeyCount[] = Object.entries(data)
    .sort(([, a], [, b]) => b - a)
    .map(([key, count]) => ({ key, count }));

  const columns: readonly Column<KeyCount>[] = [
    { key: "k", header: keyLabel, render: (r) => r.key, cellClass: "mono" },
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
