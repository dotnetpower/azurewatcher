import { useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
  type PillKind,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";

/**
 * Rule-fire trace viewer panel. Given a correlation id, calls
 * ``GET /audit/{correlation_id}/trace`` and renders the ordered
 * pipeline stages so an on-call sees "why did rule X fire?" without
 * hand-grepping the audit log.
 */

interface TraceStep {
  readonly seq: number;
  readonly recorded_at: string;
  readonly stage: string;
  readonly decision: string | null;
  readonly reason: string | null;
  readonly action_kind: string;
  readonly mode: string;
  readonly entry_hash: string;
}

interface TraceResponse {
  readonly correlation_id: string;
  readonly step_count: number;
  readonly steps: readonly TraceStep[];
  readonly terminal_stage: string | null;
}

interface Props {
  readonly client: ReadApiClient;
}

export function RuleTraceRoute({ client }: Props) {
  const [correlationId, setCorrelationId] = useState("corr-dev-0001");
  const [state, setState] = useState<AsyncState<TraceResponse>>({ status: "idle" });

  async function fetchTrace(): Promise<void> {
    if (!correlationId) return;
    setState({ status: "loading" });
    try {
      const data = await client.panel<TraceResponse>(
        `/audit/${encodeURIComponent(correlationId)}/trace`,
      );
      setState({ status: "ready", data });
    } catch (err) {
      setState({
        status: "error",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }

  return (
    <div class="stack">
      <PageHeader
        title="Trace"
        subtitle='Reconstruct the pipeline path for one correlation id. Read-only projection over the audit log; the trace is never re-executed.'
      />

      <section class="stack-section">
        <h3 class="section-title">Look up a correlation id</h3>
        <form
          class="form-grid inline"
          onSubmit={(e) => {
            e.preventDefault();
            void fetchTrace();
          }}
        >
          <label>
            Correlation id
            <input
              type="text"
              value={correlationId}
              onInput={(e) => setCorrelationId((e.target as HTMLInputElement).value)}
              required
            />
          </label>
          <button
            type="submit"
            class="btn primary"
            disabled={state.status === "loading" || !correlationId}
          >
            Fetch trace
          </button>
        </form>
      </section>

      <AsyncBoundary
        state={state}
        resourceLabel="trace"
        idle={<p class="muted footnote">Enter a correlation id and click Fetch.</p>}
      >
        {(data) => <TraceView data={data} />}
      </AsyncBoundary>
    </div>
  );
}

function decisionPill(decision: string | null): PillKind {
  if (decision === null) return "neutral";
  const v = decision.toLowerCase();
  if (v === "auto") return "auto";
  if (v === "hil") return "hil";
  if (v === "deny") return "danger";
  if (v === "abstain") return "neutral";
  if (v === "done" || v === "ok") return "success";
  if (v === "failed") return "danger";
  return "info";
}

function modePill(mode: string): PillKind {
  if (mode === "enforce") return "enforce";
  if (mode === "shadow") return "shadow";
  return "neutral";
}

function TraceView({ data }: { readonly data: TraceResponse }) {
  usePublishViewContext(
    () => ({
      routeId: "trace",
      routeLabel: "Trace",
      headline: `${data.step_count} step(s) for ${data.correlation_id}${data.terminal_stage ? ` - terminal ${data.terminal_stage}` : ""}`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "correlation_id", value: data.correlation_id, group: "trace" },
        { key: "step_count", value: data.step_count, group: "trace" },
        { key: "terminal_stage", value: data.terminal_stage, group: "trace" },
      ],
      records: {
        steps: data.steps.map((s) => ({
          seq: s.seq,
          recorded_at: s.recorded_at,
          stage: s.stage,
          decision: s.decision,
          reason: s.reason,
          action_kind: s.action_kind,
          mode: s.mode,
        })),
      },
    }),
    [data],
  );

  const columns: readonly Column<TraceStep>[] = [
    { key: "n", header: "#", render: (s) => s.seq, cellClass: "num", headerClass: "num" },
    { key: "at", header: "Recorded at", render: (s) => s.recorded_at, cellClass: "mono" },
    { key: "stage", header: "Stage", render: (s) => s.stage || <span class="muted">(unnamed)</span>, cellClass: "mono" },
    { key: "kind", header: "Action kind", render: (s) => s.action_kind, cellClass: "mono" },
    {
      key: "dec",
      header: "Decision",
      render: (s) =>
        s.decision === null
          ? <span class="muted">-</span>
          : <StatusPill kind={decisionPill(s.decision)} label={s.decision} />,
    },
    { key: "reason", header: "Reason", render: (s) => s.reason ?? <span class="muted">-</span> },
    {
      key: "mode",
      header: "Mode",
      render: (s) => <StatusPill kind={modePill(s.mode)} label={s.mode} />,
    },
  ];

  return (
    <div class="stack">
      <KpiGrid>
        <KpiCard label="Steps" value={data.step_count} />
        <KpiCard
          label="Terminal stage"
          value={<span class="mono">{data.terminal_stage ?? "-"}</span>}
        />
        <KpiCard
          label="Correlation id"
          value={<span class="mono small">{data.correlation_id}</span>}
        />
      </KpiGrid>
      <section class="stack-section">
        <h3 class="section-title">Timeline</h3>
        <DataTable
          columns={columns}
          rows={data.steps}
          keyOf={(s) => s.seq}
          empty="No audit steps for this correlation id."
        />
      </section>
    </div>
  );
}
