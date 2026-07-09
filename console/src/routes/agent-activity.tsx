/**
 * Agent activity - a per-agent timeline reconstructed from the audit log.
 *
 * The Audit and Trace panels answer "what terminal decisions were
 * recorded" and "reconstruct one correlation id". Neither answers the
 * operator's other natural question: **which agent did what work, when,
 * and how**. This panel projects the same append-only audit stream into
 * an agent-attributed timeline so an operator can watch the pantheon at
 * work (Huginn ingests, Forseti judges, Thor opens a remediation PR,
 * Var queues a HIL approval, Saga records it).
 *
 * Read-only: it reuses the GET-only `/audit` projection (no new
 * back-channel) and derives the acting agent from each entry's `actor`
 * (== the producing principal in the pantheon lifecycle). Entries whose
 * actor is not a known agent are grouped under "System".
 */

import { useEffect, useMemo, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import type { AuditItem } from "../types";
import {
  AsyncBoundary,
  EmptyState,
  PageHeader,
  StatusPill,
  type AsyncState,
  type PillKind,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { t } from "../i18n";

interface Props {
  readonly client: ReadApiClient;
}

/** Number of audit rows pulled to build the timeline (newest first). */
const TIMELINE_LIMIT = 200;

/**
 * The 15 fixed pantheon agents keyed by their canonical name, mapped to
 * a coarse "layer" used only for colour + grouping. The names are
 * fork-locked upstream (see architecture.instructions.md § Agent
 * Pantheon), so a static map is safe and avoids a second fetch against
 * the optional `/pantheon/graph` route.
 */
const AGENT_LAYER: Readonly<Record<string, string>> = {
  Odin: "planning",
  Thor: "execution",
  Forseti: "judgment",
  Huginn: "sensing",
  Heimdall: "sensing",
  Var: "approval",
  Vidar: "recovery",
  Bragi: "conversational",
  Saga: "audit",
  Mimir: "governance",
  Norns: "governance",
  Muninn: "governance",
  Njord: "domain",
  Freyr: "domain",
  Loki: "domain",
};

const SYSTEM_AGENT = "System";

/** Resolve the acting agent for one audit row. */
function agentOf(item: AuditItem): string {
  if (item.actor in AGENT_LAYER) return item.actor;
  const principal = item.entry["producer_principal"];
  if (typeof principal === "string" && principal in AGENT_LAYER) return principal;
  return SYSTEM_AGENT;
}

function layerOf(agent: string): string {
  return AGENT_LAYER[agent] ?? "system";
}

/** Free-text "how" for the row: the audit outcome, if present. */
function outcomeOf(item: AuditItem): string | null {
  const outcome = item.entry["outcome"];
  return typeof outcome === "string" ? outcome : null;
}

function summaryOf(item: AuditItem): string | null {
  const summary = item.entry["summary"];
  return typeof summary === "string" ? summary : null;
}

function tierOf(item: AuditItem): string | null {
  const tier = item.entry["tier"];
  return typeof tier === "string" ? tier.toUpperCase() : null;
}

function outcomePill(outcome: string): PillKind {
  if (outcome.includes("hil") || outcome.includes("await")) return "hil";
  if (outcome.includes("escalat")) return "warning";
  if (outcome === "auto") return "auto";
  if (outcome.includes("pr_opened") || outcome.includes("recorded")) return "success";
  if (outcome.includes("matched") || outcome.includes("normalized")) return "info";
  return "neutral";
}

function modePill(mode: string): PillKind {
  if (mode === "enforce") return "enforce";
  if (mode === "shadow") return "shadow";
  return "neutral";
}

/** HH:MM:SS in the browser locale for a compact timeline stamp. */
function stamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString();
}

interface Data {
  readonly items: readonly AuditItem[];
}

export function AgentActivityRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<Data>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const page = await client.listAudit({ limit: TIMELINE_LIMIT });
        if (!cancelled) setState({ status: "ready", data: { items: page.items } });
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
        title={t("route.agentActivity")}
        subtitle="Per-agent timeline reconstructed from the audit log - which agent did what, when, and how. Read-only projection of the same append-only record."
      />
      <AsyncBoundary state={state} resourceLabel="agent activity">
        {(data) => <ActivityBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

interface BodyProps {
  readonly data: Data;
}

function ActivityBody({ data }: BodyProps) {
  const [selected, setSelected] = useState<string | null>(null);

  // Newest first: the audit projection already returns newest-first, so
  // preserve that order for the timeline.
  const perAgent = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of data.items) {
      const agent = agentOf(item);
      counts.set(agent, (counts.get(agent) ?? 0) + 1);
    }
    // Known agents first (in count order), System last.
    return [...counts.entries()]
      .sort((a, b) => {
        if (a[0] === SYSTEM_AGENT) return 1;
        if (b[0] === SYSTEM_AGENT) return -1;
        return b[1] - a[1];
      });
  }, [data.items]);

  const visible = useMemo(
    () =>
      selected === null
        ? data.items
        : data.items.filter((item) => agentOf(item) === selected),
    [data.items, selected],
  );

  usePublishViewContext(
    () => ({
      routeId: "agent-activity",
      routeLabel: "Agent activity",
      headline: `${data.items.length} audit row(s) across ${perAgent.length} agent(s)${
        selected ? ` - filtered to ${selected}` : ""
      }`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "rows", value: data.items.length, group: "page" },
        { key: "agents", value: perAgent.length, group: "page" },
        { key: "filter", value: selected ?? "all", group: "page" },
      ],
      records: {
        by_agent: perAgent.map(([agent, count]) => ({ agent, count })),
      },
    }),
    [data.items, perAgent, selected],
  );

  if (data.items.length === 0) {
    return (
      <EmptyState
        title="No agent activity yet"
        body="Once the control loop records decisions, each agent's work appears here as a timeline."
      />
    );
  }

  return (
    <div class="stack">
      <div class="agent-filter" role="tablist" aria-label="Filter by agent">
        <button
          type="button"
          class={`agent-chip ${selected === null ? "agent-chip-on" : ""}`}
          role="tab"
          aria-selected={selected === null}
          onClick={() => setSelected(null)}
        >
          All
          <span class="agent-chip-count">{data.items.length}</span>
        </button>
        {perAgent.map(([agent, count]) => (
          <button
            key={agent}
            type="button"
            class={`agent-chip ${selected === agent ? "agent-chip-on" : ""}`}
            role="tab"
            aria-selected={selected === agent}
            data-layer={layerOf(agent)}
            onClick={() => setSelected((s) => (s === agent ? null : agent))}
          >
            <span class="agent-dot" data-layer={layerOf(agent)} aria-hidden="true" />
            {agent}
            <span class="agent-chip-count">{count}</span>
          </button>
        ))}
      </div>

      <ol class="timeline" aria-label="Agent activity timeline">
        {visible.map((item) => (
          <TimelineRow key={item.seq} item={item} />
        ))}
      </ol>
    </div>
  );
}

function TimelineRow({ item }: { readonly item: AuditItem }) {
  const agent = agentOf(item);
  const layer = layerOf(agent);
  const outcome = outcomeOf(item);
  const summary = summaryOf(item);
  const tier = tierOf(item);

  return (
    <li class="timeline-row">
      <span class="timeline-marker" data-layer={layer} aria-hidden="true" />
      <div class="timeline-card">
        <div class="timeline-head">
          <span class="timeline-agent" data-layer={layer}>
            {agent}
          </span>
          <span class="timeline-action mono">{item.action_kind}</span>
          <span class="timeline-time mono muted">{stamp(item.recorded_at)}</span>
        </div>
        {summary ? <p class="timeline-summary">{summary}</p> : null}
        <div class="timeline-meta">
          {tier ? <span class="timeline-tier mono">{tier}</span> : null}
          <StatusPill kind={modePill(item.mode)} label={item.mode} />
          {outcome ? <StatusPill kind={outcomePill(outcome)} label={outcome} /> : null}
          {item.correlation_id ? (
            <a
              class="timeline-corr mono"
              href={`#/trace?correlation=${encodeURIComponent(item.correlation_id)}`}
              title="Open this correlation in the Trace panel"
            >
              {item.correlation_id}
            </a>
          ) : null}
        </div>
      </div>
    </li>
  );
}
